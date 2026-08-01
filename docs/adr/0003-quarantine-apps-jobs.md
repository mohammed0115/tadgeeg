# ADR 0003 — Quarantine `apps.jobs` instead of registering it

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 0-A (Admin API Surface Activation & Guardrails)

## Context

`apps/jobs/` is a complete recruitment module — models, views, selectors,
services, serializers, admin, one migration, and two finished UI templates.
It is **not** listed in `LOCAL_APPS` (`finai_backend/settings_canonical.py`).

`apps/jobs/models.py` declares no explicit `app_label`, so importing it from an
unregistered app raises **at import time**, not at query time:

```
RuntimeError: Model class apps.jobs.models.JobPost doesn't declare an explicit
app_label and isn't in an application in INSTALLED_APPS.
```

Five installed modules imported it:

| # | Site | Import kind |
|---|---|---|
| 1 | `apps/platform_admin/api_views.py` | module level (`JobPost`, queried in `PlatformDashboardStatsView`) |
| 2 | `apps/platform_admin/api_urls.py` | module level (`jobs_views`) |
| 3 | `apps/platform_management/api_urls.py` | module level (`jobs_views`) |
| 4 | `apps/cms/views.py` | deferred, inside `CMSDashboardStatsView.get` |
| 5 | `apps/system_monitoring/api_views.py` | **transitive**, via site 1 |

Because `include()` imports a URLConf while the URL tree is being built, any of
sites 2, 3 or 5 in the routed tree stops the **process** from booting — not one
endpoint. This blocked Phase 0-A's actual goal (mounting the admin API at
`/api/platform-admin/`, which had left all 61 console API call sites returning
404).

This is the second occurrence of this bug class here. The first —
`storage_management`, `audit_engine`, `file_management`, `leads`, `cms` — is
recorded in the `TADGEEG-DEPLOY-FIX` comment in `settings_canonical.py` and
reached production as "table doesn't exist" 500s on fresh deploys.

## Decision

**Quarantine, do not register.**

1. Remove all imports of `apps.jobs` from installed apps. Installed code asks
   `core.feature_flags.jobs_enabled()` — which queries the app registry, so it
   cannot drift from reality.
2. **Preserve API response shape.** `active_jobs` and `total_applications` stay
   in the stats payloads. Values are `None`, not `0`: zero is a factual claim
   ("no open jobs"); the truth is "unknown, feature off". A companion
   `jobs_feature_enabled` boolean lets clients tell the two apart.
3. **Announce the disabled state.** Dashboard tiles render "Feature not
   enabled" rather than a silent `0`; the sidebar entry is removed; and
   `/platform-admin/jobs/` renders `feature_unavailable.html` instead of a page
   whose every request fails.
4. **Retain the code.** `apps/jobs/` and its migration are untouched. So are
   `templates/platform_admin/jobs.html` and `templates/cms_admin/jobs.html`.
5. **Guard against recurrence** with `tests/test_app_registry_integrity.py`,
   which parses the tree with `ast` (never `importlib` — importing the
   offending module is what explodes) and fails if any installed app imports
   from an uninstalled one.

## Why not register it (the rejected option)

Adding `apps.jobs` to `INSTALLED_APPS` would:

- Make `apps/jobs/migrations/0001_initial.py` — never applied on any
  environment — a pending migration in the deploy path. Phase 0-A is
  explicitly a no-migration change.
- Add `contenttypes` and auth permission rows.
- Expose seven admin endpoints and two public endpoints that have had **no**
  permission review. In particular `apps/jobs/views.py` contains the same
  privilege-escalation defect fixed elsewhere in this phase:
  ```python
  return user.is_staff or getattr(user, 'role', None) == 'admin'
  ```
  `User.Role.ADMIN` is granted to every self-service registrant, so that check
  is equivalent to `IsAuthenticated`.

## Re-enabling — required, in order

1. Fix `apps/jobs/views.py` `_is_admin` to use `core.permissions.is_platform_user`.
2. Add `"apps.jobs"` to `LOCAL_APPS`.
3. Run `migrate` **on MySQL**, not only SQLite, and confirm the tables exist.
4. Permission-review all nine routes; add tests that execute the view body as
   staff (200) and assert 403 for an authenticated non-staff user.
5. Restore the seven `jobs/*` paths in `apps/platform_management/api_urls.py`
   and `apps/platform_admin/api_urls.py`.
6. Restore the `jobs` item in `navigation/platform_menu.py`.
7. Delete the `jobs_enabled()` branch in `apps/platform_admin/views.jobs_manager`.

No step may be skipped: `jobs_enabled()` flips on at step 2, so the UI will
start calling endpoints that step 5 has not yet restored.

## Consequences

- The recruitment feature is unavailable and says so plainly.
- Process startup no longer depends on an unregistered app.
- `active_jobs` is `None` rather than `0` — clients reading it as a number must
  handle null. The `jobs_feature_enabled` flag exists for exactly this.
- The whole bug class is now caught by a test rather than by a production
  incident.

## Open product decision (not settled here)

Re-enable, delete, or keep frozen? The UI is built and the migration is ready,
so the cost of re-enabling is a permission review, not development. Deleting
would discard finished work. Deliberately left open.
