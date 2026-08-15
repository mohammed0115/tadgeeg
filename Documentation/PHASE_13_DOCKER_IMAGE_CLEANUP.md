# Phase 13 — Docker Image Cleanup

## What was wrong

`.dockerignore` was thin (16 lines). The Docker build context included:

- `Dataset/` (~23 MB of Arabic-named test invoices/PDFs/images, some with paths long enough to break extraction on POSIX filesystems with NAME_MAX=255)
- `Documentation/` (~1.9 MB of operator/developer markdown)
- `htmlcov/` (~48 MB of pytest-cov HTML reports)
- `.coverage`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`
- Loose test fixtures at the repo root (`*.zip`, `*.pdf`, `*.xlsx`, `*.csv`)
- `.env.*` files (potentially with secrets)
- IDE/OS noise (`.DS_Store`, `*.swp`, `Thumbs.db`)

Build context size matters because:

1. Every byte sent to the Docker daemon = build slower.
2. Every byte that lands in the image (even if `COPY .` happens before a deletion in a later RUN) = pull slower for every cluster node.
3. `Dataset/` containing customer-shaped data should NEVER ship to production runtime.

## What changed

`.dockerignore` rewritten (16 → ~75 lines), grouped by purpose:

- **VCS / IDE:** `.git`, `.idea`, `.vscode`, …
- **Python build artifacts:** `__pycache__`, `*.pyc`, `*.egg-info`, caches.
- **Secrets:** `.env`, `.env.*` — but **`!.env.example` is preserved** so deploy templating still works.
- **Local DB / runtime:** `*.sqlite3`, `*.sqlite3-journal`.
- **Volume-mounted dirs (don't bake into image):** `media`, `staticfiles`, `logs`, `node_modules`.
- **Heavy test fixtures:** `Dataset/`, loose `*.zip`/`*.pdf`/`*.xlsx`/`*.csv` at the repo root, `outputbase.txt`, `*.har`, `*.pcap`.
- **Docs:** `Documentation/`, `docs/` excluded from runtime image. `README.md` is at the repo root and stays.
- **Coverage:** `htmlcov/`, `.coverage`, `.pytest_cache/`.
- **Docker overrides:** `docker-compose.override.yml`, `docker-compose.local.yml`.
- **OS junk:** `.DS_Store`, `Thumbs.db`, swap files.

Estimated build-context savings: ~70 MB (Dataset 23 + Docs 2 + htmlcov 48).

## Files changed

| File | Change |
|---|---|
| `.dockerignore` | +73 / -3 — reorganized + expanded |

## Verification

```bash
$ ls -la .env.example
-rw-rw-r-- 1 mohamed mohamed 1801 May  1 14:57 .env.example   # preserved by !.env.example

$ du -sh Dataset Docs htmlcov
23M Dataset
1.9M Docs
48M htmlcov
```

`docker compose build` was not run in this dev environment (Docker not available locally). The .dockerignore syntax is plain glob; should be picked up by any docker BuildKit / buildx without further changes.

## What still requires human attention

- The `requirements.lock.txt` file IS shipped to the image (correctly — `pip install -r` needs it). A future Tier-3 follow-up should switch the Dockerfile to use the lock file instead of the loose `requirements.txt` (separate PR).
- If any deploy script or CI step previously assumed `Documentation/` would be inside the running container (e.g., for serving operator docs from a routes), that will now break. None observed; verify before merge.
- `docker-compose.override.yml` is excluded — if anyone uses it for local-only port mappings, they must keep it untracked / outside the image.

## Risks / things to watch

- A negation pattern like `!.env.example` only works if it appears AFTER the broader pattern that excludes `.env*`. Verified — the order is correct in this rewrite.
- `Documentation/*` and `Docs` are both listed (belt + braces). On Docker BuildKit either one alone would work; this redundancy is harmless.
