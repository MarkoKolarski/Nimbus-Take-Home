# Decisions Log

Format: ADR-lite. Each entry corresponds to one build block; where a block ends on a
git tag, the tag message is this entry.

---

## v0.1-skeleton — 2026-08-16

### Context

First block: `docker compose up --build` must bring up an empty but correct system —
database, S3 emulator, backend, frontend — with 2 test users and fixture files already
loaded, so every later block has something to build on instead of building
infrastructure as it goes.

### Decisions

1. **The entire `public` control-plane schema (users, tenants, sync_jobs) in one
   Alembic migration**, even though `sync_jobs` isn't touched by any code until the
   "Sync state + worker" block. §3 treats them as one unit; a second migration just for
   `sync_jobs` later wouldn't buy anything.
2. **`provision_tenant()` writes the full 7-table DDL up front** (datasources,
   directories, documents, contents, chunks, chats, chat_messages), even though most of
   them sit unused until later blocks. §3 explicitly calls provisioning "one versioned
   function" — not incremental per-block construction.
3. **`users.password_hash` added ahead of §3's trimmed column list** — the Auth block
   already promises a real email+password screen for these two users, and this is the
   block that creates those rows; adding the column now is cheaper than an `ALTER
   TABLE` later.
4. **Tenant schema name = `tenant_` + slug of the email's local part**
   (`tenant_alice`, `tenant_bob`) — readable for a demo, deliberately not
   collision-safe for future JIT-provisioned users (a v1.5 concern).
5. **`tests/test_seed.py` as a fourth test file**, outside §8's list of three
   (test_isolation/test_dedup/test_sync_state) — CLAUDE.md requires `pytest -q` to
   actually pass as proof a block is done; with zero tests, pytest exits 5, not a clean
   pass. This is its own, ongoing concern (is bootstrap correct), not a duplicate of
   the other three.
6. **No FK in the tenant schema uses `ON DELETE CASCADE`** — §4's removal design
   explicitly manages delete order at the application level (soft-delete → refcount →
   only then hard-delete the parent); the default `RESTRICT` enforces that at the
   database level too.
7. **Deliberately out of scope**: routes beyond `/health`, ORM domain models,
   `SET LOCAL search_path`, the fastembed/pypdf/langchain dependencies, README. All
   already scheduled for later blocks.

### Bugs found and fixed during the build

- **Wrong DB driver.** `database_url` defaulting to `postgresql://...` would resolve to
  `psycopg2` under SQLAlchemy, which isn't even installed (`psycopg` v3 is). Fix: a
  `sqlalchemy_database_url` property that appends `+psycopg` only for SQLAlchemy
  consumers; raw `psycopg.connect()` calls (seed, provisioning) keep using the plain
  DSN form.
- **npm workspaces hoist the lockfile to the repo root.** The root `package.json`
  already declares `workspaces: ["apps/*"]`, so `npm install` inside `apps/web` puts
  `node_modules`/`package-lock.json` in the repo root, not locally. Fix: the Docker
  build context for `web` is the repo root, not `apps/web`.
- **Healthcheck falsely reported "unhealthy" while the site worked fine.** Inside the
  `nginx:alpine` container, `localhost` resolves to both `127.0.0.1` and `::1`; `wget`
  tried IPv6 first and got connection refused since nginx only listens on IPv4, even
  though the site was completely alive from outside. Fix: healthcheck targets
  `127.0.0.1` directly.

### Verification

Full system (6 services) verified from a clean state (`docker compose down -v` then
`up --build`): every service healthy/exited-0, `pytest -q` → 3 passed, `\dn` shows
`public` + `tenant_alice` + `tenant_bob`, all 6 fixture files present in the S3 bucket,
re-running `seed` on a warm database duplicates nothing.

---

## v1.0-core / Auth — 2026-08-16

### Context

First functional block after the skeleton: login, logout, `get_current_user` as the
single source of identity. Every later route (Tenant layer onward) depends on this
dependency existing.

### Decisions

1. **Backend-only in this block; the login screen waits for the "React UI" block.**
   SPEC/§8 describes "a real email+password screen, not a bare identity picker" — that
   is an API contract (an email+password body, not a user selector), not a requirement
   that `apps/web` has a form already. React UI is already budgeted as a separate
   60-minute block that builds the one screen; touching `apps/web` twice would be
   wasted effort. This assumption is recorded in BUILDPLAN.md too.
2. **JWT in an httpOnly cookie** (`access_token`), `samesite=lax`, `secure=False` —
   local http demo, same origin through the nginx `/api/` proxy, no CORS.
3. **Login is enumeration-safe**: a wrong email and a wrong password both return the
   identical `401 {"detail": "invalid credentials"}` — the same logic as the
   404-not-403 rule for documents (§3), never revealing which account exists.
4. **`get_current_user` reads `public.users` directly through SQLAlchemy `text()`**,
   with no ORM model — no model for `users` exists yet, and building one to run exactly
   one query would be a premature abstraction. ORM domain models arrive in the Tenant
   layer block.
5. **`get_db()` added to `core/db.py` now, plain.** The Tenant layer block will extend
   it with `SET LOCAL search_path` in the same transaction — a natural next step, not a
   throwaway abstraction.
