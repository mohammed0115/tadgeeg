# Phase 1 — App Registry & Settings Reconciliation

**Note:** in the original plan this was numbered "Phase 2" (Phase 1 = inspection). The deliverable file is named `PHASE_1_APP_REGISTRY_FIX.md` to match the user's spec.

## What was wrong

| Issue | Status before | Status after |
|---|---|---|
| Two settings files (`settings.py`, `settings_canonical.py`) with different `LOCAL_APPS` lists | Drift hazard — `settings.py` listed 20 apps; `settings_canonical.py` listed 23. | `settings.py` is now a 22-line delegation shim that re-exports from `settings_canonical.py`. Drift impossible. |
| Active import path is the `settings/` **package** → `settings/base.py` → `settings_canonical.py`. The file `settings.py` was dead code, but tooling and direct imports could still hit it. | Dead but confusing. | Kept (so old imports work) but routes to canonical. |
| `apps.platform_management` and `apps.vendor_dashboard` referenced in `urls.py` but never in `INSTALLED_APPS` | Routes resolved at request time, but the apps' AppConfigs never loaded → no admin, no signals, no migrations would ever run for them. | Both added to `LOCAL_APPS` in `settings_canonical.py`. |
| `ALLOWED_HOSTS` unconditionally appended `testserver`, `localhost`, `127.0.0.1` even in production | Host-header injection possible in production. | Now only added when `DEBUG=True` or `DJANGO_RUNNING_TESTS=1` or pytest is on `sys.argv[0]`. |

## Files changed

| File | Change | Lines |
|---|---|---|
| `finai_backend/settings_canonical.py` | Added `apps.platform_management` + `apps.vendor_dashboard` to `LOCAL_APPS`. Wrapped `testserver` ALLOWED_HOSTS extension in a DEBUG / pytest guard. | +9, -3 |
| `finai_backend/settings.py` | Replaced 523-line duplicated config with a delegation shim that imports from `settings_canonical`. Original content preserved in git history. | +22, -524 |

## What was NOT changed

- No URL routes were disabled. The two apps that were missing are now properly installed, so disabling their routes is unnecessary.
- `manage.py`, `wsgi.py`, `asgi.py`, `celery.py` continue to use `DJANGO_SETTINGS_MODULE=finai_backend.settings`. The package wins over the file (verified), so behavior is unchanged at runtime.
- `assistant`, `webhooks`, `data_export` were already in `settings_canonical.py` (and therefore active). The Phase 1 audit doc had this slightly wrong; the §15 update corrected it.

## Verification

| Check | Result |
|---|---|
| `python manage.py check` | ✅ 0 issues |
| `apps.platform_management` in `INSTALLED_APPS` | ✅ True |
| `apps.vendor_dashboard` in `INSTALLED_APPS` | ✅ True |
| `testserver` leak with `DEBUG=False` and explicit `ALLOWED_HOSTS=example.com,api.example.com` | ✅ NOT in `ALLOWED_HOSTS` |
| Settings consistent regardless of import path | ✅ — `settings.py` re-exports from `settings_canonical.py` |

## Migrations

`makemigrations --check --dry-run` reports the same pre-existing migration drift on `apps.rule_engine` (3 model alterations) that existed before Phase 1. Not introduced by this change. Deferred to Phase 6.

## Risks / things to watch

- `apps.platform_management` and `apps.vendor_dashboard` did not have models or migrations. Loading their `AppConfig.ready()` for the first time may register signals that were silently disabled before. If any signal handler does mutating work on app-load, watch the next migrate run.
- Old `.env` files that hardcoded `DJANGO_SETTINGS_MODULE=finai_backend.settings` continue to work.
