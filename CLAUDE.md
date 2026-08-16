# Project
Document intelligence platform. SPEC.md is the contract, BUILDPLAN.md is the
execution order and current status.

# Commands
- run: docker compose up --build
- test: docker compose exec -T api pytest -q
- migrate: docker compose exec -T api alembic upgrade head
- reset: docker compose down -v && docker compose up --build

# Non-negotiable invariants (breaking these is a data-safety bug)
- get_current_user is the ONLY source of user identity. No route accepts
  user_id as a path, query or body parameter.
- Tenant models are declared WITHOUT schema=. The session dependency sets
  search_path from the verified token. One model set serves all tenants.
- A document is LIVE iff removed_at IS NULL AND state = 'indexed'. This exact
  predicate is used in three places: refcount on delete, layer-3 dedup check,
  and the known_keys diff in sync. Never inline a different version of it.
- chunks and contents rows for a content_hash are deleted together, always.
- Never commit .env. Never print the OpenRouter key.

# Code style
- No AI-slop comments. Comment only where a senior engineer would: a
  non-obvious invariant, a workaround, a "why", never a restatement of
  the code. Keep it short.
- Function/docstring descriptions: short and precise, like a senior
  engineer would write them — no filler, no restating the signature.

# Workflow
- Read SPEC.md and BUILDPLAN.md before starting any block.
- Split each tag into meaningful, independent chunks of work and go
  through them in order, one at a time.
- A chunk is not done until `test` passes. Show the output as proof.
- After each chunk: tick the checkbox in BUILDPLAN.md, update Trenutni
  status, then give a short plain-language summary of what was done.
  Do not commit — leave that action to the user.
- Commit message, when the user asks for one: a single short title
  line, nothing else (no body).
- At the end of a tag: create an annotated git tag whose message is the
  decision-log entry for that tag.
- If SPEC.md is ambiguous, state the assumption in the code comment and in
  BUILDPLAN.md. Do not silently guess.