6. **A route-introspection test (`test_no_route_accepts_user_id_...`) lands in this
   block, not later** — it's the mechanism that guards the CLAUDE.md invariant ("no
   route accepts `user_id`"), so every route added after this block is already covered.
7. **The dev JWT secret is a hardcoded default in `config.py`, not required in
   `.env.example`** — the SPEC requirement is that `OPENROUTER_API_KEY` is the only
   required key; the JWT secret is overridable via env for anything more serious than a
   local demo.

### Verification

`docker compose up --build` from a warm state, then
`docker compose exec -T api pytest -q` → **11 passed** (3 from `test_seed.py` + 8 new
in `test_auth.py`: login succeeds with an httponly cookie, wrong password, unknown
email returns the same 401, `/auth/me` without a cookie → 401, alice/bob return
distinct correct identities without cross-contamination, a forged JWT (real `sub`,
wrong signature) → 401, logout clears the cookie and the next `/auth/me` → 401,
route-introspection test). Also confirmed manually through a real HTTP stack (`curl`
login/me for both users through `localhost:8000`) — cookie jars for alice and bob
return exactly their own identities, no cookie → 401, wrong password → 401.

---

## v1.0-core / Tenant layer — 2026-08-16

### Context

`provision_tenant()` and `public.tenants` already existed (v0.1-skeleton, ahead of
plan). What was actually left for this block: a session dependency that runs
`SET LOCAL search_path` from a verified token, and an ORM model set that resolves
through it — with no `schema=` argument anywhere. No SQLAlchemy ORM model existed in
the repo before this; the next five blocks (Datasource+S3, Directories, Sync, Ingest,
Chat) build directly on this layer.

### Decisions

1. **`app/tenancy/registry.py`, not `core/db.py`, owns the tenant-session mechanism.**
   `core/security.py` already imports `get_db` from `core/db.py`; if the tenant-scoped
   session dependency lived in `db.py` and needed `CurrentUser`/`get_current_user` as a
   `Depends()` parameter, that would be a circular import. `tenancy/registry.py` keeps
   a one-directional layering: `core` (general DB/identity infrastructure) ←
   `tenancy` (identity → schema mapping) ← routes. This is also exactly the filename
   BUILDPLAN.md already anticipates in §8 (`tenancy/{provision,registry}.py`).
2. **`tenant_session(user_id)` as a context manager underneath the FastAPI
   dependency**, not a generator tied directly to `Depends`. §3 explicitly says the
   worker (the "Sync state + worker" block) must do the identical thing with a bare
   `user_id` from a `sync_jobs` row, with no HTTP request to hang a `Depends()` off of.
   Sharing the mechanism now means the worker later just calls `tenant_session()`, no
   duplicated logic. The commit happens inside `tenant_session` itself (not in every
   writing route individually) — every future route that writes will use this, so a
   centralized commit/rollback means no future block can forget it.
3. **`SET LOCAL search_path` goes through `psycopg.sql.Identifier`, executed on the
   Session's own connection** (`Session.connection().connection.dbapi_connection` for
   quoting, `Connection.exec_driver_sql()` to execute) — stays on the same transaction
   the Session uses for every later query in that request, through the one audited path
   for quoting a schema name, same as in `provision.py`. `schema_name` is read from
   `public.tenants` (`.scalar_one()`), never from user input.
4. **All 7 tenant models declared at once, in one file**, even though most routes
   won't use them until later blocks — `domain/models.py` is created for the first time
   in this block, so one pass against `provision_tenant()`'s DDL is cheaper than five
   partial checks spread across blocks. This is also the literal meaning of the
   CLAUDE.md invariant "one model set serves every tenant." `chunks.embedding` uses
   `pgvector.sqlalchemy.Vector(384)` — `pgvector` added to `requirements.txt` (not a
   dependency until now), even though the column isn't read/written until the "Ingest +
   dedup" block.
5. **Alembic still doesn't touch tenant schemas** (`migrations/env.py` has
   `target_metadata = None`) — `provision_tenant()`'s hand-written DDL remains the sole
   source of truth for tenant table shape; `domain/models.py` is a second,
   hand-maintained description of the same shape, used only for runtime ORM queries.
   The existing asymmetry from §8 ("Alembic for `public`, versioned DDL for tenants")
   isn't changed by this block, just extended with the ORM side.

### Verification

`docker compose up --build` (rebuilds the `api`/`worker` images for the new `pgvector`
package), then `docker compose exec -T api pytest -q` → **14 passed** (11 existing + 3
new in `test_isolation.py`: `SHOW search_path` contains exactly the right schema per
user, an ORM write through Alice's session isn't visible through Bob's and vice versa —
same model, same unqualified table name, physically a different table — and SPEC.md
§3's v1.0 meta-test: with no `search_path` set, an unqualified query against
`datasources` fails with `UndefinedTable`).

---

## v1.0-core / Datasource + S3 — 2026-08-16

### Context

First block that actually exercises the tenant-scoped ORM layer (`get_tenant_db`,
`Datasource` model) through a real HTTP route, not just a direct test — confirmation
that the previous block's mechanism holds under a real request. Registering a
directory (turning a browsed prefix into a tracked `directories` row) is the next,
separate block — this one stops at: connect a datasource, store its config safely,
allow browsing prefixes.

