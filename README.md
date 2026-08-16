# Nimbus - Document Intelligence Platform

Connect a storage provider, sync a directory into a per-user knowledge base, and chat
with an LLM grounded in your own documents.

## Stack

FastAPI (Python) for the API and sync worker, React + Vite for the UI, Postgres +
pgvector for metadata and vectors, LocalStack for a local S3, OpenRouter for LLM calls.
Everything runs from one `docker compose up`. 
## Quick start

Requires Docker and Docker Compose. Nothing else needs to be installed locally.

```bash
git clone <this-repo>
cd nimbus-take-home
cp .env.example .env
docker compose up --build
```

Wait for all services to report healthy, then open **http://localhost:3000**.

Two demo users are seeded automatically:

| Email | Password |
|---|---|
| `alice@nimbus.dev` | `nimbus-demo` |
| `bob@nimbus.dev` | `nimbus-demo` |

Each has their own isolated tenant schema and their own S3 prefix already populated
with sample documents (`alice/contracts/`, `alice/duplicates/`, `bob/contracts/`), so
you can log in and start syncing right away without connecting anything by hand.

## Environment variables

The only variable you need to touch is in `.env`:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENROUTER_API_KEY` | No | *(empty)* | Enables real LLM answers via [OpenRouter](https://openrouter.ai). Without it, chat still runs the full retrieval pipeline but returns a deterministic answer assembled from the retrieved chunks instead of an LLM completion, the end-to-end path works either way. |

Everything else (Postgres DSN, LocalStack endpoint, S3 credentials, bucket name) is
wired between containers in `docker-compose.yml` and needs no configuration for local
use. Two more dev-only secrets (`jwt_secret_key`, `fernet_key`) have fixed local
defaults baked into `services/api/app/core/config.py`; override them via `.env` only if
you're running this somewhere that isn't your own machine.

`.env` is git-ignored, never commit a real key. `.env.example` documents the shape.

## What's running

| Service | Role | Exposed at |
|---|---|---|
| `web` | nginx serving the React build, proxies `/api/*` to `api` | http://localhost:3000 |
| `api` | FastAPI,  auth, datasources, directories, sync, chat | http://localhost:8000 |
| `worker` | Same image as `api`, different entrypoint, claims sync jobs and does the actual ingest work | internal only |
| `postgres` | Postgres 16 + pgvector,  control-plane tables and per-tenant schemas | internal only |
| `localstack` | S3-compatible emulator standing in for real cloud storage | http://localhost:4566 |
| `seed` | One-shot: runs migrations, provisions the two demo tenants, uploads fixture documents | exits after bootstrap |

`api` and `worker` have no bind mount, application code is baked into the image at
build time. If you change backend code, rebuild before testing:

```bash
docker compose up --build api worker
```

## Common commands

```bash
docker compose up --build          # start everything (make up)
docker compose exec -T api pytest -q   # run the test suite (make test)
docker compose exec api alembic upgrade head  # apply migrations (make migrate)
docker compose down -v && docker compose up --build  # wipe volumes and start clean (make reset)
```

A `Makefile` wraps the first four as `make up` / `make test` / `make migrate` / `make reset`.

## Trying it out

1. Log in as `alice@nimbus.dev`.
2. Connect a datasource, the form is pre-filled for the LocalStack bucket, just save it.
3. Browse the bucket, pick a prefix (e.g. `contracts/`), register it as a directory.
4. Click **Sync**, watch it go `queued → running → succeeded` with a summary
   (`indexed: N`).
5. Click **Sync** again, `unchanged: N, indexed: 0`: the second sync costs one `LIST`
   call, nothing is re-downloaded or re-embedded.
6. Register `duplicates/` (same bytes as a file already indexed, different name) and
   sync it,  `deduped: 1, indexed: 0`.
7. Ask a question in the chat panel, the answer cites the source file(s) it used.
8. Log out, log in as `bob@nimbus.dev`, ask the same question, Bob has no access to
   Alice's documents, so the answer says there's nothing about that in his documents.
9. Back as Alice, remove a cited document from the document list, ask again, the
   answer is no longer grounded in it. Sync once more: the removed file does **not**
   come back, even though it's still untouched at the source.

## Example chat questions

Once `alice/contracts/` (or `bob/contracts/`) is synced, these ask about facts that
only exist in the fixture documents, so a grounded, non-echoed answer (with a
citation) confirms the OpenRouter call actually worked end to end, not just that the
retrieval pipeline ran:

| User | Question | Answer should mention | Source |
|---|---|---|---|
| alice | `What is the quarterly license fee in the MSA?` | `$18,500` | `msa.md` |
| alice | `How much notice is required to not renew the MSA?` | `90 days` | `msa.md` |
| alice | `How long does the NDA's evaluation period last?` | `six (6) months` | `nda.txt` |
| bob | `When does payroll run?` | `15th and last day of each month` | `onboarding.md` |
| bob | `How many PTO days do full-time employees accrue per year?` | `15 days` | `handbook.txt` |

Ask the same question as the other user (or before syncing) and the answer should say
there's nothing about that in their documents, that's the tenant-isolation /
no-context path, not a bug.

Keep questions in English: `bge-small-en-v1.5` (the embedder) is an English-only
model, a question phrased in another language can fall below the similarity
threshold in `retrieve()` even when the answer is right there in the (English)
document, and the LLM never sees a source to cite.

## Tests

```bash
docker compose exec -T api pytest -q
```

Tests target the invariants that matter most: cross-tenant access always returns 404
(never 403, which would leak existence), dedup only skips work within a single user,
and a removed document never resurfaces on re-sync. `pytest` never spends OpenRouter
credit, the LLM client is overridden with a deterministic stub in tests regardless of
what's in `.env`.

## Deviations from the suggested stack

| Instead of | Used | Why |
|---|---|---|
| Pinecone | pgvector, same Postgres | Clean-clone-in-one-command is a hard requirement; one fewer external key. Vectors also live inside the tenant schema, so physical isolation covers them for free. |
| SQS / Celery / Redis | Postgres queue (`FOR UPDATE SKIP LOCKED`) | Enqueuing a sync job and recording that it was requested need to be one atomic write, not two systems that can disagree. |
| LangChain / LangGraph | A ~40-line hand-written retrieve → prompt → generate loop | The tenant boundary needs to be visible in code, not configured inside a chain, for something this linear. |
| Next.js | Vite + React SPA behind nginx | No SSR/SEO need — one authenticated screen over a JSON API. nginx also proxies `/api`, so there's no CORS or cross-origin cookie handling to get wrong. |
| Clerk / Ory Kratos | Two seeded users, JWT in an httpOnly cookie | The brief explicitly allows two hardcoded users; neither IdP would change how isolation is proven. |
| Hosted embeddings | `fastembed` (`bge-small-en-v1.5`), baked into the image | OpenRouter has no embeddings endpoint. A local model means indexing works with zero API keys. |

Physical isolation is the one place worth calling out on its own: each user gets a
separate Postgres schema (`tenant_<id>`), selected via `SET LOCAL search_path` from a
verified token, and no tenant table has a `user_id` column anywhere, there's no
column to filter on incorrectly, because there's no shared table to filter.