# Phase 3 — Entrypoint Safety

## What was wrong

`docker/entrypoint.sh` ran two Python blocks **on every container restart** that:

1. Detected an old `audit_sessions.session_name` schema and ran:
   ```sql
   UPDATE invoice_batches SET audit_session_id = NULL ...
   DROP TABLE IF EXISTS audit_findings;
   DROP TABLE IF EXISTS audit_sessions;
   DELETE FROM django_migrations WHERE ...
   ```

2. Dropped a hardcoded list of "orphan tables" if their owning migration row was not present in `django_migrations`:
   ```sql
   DROP TABLE IF EXISTS `ledger_periods`
   DROP TABLE IF EXISTS `procurement_threeway_matches`
   DROP TABLE IF EXISTS `procurement_pr_approvals`
   DROP TABLE IF EXISTS `procurement_pr_lines`
   DROP TABLE IF EXISTS `procurement_requisitions`
   ```

Both ran as root-equivalent on production MySQL on every `docker compose up`. A regression in either guard, or a future addition to the list with a typo, equals data loss.

## What changed

### `docker/entrypoint.sh`

- Removed both DROP TABLE blocks entirely.
- Reduced to: wait-for-mysql → `migrate --noinput` → `compilemessages` → `collectstatic` → `exec "$@"`.
- Added a header comment that explains the safe-by-default contract and points operators to the manual repair script.

### `scripts/manual_schema_repair.py` (new)

- Contains the same logic that was previously in entrypoint, but moved out of automatic execution.
- Refuses to run unless **both** `--i-have-a-backup` is passed AND `DJANGO_SETTINGS_MODULE` is the default (`--allow-non-default-settings` overrides).
- Always supports `--dry-run` to preview changes without writing.
- File header is explicit: when to run, how to run, what it does, what it will not do.

## Files changed

| File | Change |
|---|---|
| `docker/entrypoint.sh` | -75 lines (removed both destructive blocks), +9 lines (header comment) |
| `scripts/manual_schema_repair.py` | NEW (165 lines) — destructive logic with safety gates |

## Verification

```bash
$ grep -nE "DROP TABLE|DELETE FROM django_migrations" docker/entrypoint.sh
(no output) ✅
```

```bash
$ python scripts/manual_schema_repair.py
Refusing to run destructive operations without --i-have-a-backup.

$ python scripts/manual_schema_repair.py --dry-run
No schema repairs needed — DB is consistent with migrations.
```

## What still requires human attention

If a deploy crashed mid-migration in the past and was previously "fixed" by entrypoint dropping tables, those drops will no longer happen automatically. **First time this matters** is the first `docker compose up` after this change on a DB that's actually in the broken state. The deploy will fail with "table already exists" or similar. The operator should:

1. Take a `mysqldump`.
2. Run `python scripts/manual_schema_repair.py --dry-run` to see what the old entrypoint would have dropped.
3. Run `python scripts/manual_schema_repair.py --i-have-a-backup` to apply.
4. Re-run `docker compose up`.

This is exactly the friction we want — destructive SQL must be deliberate, not implicit.

## Risks / things to watch

- The 2-3 production environments where the legacy `audit_sessions` schema still exists will need a one-time manual run of the repair script. Document this in deploy runbook.
- The `ORPHAN_CHECKS` list in the repair script is the same list that was in entrypoint.sh — same safety guarantees, just no longer automatic.