### Decisions

1. **The Fernet key is a fixed dev default in `config.py`, not a required env
   variable** — same pattern as `jwt_secret_key` (Auth block). It must be fixed, not
   regenerated on every startup: Postgres data survives a `docker compose up` restart
   (only `-v` wipes it), so a changing key would strand every already-encrypted
   `config_encrypted` row. Keeps the §12 promise that `OPENROUTER_API_KEY` is the only
   required key.
2. **The `Connector` Protocol gets all three methods at once**
   (`list_prefixes`, `list_objects`, `get_object_bytes`), `S3Connector` implements all
   three, but this route only calls `list_prefixes`. §7 (the v1.4 section) already
   names exactly this trio as the shape `GoogleDriveConnector` must share with
   `S3Connector` — writing all three now means Sync and Ingest (which need
   `list_objects`/`get_object_bytes`) don't touch this Protocol's contract later. Same
   logic as "all 7 tenant models at once" in the previous block.
3. **No connection check on `POST /datasources`.** A bad bucket/credentials fails
   loudly on the next call (`browse`), which is also the next step in the demo script
   (§9: connect → browse → register). Checking in both places would duplicate work for
   a 35-minute block.
4. **`browse` doesn't map `botocore` errors into a dedicated taxonomy** — a raw
   `ClientError` surfacing as a 500 is acceptable for this block; nicer provider-error
   mapping isn't what the brief is testing.
5. **Pydantic schemas (`S3ConnectionConfig`, `DatasourceCreate`, `DatasourceOut`) live
   in `datasources.py`, not in `domain/schemas.py`** — same pattern as `auth.py`
   (`LoginRequest`, `UserOut` are also local). Nothing else uses them yet, so a shared
   schemas file would split one route's types across two files for no benefit.
6. **`GET /datasources/{id}/browse` on someone else's ID returns 404, not 403** — free
   from tenant-schema isolation: a foreign ID simply isn't a row in this tenant's
   table, so "doesn't exist" and "exists but isn't yours" look identical. Same property
   §3 requires for documents/sync.
7. **New test file `test_datasources.py`, not an extended `test_isolation.py`** — same
   precedent as `test_seed.py`/`test_auth.py`: one file per feature (including its own
   isolation checks), `test_isolation.py` stays the lower-level DB/session mechanism
   layer.

### Verification

`docker compose up --build` (new `cryptography` package), then
`docker compose exec -T api pytest -q` → **18 passed** (14 existing + 4 new in
`test_datasources.py`: creating + listing returns `DatasourceOut` with no config field,
`browse` against real LocalStack returns real prefixes (`alice/contracts/`,
`alice/duplicates/`), proving the full path encrypt → store → decrypt → boto3 call,
Alice's datasource doesn't show up in Bob's list, Bob's `browse` on Alice's ID → 404).

---

## v1.0-core / Directories — 2026-08-16

### Context

The `directories` table and `Directory` ORM model already existed (v0.1-skeleton,
Tenant layer block) — what was left for this block was pure API surface over an
existing schema: register, list, delete. No `documents` row can point at a directory
yet, since Sync and Ingest don't exist — so deleting a directory in this block is a
plain `DELETE`, with no cascade logic.

### Decisions

1. **Register/list nested under `/datasources/{id}/directories`, delete flat as
   `/directories/{id}`.** Matches the pattern SPEC.md itself uses when referencing this
   endpoint in §3/§4 (`DELETE /directories/{id}`), and is symmetric with the existing
   `GET /datasources/{id}/browse` from the previous block — register/list logically
   need the parent (which datasource), delete doesn't.
2. **404 on a missing/foreign `datasource_id`, same logic as `browse`.**
   `_get_datasource_or_404` runs the identical check the previous block already
   introduced for `browse_datasource` — tenant isolation is a free consequence of
   `search_path`, "doesn't exist" and "exists but isn't yours" look identical for both
   register and list.
3. **A duplicate `(datasource_id, prefix)` registration → `409`, not `500`.** The table
   already has `UNIQUE(datasource_id, prefix)` (Tenant layer block); the route catches
   `IntegrityError` and translates it into a readable HTTP status — same pattern as
   SPEC's description of the `sync_jobs` partial unique index (the database is the
   source of truth for the constraint, the app just translates it readably).
4. **`_get_datasource_or_404` helper stays local to `directories.py`, not moved into
   `datasources.py`.** Used twice within the same file (register + list); sharing it
   with an already-finished `datasources.py` would mean touching a completed block for
   three lines that aren't repeated anywhere else.
5. **No cascade/refcount logic in `DELETE /directories/{id}` in this block,
   deliberately.** The full version (soft-delete every document in the directory →
   refcount on `chunks`/`contents` → only then hard-delete the `directories` row, §4)
   is explicitly budgeted as part of the later **Removal** block, once Sync and Ingest
   can actually populate `documents`. Adding that logic now would be dead code —
   nothing yet exists to trigger it.
6. **New test file `test_directories.py`, same precedent as `test_datasources.py`** —
   one file per feature, including its own isolation checks (register/list/delete on a
   foreign resource → `404`, not `403`).

### Bugs found and fixed during the build

