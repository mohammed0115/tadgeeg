# Phase 2 — Docker / Redis / Celery

> File numbering follows the user's spec (Phase 2 here = "Docker + Celery + Redis"). Sequencing in `git log` is independent.

## What was wrong

| Issue | Impact |
|---|---|
| `docker-compose.yml` had only `db` (mysql), `web` (gunicorn), `nginx`. **No redis, no celery_worker, no celery_beat.** | Every `.delay()` / `apply_async` call (audit pipeline triggers, notification fan-out, weekly KPI report, nightly anomaly scan, prune-audit-logs) tried to enqueue to `redis://localhost:6379/0` from inside the `web` container — there was no redis there. Symptom: upload "succeeded" but no audit run ever appeared. |
| `CELERY_BEAT_SCHEDULE` defined 4 scheduled jobs (nightly anomaly scan, weekly KPI report, weekly summary, prune audit logs) but no beat container existed. | Scheduled tasks never fired. |
| `gunicorn --workers 3` with no `--max-requests` / `--max-requests-jitter`. | Memory creep over time without worker recycling. |

## What changed

### `docker-compose.yml`

- **Added `redis` service** (redis:7-alpine, AOF persistence via `--save 60 1`, healthcheck `redis-cli ping`, named volume `redis_data`).
- **Added `celery_worker` service** — same image as `web`, runs `celery -A finai_backend worker --concurrency=2 --max-tasks-per-child=200 --hostname=worker@%h`. Concurrency and max-tasks-per-child are env-tunable.
- **Added `celery_beat` service** — same image, runs `celery -A finai_backend beat`. Single instance only; running multiple beat containers duplicates every scheduled task.
- All three new services depend on `redis` healthy and `db` healthy.
- `web`, `celery_worker`, `celery_beat` all set `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` env vars to `redis://redis:6379/0` (the docker service name) by default. Operators can override via `.env`.
- `web` gunicorn now has `--max-requests 1000 --max-requests-jitter 100` (env-tunable). Workers recycle on memory pressure.

### Settings (no edit required)

`finai_backend/settings_canonical.py:CELERY_BROKER_URL` already reads `REDIS_URL` env var — the new docker-compose just supplies it correctly.

## Files changed

| File | Change |
|---|---|
| `docker-compose.yml` | +90 / -3 — added redis, celery_worker, celery_beat; gunicorn flags; `redis_data` volume |

## Verification

| Check | Result |
|---|---|
| `python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"` | ✅ parses |
| `docker compose config` | (not run — Docker not available in this dev environment) |
| Default `REDIS_URL` resolves to docker service name `redis` (not `localhost`) | ✅ |
| Beat schedule (`nightly-anomaly-scan` etc.) sourced from `finai_backend/celery.py:beat_schedule` | ✅ — uses default scheduler (PersistentScheduler), beat container reads it on startup |

## Known follow-ups (deferred)

- All three Django containers (`web`, `celery_worker`, `celery_beat`) currently invoke `entrypoint.sh`, which runs `migrate` + `collectstatic` before `exec`. Migrations are idempotent so this is correctness-safe but wasteful. A future PR should add an env flag (e.g. `SKIP_MIGRATE=1`) so workers skip startup work.
- `--max-requests` is set on gunicorn but not on the celery worker; consider `--max-tasks-per-child=200` (already added) is sufficient.
- No `django_celery_beat` (DB scheduler) added — would require a migration. Current static schedule in code is fine for now.
- HTTPS is still terminated outside the stack (or absent). nginx still listens on port 80 only. Tier-3 follow-up.

## Risks / things to watch

- First deploy after this change: redis must be reachable at `redis://redis:6379/0`. If `.env` overrides `REDIS_URL` to something else, the worker/beat may fail their healthchecks.
- Celery worker startup runs `migrate` (via shared entrypoint) — if web finishes migrate first, worker's migrate is a no-op. Three parallel `migrate` invocations against MySQL may show lock contention briefly on first deploy; acceptable.
- Scheduled tasks that previously were dead (not running) will now fire. Specifically: `prune-audit-logs` runs weekly. If the audit-log retention setting was wrong, log volume could change unexpectedly. Audit retention env vars before merge.
