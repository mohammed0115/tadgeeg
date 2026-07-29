# Tadgeeg — Deployment / Migration Analysis & Fixes

> Analysis of "migrations issues in Docker" + fixes for problems that would occur when deployed to the server (production = **MySQL** via `entrypoint.sh` running `migrate` on container start).
> **Date:** 2026-07-29.

---

## 1. The real problem (found + fixed) — missing tables on a fresh deploy

**Symptom:** on a fresh Docker/MySQL deploy, `migrate` runs but some features 500 with "table doesn't exist."

**Root cause:** five apps are **imported by installed apps** but were **absent from `INSTALLED_APPS`**, so `migrate` never created their tables:

| App | Imported by (installed) | Models |
|---|---|---|
| `storage_management` | platform_admin, platform_management | 7 |
| `audit_engine` | rule_engine (legacy adapter), vendor_dashboard | 4 |
| `file_management` | vendor_dashboard | 3 |
| `leads` | platform_admin, platform_management | 2 |
| `cms` | platform_admin, platform_management | 15 |

Verified: the runtime DB had **0 of these tables** — the features were silently broken in dev too (dev only "worked" because those code paths weren't exercised).

**Fix:**
1. Registered the five apps in `INSTALLED_APPS` (`settings_canonical.py`). They ship complete migrations → `makemigrations --check` = *No changes*; a fresh from-scratch `migrate` applies all five `0001_initial` cleanly (EXIT 0).
2. Changed the deploy `migrate` to **`--fake-initial`** (`docker/entrypoint.sh` + `deployment/live_deployment.sh`). This is safe for both cases:
   - fresh DB → tables created normally;
   - a legacy DB that already has those tables → the initial migration is marked applied instead of erroring with "table already exists".

**Validation:** core regression **862 passed**; importer + new-app suites **342 passed**; fresh-from-scratch migrate EXIT 0; runtime DB brought fully up to date.

## 2. Runtime DB was 17 migrations behind
The dev `db_runtime.sqlite3` was stuck at ~migration 0023 (pre-9C). Applied all pending migrations (0024→0041 audit, +auth/activity_logs). This is why running the app locally failed on the newer pages. Production is unaffected (fresh `migrate` on deploy), but noted.

## 3. `create_demo_user.py` was broken (fixed)
It imported Django's default `contrib.auth.models.User` and used a `username` field — but Tadgeeg has a **custom user model** keyed on `email` with no `username`, and a wrong hard-coded path. Rewritten to use the real model, create an org + **activate a subscription** (else `SubscriptionRequiredMiddleware` blocks the user), and seed both an auditor and a client demo login.

## 4. Verified healthy (no change needed)
- **Migration graph** is sound from an empty DB (no raw SQL, no `RunPython`, no index/constraint names > 64 chars → MySQL-safe).
- **Prod config hardened:** `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` are env-driven; a fatal check rejects the default `SECRET_KEY` in non-local; `DEBUG` defaults False.
- **`.env`** is gitignored and not tracked (no secret leak).
- **Entrypoint** waits for the DB, `set -e`, runs `collectstatic`; deploy scripts validate the `MySQLdb` driver.

## 5. Known, non-blocking (documented — do NOT "fix" blindly)
**Conditional unique constraints are silently unenforced on MySQL.** Eight audit models use `UniqueConstraint(fields=["organization","reference"], condition=Q(reference__gt=""))`. MySQL has `supports_partial_indexes = False`, so Django **skips** these constraints (returns `None`) — no migration error, but per-org `reference` uniqueness is not enforced at the DB level on MySQL.
- **Impact:** a concurrency-only risk of duplicate `reference` values (references are generated server-side sequentially).
- **Why not convert to a plain `UniqueConstraint`:** if a production MySQL has already accumulated duplicate references (because the constraint never enforced), adding a plain unique index would **fail the deploy**. The correct fix is **application-level atomic reference generation** (e.g., `select_for_update` on a per-org counter), a deliberate change — not a blind schema swap.

## 6. Deploy checklist (for the server)
1. Set env: `DB_BACKEND=mysql`, `DB_NAME/DB_USER/DB_PASSWORD/DB_HOST`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DEBUG=False`.
2. Ensure `MYSQL_PASSWORD == DB_PASSWORD` (documented trap in the deploy scripts).
3. `entrypoint.sh` now runs `migrate --fake-initial` + `collectstatic` automatically.
4. First deploy on an existing legacy DB: `--fake-initial` handles pre-existing tables; verify with `showmigrations` afterward.