- **`api`/`worker` have no bind mount — code is baked into the image at build time.**
  The first `pytest` run after writing the code quietly reported "18 passed" (the old
  number, the old image) — the new route and new test file weren't inside the
  container at all. Fix: every code change during this block needed
  `docker compose up --build api` before `pytest`, not just `exec`. A lesson worth
  carrying into every later block — "test passed" without a rebuild proves nothing
  here.
- **Test cleanup failed on an FK, not on `search_path`.** `_delete_datasource` deleted
  a `Datasource` row without first deleting its `Directory` rows;
  `directories_datasource_id_fkey` (deliberately without `ON DELETE CASCADE`,
  v0.1-skeleton decision #6) correctly rejected that. Fix: `_delete_datasource` now
  finds and deletes all `Directory` rows for that `datasource_id` first, an explicit
  `db.flush()`, only then deletes the `Datasource` — without `flush()`, SQLAlchemy has
  no guaranteed DELETE ordering when there's no `relationship()` between the models,
  only a `ForeignKey` column.

### Verification

`docker compose up --build api` then `docker compose exec -T api pytest -q` → **24
passed** (18 existing + 6 new in `test_directories.py`: register + list, duplicate
prefix registration → `409`, registering under a nonexistent `datasource_id` → `404`,
delete removes it from the list, Bob's register/list on Alice's `datasource_id` → `404`
for both, Bob deleting Alice's `directory_id` → `404` and the row is untouched).

---

## v1.0-core / Sync state + worker — 2026-08-16

### Context

`sync_jobs` and its partial unique index already existed (v0.1-skeleton), with zero
code using them. What was left for this block: it becomes a real mechanism — an
enqueue/poll API and a real worker loop, instead of a `worker.py` that until now just
slept. `documents`/`contents`/`chunks` aren't touched at all in this block — §8 draws
that boundary explicitly (see decision #1).

### Decisions

1. **In this block, the worker only LISTs and counts — it doesn't touch `documents`.**
   §8 separates this block (`sync_jobs`, partial unique index, `SKIP LOCKED` loop,
   polling endpoint) from "Ingest + dedup" (streaming sha256, extraction, chunking,
   embedding, **all three dedup layers** — including layer 1,
   `(source_key, etag, size)`). Since layer 1 explicitly belongs to the next block, the
   work here stops at `connector.list_objects(prefix)` and
   `stats = {"scanned": N}`. Deliberately no `unchanged`/`indexed`/`deduped` keys with
   fake zeros — that would look like "0 indexed" instead of "not implemented yet." This
   assumption is also recorded in BUILDPLAN.md.
2. **`sync_jobs` stays raw SQL, with no ORM model** — same pattern as
   `public.users`/`public.tenants` in `security.py`/`registry.py`, `text()` with an
   explicit `public.sync_jobs` prefix. A table accessed only by
   `id`/`directory_id`/`user_id` doesn't get an ORM model just to have one.
3. **The claim step runs on a bare `SessionLocal()`, not on `tenant_session`.** The
   worker doesn't know which tenant a job belongs to until it reads `user_id` from the
   claimed row — `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1` then immediately
   `UPDATE ... state='running'`, same transaction, commit. Only after that does
   `run_sync` open `tenant_session(user_id)` for the `Directory`/`Datasource` and the S3
   call — exactly the split `registry.py`'s docstring (Tenant layer block) already
   anticipates.
4. **A 409 response body requires a query after the failed INSERT, which requires an
   explicit rollback.** A unique-index violation aborts the current Postgres
   transaction; every following query on the same connection fails until the
   transaction is rolled back. Since that rollback also clears `SET LOCAL search_path`,
   the following query for the existing job must be explicitly `public.`-qualified
   (not a tenant table, so that's not a problem). Same 409 pattern as the Directories
   block (`IntegrityError` → readable status), plus the extra rollback here because the
   response body is needed too, not just the status code.
5. **A job-level error goes into `stats.error`, not a new column.** `sync_jobs` has
   `error_count` (int, reserved for v1.2's per-file counter), but no text `error`
   column. A whole-job failure (directory disappeared before the worker reached it, bad
   connector config) is a different kind of failure from a per-file one; the JSONB
   field that already exists is cheaper than a migration for a column v1.2 would
   probably want shaped differently anyway.
6. **`GET` before any sync ever ran → `404`.** SPEC/§5 describes four states (nothing
   new / in progress / running / finished), not a fifth for "never run." Treated like
   any other missing resource in this codebase (404, not an empty object) — the same
   404-not-403 line used everywhere else.
7. **One deliberately triggered `failed` path, via a directly inserted row.** A
   realistic `failed` scenario (directory deleted between enqueue and claim) would
   require racing a real worker to make the test deterministic. The test instead
   inserts a `sync_jobs` row directly (`db_conn`) with a `directory_id` that doesn't
   exist in any tenant schema, and polls `public.sync_jobs.state` directly — the only
   way to reliably cover `run_sync`'s except branch without flakiness.

### Bugs found and fixed during the build

- **`:stats::jsonb` in `text()` SQL silently swallowed the bind parameter.**
  SQLAlchemy's `text()` bind-parameter parser gets confused by `::` right after a
  parameter name — `:stats` was never recognized as a bind, was left literally in the
  SQL, and psycopg failed with "syntax error at or near ':'" only inside the worker
  (not on the API request itself). The worker crashed on its first job and stayed dead
  until the next `docker compose up`, leaving jobs stuck in `queued`/`running` forever —
  exactly the scenario BUILDPLAN.md had already named as a known v1.0 limitation (no
  reaper), just for the wrong reason (a bug, not an actual dead worker). Fix:
  `CAST(:stats AS jsonb)` instead of `::` everywhere `stats` is written.

### Verification

`docker compose up -d --build` (rebuilds `api` and `worker`, neither has a bind mount),
then `docker compose exec -T api pytest -q` → **30 passed** (24 existing + 6 new in
`test_sync_state.py`: enqueue → the worker actually finishes a job with
`stats.scanned == 3` against real `alice/contracts/` fixtures, a second click in a row →
`409` with the existing job in the body, Bob's POST/GET on Alice's `directory_id` → `404`
for both, POST on a nonexistent `directory_id` → `404`, GET before any sync ran → `404`,
the worker marks a job `failed` when the directory doesn't exist).

---

## v1.0-core / Ingest + dedup — 2026-08-16

### Context

The `sync_jobs`/`SKIP LOCKED` loop and polling endpoint already existed (Sync state +
worker block), but the worker had so far only counted objects — `documents`/`contents`/
`chunks` had never been touched. What was left for this block was the core of the whole
system: `run_sync` had to actually download bytes, extract text, chunk it, embed it,
and write it, honoring all three dedup layers from SPEC.md §4 and the live-document
predicate from the CLAUDE.md invariant. Without this block, Chat + RAG (two blocks
later) has nothing to work with.

### Decisions

1. **The three dedup layers as three sequential, short-circuiting checks inside
   `ingest_object()`**, not three separate passes over the listing. Layer 1 (an
   existing `documents` row for `(directory_id, source_key)` whose
   `remote_etag`/`remote_size` match) returns before any network call. If that row
   exists but isn't live, the function still leaves it alone — that alone is enough to
   make "removal survives a re-sync" (§4) already correct now, even though nothing sets
   `removed_at` yet (that part arrives in the "Removal" block). Layer 2
   (`contents[content_hash]` already exists) skips extraction/chunking/embedding, only
   writes the `documents` row. Order matters: layer 1 must run first because it's the
   only one that avoids a network call at all.
2. **The live predicate is centralized in `app/domain/refcount.py`**
   (`is_live_clause()` + `release_content_if_orphaned()`), not an inline condition in
   `ingest/index.py`. This block is the first place the predicate gets used (layer-3
   dedup check and refcount on a content change at the same path) — the "Removal" block
   and v1.2's `known_keys` diff import it rather than making another copy, exactly as
   CLAUDE.md requires.
3. **A changed file at the same path pushes the old `content_hash` through refcount
   immediately, in this block, not deferred to "Removal."** SPEC.md §4 ("same path +
   different bytes → new content, old chunks are released") is part of the dedup
   definition, not removal — leaving the old `chunks`/`contents` rows orphaned here
   would be the same kind of silent data loss CLAUDE.md explicitly forbids.
4. **`run_sync` drops the `tenant_session()` helper and manages the session by hand**
   (same style as `claim_next_queued_job`), because SPEC §5 requires a commit per
   document (a worker dying mid-run → restart resumes, doesn't start over), and
   `tenant_session()` only commits once at the end. Since `SET LOCAL search_path` is
   transaction-scoped, it has to be reissued after every `db.commit()` in the loop —
   otherwise the next unqualified query in the loop can't see the tenant tables.
5. **Chunking: `RecursiveCharacterTextSplitter`, `chunk_size=1500`,
   `chunk_overlap=200` characters** — SPEC doesn't prescribe numbers. 1500 characters is
   roughly 375 tokens by the `len(text)//4` estimate (the same formula BUILDPLAN
   already names for v1.6 compaction), safely under the 512-token limit of
   `bge-small-en-v1.5`. `chunks.token_count` is filled using the same formula. This
   assumption is also recorded in BUILDPLAN.md.
6. **"Streaming sha256" read as the hashlib streaming API, not a new S3-streaming
   protocol.** `app/ingest/hash.py` hashes through `.update()` in 1MB chunks, but
   `Connector.get_object_bytes` still returns the full byte string — fixtures are small
   files, and real network-streaming download would require changing the `Connector`
   Protocol through `S3Connector`, outside this block's budget.
7. **The embedder sits behind its own `Protocol`** (`app/ingest/embed.py`), the model
   loaded lazily and cached at the process level — same pattern as `Connector`. The
   Dockerfile gets a build-time step that pre-downloads the `bge-small-en-v1.5` ONNX
   model, since `api`/`worker` have neither a bind mount nor network access after
   build.
8. **Extraction is dispatched by file extension, not by content sniffing**
   (`.pdf` → pypdf, `.txt`/`.md` → UTF-8 decode); an unknown extension raises without a
   per-file catch — per-file failure → `partial` state is explicitly v1.2 scope (noted
   in the Sync state + worker block), not this one.

### Bugs found and fixed during the build

- **`fastembed<0.5` doesn't support Python 3.13.** `pip install` in the image failed
  with "no matching distribution" — SPEC/BUILDPLAN didn't pin a version, and the
  assumed `>=0.4,<0.5` predates support for the base image (`python:3.13-slim`). Fix:
  `fastembed>=0.8,<0.9`, recorded in BUILDPLAN.md.
- **SQLAlchemy doesn't order INSERTs across `Content`/`Chunk` from a column-level
  `ForeignKey()` alone.** Without a `relationship()` between the models, the unit of
  work doesn't know `chunks` must come after `contents` — the first real sync failed on
  `chunks_content_hash_fkey` because the `chunks` insert went out before the `contents`
  insert in the same flush. Same class of bug as the FK-ordering issue in the
  Directories block, just in the opposite direction (there DELETE, here INSERT). Fix:
  an explicit `db.flush()` right after `db.add(Content(...))`, before adding any
  `Chunk` rows.
- **The existing `test_sync_state.py` cleanup broke on an FK the moment the worker
  started actually writing to `documents`.** Previously (Sync state + worker block) the
  worker never touched `documents`, so `_cleanup` didn't need to delete it before
  `directories`; now that ingest actually writes rows, `documents.directory_id`
  (no `ON DELETE CASCADE`, v0.1-skeleton decision #6) correctly refuses to let the
  directory be deleted while the reference exists. Fix: `_cleanup` now deletes
  `Document` rows for the directory first, then the directory itself — same fix applied
  to the new `test_dedup.py`'s cleanup. `contents`/`chunks` are deliberately left alone
  after cleanup — content-addressed, safely shared across tests, not test-scoped
  scratch data.

### Verification

`docker compose up --build api worker` (new `pypdf`/`langchain-text-splitters`/
`fastembed` packages, fastembed model baked into the image), then
`docker compose exec -T api pytest -q` →
**33 passed** (30 existing + 3 new in `test_dedup.py`: a fresh sync of
`alice/contracts/` actually extracts the PDF (`mime=application/pdf`, `text_len>0`), a
second sync of the same unchanged directory returns exactly
`{scanned:3, unchanged:3, downloaded:0, indexed:0, deduped:0}`, `alice/duplicates/`
(byte-identical `msa_copy.md`) after syncing `alice/contracts/` returns
`deduped:1, indexed:0` and shares the same `content_hash` as `msa.md` with no duplicate
write to `chunks`). Also confirmed manually via `psql`: `contents` after both syncs has
exactly 3 distinct `content_hash` values (not 4), `policy.pdf` has
`mime=application/pdf, text_len=41, chunk_count=1`.

---

## v1.0-core / Chat + RAG — 2026-08-16

### Context

`documents`/`chunks`/`contents` and their deduplication were already done (Ingest +
dedup block), as was removal (Removal block) — meaning retrieval now has something to
work against. What was left for this block: tenant-scoped vector search with an
`is_live_clause()` filter, retrieval with a similarity threshold, prompt assembly with
numbered sources, the LLM call (OpenRouter or an EchoLLM fallback), and one implicit
`Chat`/`ChatMessage` per tenant persisted through the ORM. All of this is the v1.0
baseline; multi-chat sessions and conversation memory are v1.3+.

### Decisions

1. **`POST /chat/messages` as an implicit single-chat endpoint per tenant.** Create or
   load the first `Chat` row (by `created_at`), write a `user` `ChatMessage` with the
   message. No `chat_id` in the path here — that arrives in v1.3 ("the existing v1.0
   chat endpoint, now scoped to a concrete `chat_id` instead of an implicit single
   conversation"). This assumption is the only one that makes the v1.3 description make
   sense (without an implicit chat in v1.0, v1.3 would be a retrofit instead of
   wiring). No `GET` history endpoint here — that's v1.3.

2. **`LLMClient` Protocol with two drivers: `OpenRouterLLM` and `EchoLLM`.**
   `OpenRouterLLM` is used when `settings.openrouter_api_key` isn't empty (`Bearer`
   auth, model = `openai/gpt-4o-mini`, a simple `httpx.post` to
   `https://openrouter.ai/api/v1/chat/completions`). `EchoLLM` is the default when no
   key is set — it mechanically assembles an answer from the retrieved sources with no
   network call. `get_llm_client()` is a lazily-cached singleton factory, same pattern
   as `get_embedder()`.

3. **`get_llm_client` as a FastAPI dependency, not a bare function call.** This lets a
   test override it with `app.dependency_overrides[get_llm_client] = lambda: EchoLLM()`
   and get a deterministic, free response regardless of what's in the container's
   `.env`. The promise in BUILDPLAN's risk table ("pytest never spends credit") requires
   not depending on whatever `OPENROUTER_API_KEY` happens to be set to.

4. **`VectorStore` Protocol with a `PgVectorStore` implementation.** Cosine-distance
   search over `Chunk` rows where
   `content_hash IN (SELECT content_hash FROM documents WHERE is_live_clause())`. A
   second, independent use of `is_live_clause()` (the first was layer-3 dedup in the
   Ingest block) — a removed document never comes back as a citation even if the
   `chunks` row still physically exists. No `user_id` filter anywhere — isolation comes
   from `search_path`, the same as the rest of the system's design.

5. **Similarity threshold set to 0.55, measured, not assumed.** BUILDPLAN §6 gave "e.g.
   0.5" as an example, but measurements against `bge-small-en-v1.5` on the fixture
   corpus show: relevant hits 0.66–0.78, unrelated-but-same-domain ~0.47–0.50 (e.g.
   Bob's onboarding guide against Alice's question about a license fee), fully
   unrelated ~0.30–0.37. A threshold of 0.55 separates the first two cases without
   discarding real hits — deliberately measured.

6. **Top-k stays at 5, threshold checked in code before the LLM call, with no
   "no-context" ability handed to the model.** If the top-1 similarity is below the
   threshold, or there are no hits, `retrieve()` returns an empty list — what's sent to
   the LLM is a system prompt that then says "I don't have anything about that" instead
   of relying on the model to notice the context is empty. BUILDPLAN §6 says this
   explicitly — a numeric threshold checked before the call is cheaper and more
   reliable than trusting the model to recognize an empty context.

7. **Retrieval maps `content_hash` → filenames with one batch query.** Several chunks
   can share a `content_hash` (one file, many chunks), and several documents can share a
   `content_hash` (the same content at multiple paths — the last dedup layer). A
   citation honestly lists every live `documents` row for that `content_hash`.

8. **New test file `test_chat.py`.** Two tests, both forced onto `EchoLLM` via
   `app.dependency_overrides`: (1) Alice syncs `alice/contracts/`, asks "What is the
   quarterly license fee for WidgetFlow?" — the answer should cite `"msa.md"`;
   (2) Bob syncs `bob/contracts/` (different content), asks the same question — the
   answer should have `citations == []` and a "don't have" message, proving retrieval
   never crosses the tenant boundary even for a question phrased specifically to target
   another tenant's document (the adversarial case from BUILDPLAN §3).

### Verification

`docker compose up --build api worker` (new `httpx` package, no embedding change), then
`docker compose exec -T api pytest -q` → **41 passed** (39 existing + 2 new in
`test_chat.py`). Also confirmed manually: the `EchoLLM` fallback with zero API keys
demonstrates the full path (sync → retrieve → cite), just with a mechanical answer
instead of a generated one.

---

## v1.0-core / Removal — 2026-08-16

### Context

`documents` rows now exist and get populated (Ingest + dedup block), which means
cascading operations — deleting a document, deleting a whole directory — become
meaningful. What was left for this block: `DELETE /documents/{id}` with refcount
release, `DELETE /directories/{id}` as a cascade (soft-delete all its documents →
refcount → hard-delete the directory), and a race guard in the worker against a sync
that's in flight when the directory is deleted mid-run.

### Decisions

1. **`DELETE /documents/{id}` uses `is_live_clause()` from `refcount.py`, with no
   Python re-check after loading.** Same helper "Ingest + dedup" already imported for
   the layer-3 dedup check — a document that's missing, cross-tenant (invisible through
   `search_path`), or already removed all produce the same 404, without repeating the
   predicate in a second place. Soft delete (`removed_at = now()`), then
   `release_content_if_orphaned()` if it had a `content_hash`. 204 No Content on
   success.

2. **`DELETE /directories/{id}` hard-deletes every `documents` row for that directory,
   not just marking `removed_at`.** `documents.directory_id` is `NOT NULL` with no
   `ON DELETE CASCADE` — "no `documents` row still points at that directory" (§4)
   literally means those rows no longer exist. Algorithm: (1) read the set of
   `content_hash` values from currently live `documents` rows (only those can become
   orphaned here), (2) hard-delete every `documents` row for the directory, (3) run
   refcount release for just that set, (4) only then delete the `directories` row. No
   predicate duplication — same `is_live_clause()` helper as `DELETE /documents` and
   the Ingest block.

3. **Race guard: the worker re-checks `EXISTS(Directory)` at the start of every loop
   iteration.** The per-file loop
   (`for obj in objects: ... ingest_object ... db.commit() ... set_search_path ...`)
   now checks `directory_id` (a raw UUID argument, not the `directory` ORM object —
   that one expires after `db.commit()` with `expire_on_commit=True`) before every
   `ingest_object` call. `break`, not `continue` — once the directory is gone, it stays
   gone for the rest of the run; no point downloading/extracting/embedding further.
   Checked in the same (pre-commit) transaction as the file write and the post-commit
   `set_search_path` re-setup, so the logic holds correctly across every
   `db.commit()` boundary.

4. **"Removal survives a re-sync" is already correct without touching
   `ingest/index.py`.** The layer-1 check (an existing `(directory_id, source_key)` row
   whose `etag`/`size` match) returns before it ever touches `removed_at`, which means
   a soft-deleted document stays put — new syncs don't bring it back. This was a
   dependency ordering win, not new code. Added a regression test
   (`test_removed_document_does_not_reappear_on_unchanged_resync`) to make the claim
   falsifiable.

5. **The `GET` document list per directory stays out of this block.** BUILDPLAN's §7
   table explicitly places it in the "React UI" block — tests read `documents` rows
   directly through `tenant_session`, same pattern as `test_dedup.py`/
   `test_sync_state.py`, which proves the API was never actually required for
   functionality, only for the frontend.

6. **New test file `test_removal.py`, same precedent as `test_dedup.py`** — six tests:
   refcount release only when no live references remain, a missing document → 404,
   cross-tenant access → 404 not 403, a removed document stays removed after a re-sync,
   cascading directory delete with refcount (content shared between two directories is
   released only once both are gone), and a deterministic race-guard test (monkeypatch
   `ingest_object` to commit after the first file, then issue a real
   `DELETE /directories` call from the test's HTTP client, then run `run_sync` in the
   same process as the worker, confirming only 1 of 3 scanned files was processed).

### Bugs found and fixed during the build

- **`job_id` could be uninitialized in
  `test_directory_deleted_mid_sync_worker_skips_remaining_files`'s cleanup** — the test
  inserts a `sync_jobs` row directly through `db_conn`, and needed `job_id` initialized
  to `None` at the top of the try block so cleanup doesn't crash if the INSERT itself
  failed. No actual code bug, just test robustness.

### Verification

`docker compose up --build api worker` (no new external dependencies, pure
refactoring), then `docker compose exec -T api pytest -q` → **39 passed** (33 existing +
6 new in `test_removal.py`: deleting a document releases content only when no other
live references remain, a missing/foreign document returns 404, a removed document
doesn't reappear on resync, cascading directory delete, race-guard worker stop between
the two directories).

---

## v1.0-core / React UI — 2026-08-16

### Context

All prior blocks were done, but `apps/web` was still an unmodified Vite template with
no real logic — no login form, no datasource list, no sync or chat. What was left for
this block was building the one screen that demonstrates the whole flow: datasource →
directories → documents + sync, chat with citations. The backend API is complete; the
frontend just needs to call it.

### Decisions

1. **New endpoint `GET /directories/{directory_id}/documents` added in this block**,
   the only backend work. BUILDPLAN §7 explicitly places it here since it's part of the
   UI that uses it (the Remove button, per-file `state` display). Filters only on
   `removed_at IS NULL`, not the full `is_live_clause()` — this is a display route, not
   a dedup mechanism, and needs to show `failed` and `deleted_at_source` rows once v1.2
   exists (the full live predicate requiring `state = 'indexed'` would hide them).
   Covered by 4 new tests in `test_documents.py`.

2. **`apps/web/src/api.ts` as a centralized fetch wrapper with global 401 handling.**
   Any 401 response (excluding the initial `/auth/me` probe) triggers a
   `setUnauthorizedHandler()` callback, which clears auth state and returns the user to
   login — a session that expired without an explicit logout. Every route maps onto the
   same shape as the backend's Pydantic `*Out` models.

3. **Three new components under `src/components/`:**
   - `Datasources.tsx`: a chip list, "Connect" form pre-filled for LocalStack
     (`endpoint_url=http://localstack:4566`, other dev defaults), auto-selects the
     first one created
   - `Directories.tsx`: browse (prefix picked from a list), free-typed prefix input,
     register, per-directory Sync with live polling (`queued`→`running`→terminal), an
     expandable document list with Remove, directory delete
   - `Chat.tsx`: a local message list (no HTTP `GET` history — v1.0's implicit chat),
     Send, numbered `[1][2][3]` citations rendered under the answer

4. **`App.tsx` as the auth gate:** `me()` on mount, a login form if there's no user,
   otherwise a header with the display name + Logout, a two-column flex layout with
   Datasources on the left (flex-3) and Chat on the right (flex-2). Logout clears the
   cookie, `me()` returns `401`, the global handler clears state.

5. **Minimal CSS, no framework:** plain flexbox, status badges, errors shown inline
   next to the action that failed, no toasts, no CSS framework — "usable, not
   beautiful" per the SPEC.

6. **One bug caught and fixed in the Directories polling logic:** `syncSummary` showed
   "nothing new to sync" even when `deduped > 0` and `indexed === 0`, which would
   present a successful dedup as if nothing had happened. Fix: the check now treats
   `indexed === 0 && deduped === 0` as "nothing new," otherwise it reports
   "finished — indexed X, deduped Y, unchanged Z."

### Verification

`docker compose down -v && docker compose up --build` (clean environment, no test
contamination), then `docker compose exec -T api pytest -q` → **45 passed** (every
test, including 4 new in `test_documents.py`). Manually verified through the browser
(the §9 demo script — the full flow, not just individual components): login as alice →
connect → browse `alice/` → register `contracts/` → Sync (live progress, finishes with
"indexed 3") → Sync again ("unchanged 3") → register `duplicates/` → Sync ("indexed 1"
because of dedup — the dedup-counting bug fixed above) → expand the document list, see
"msa.md", "nda.txt", "policy.pdf" all "indexed" → ask a chat question → answer with
`[1][2][3]` citations → logout → login as bob → same question → "I don't have anything
about that" (zero citations, isolation confirmed) → back as alice → Remove "msa.md" →
same question → answer now without an "msa.md" citation (content released) → Sync
again → "msa.md" doesn't come back — soft delete survives a re-sync.

---

## What's next

`v1.1` (least-privilege DB role per tenant) and `v1.2` (sync resilience — heartbeat,
reaper, `deleted_at_source`, partial failure) were planned as the next two blocks but
weren't reached in this timebox. `v1.0-core` above is the complete mandatory system;
the reasoning for what comes after it, and why, is in `docs/WRITEUP.md`.
