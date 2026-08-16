---
name: verify
description: pokreni punu verifikaciju sistema
disable-model-invocation: true
---
Run in order and show the output of each:
1. docker compose up -d --build, then wait for healthchecks
2. docker compose exec -T api pytest -q
3. curl the health endpoint
Report pass/fail per step. If anything fails, diagnose the root cause before
suggesting a fix. Do not suppress errors.
