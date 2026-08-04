"""Database configuration helpers for SQLite/MySQL environments."""

from __future__ import annotations

import os
from pathlib import Path

# A gunicorn worker blocked on a slow query is a worker that serves nobody. With
# three workers, three such queries take the whole site down while MySQL sits
# idle-ish — the outage looks like "the server is down" and the cause is one
# unindexed report. These two settings bound that.
#
# `max_execution_time` (MySQL 5.7.8+, milliseconds) aborts the *statement*, not
# the connection, and returns error 3024 to Django. Scope, stated plainly:
#   - it applies to read-only SELECT only;
#   - it does NOT apply to INSERT/UPDATE/DELETE, DDL, or SELECT inside a stored
#     program;
#   - it does NOT cover waiting on a row lock — that is
#     `innodb_lock_wait_timeout` (server default 50s), deliberately left alone
#     because the invoice-upload transaction holds locks for a while.
# So this is a guard against runaway reads, which is the failure we actually
# have, and not a general "no query may exceed N seconds" rule.
#
# The default is below gunicorn's 120s worker timeout on purpose: MySQL should
# be the one to give up, with a logged error naming the query, rather than
# gunicorn killing the worker and leaving the query still running server-side.
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_CONNECT_TIMEOUT_S = 10


def _int_env(env: os._Environ | dict, key: str, default: int) -> int:
    """Read an integer env var, falling back to `default` on absent/garbage."""
    raw = str(env.get(key, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _mysql_options(env: os._Environ | dict) -> dict:
    """Build MySQL OPTIONS with a statement timeout and a connect timeout.

    `DB_STATEMENT_TIMEOUT_MS=0` disables the statement timeout — needed by
    Celery workers, whose audit runs legitimately read for minutes, and by any
    long data migration.
    """
    statement_timeout_ms = _int_env(env, "DB_STATEMENT_TIMEOUT_MS", DEFAULT_STATEMENT_TIMEOUT_MS)

    settings = ["sql_mode='STRICT_TRANS_TABLES'"]
    if statement_timeout_ms > 0:
        settings.append(f"max_execution_time={statement_timeout_ms}")

    return {
        "charset": "utf8mb4",
        "init_command": "SET " + ", ".join(settings),
        # Without this, a MySQL host that accepts the TCP connection but never
        # completes the handshake blocks the worker until the OS gives up —
        # minutes, not seconds.
        "connect_timeout": _int_env(env, "DB_CONNECT_TIMEOUT", DEFAULT_CONNECT_TIMEOUT_S),
    }


def _normalized_backend(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"mysql", "django.db.backends.mysql"}:
        return "mysql"
    if raw in {"sqlite", "sqlite3", "django.db.backends.sqlite3"}:
        return "sqlite"
    return ""


def _sqlite_path(base_dir: Path, env: os._Environ | dict) -> Path:
    sqlite_name = env.get("SQLITE_NAME", "db_runtime.sqlite3")
    sqlite_path = Path(sqlite_name)
    if not sqlite_path.is_absolute():
        sqlite_path = base_dir / sqlite_path
    return sqlite_path


def build_default_database(base_dir: Path, env: os._Environ | dict | None = None) -> tuple[str, dict]:
    """Return the configured backend label and Django DATABASES['default'] value."""
    env = env or os.environ
    explicit_backend = _normalized_backend(env.get("DB_BACKEND"))
    legacy_backend = _normalized_backend(env.get("DB_ENGINE"))
    sqlite_path = _sqlite_path(base_dir, env)

    if explicit_backend == "mysql" or (not explicit_backend and legacy_backend == "mysql") or env.get("DB_NAME"):
        return "mysql", {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env.get("DB_NAME", "finai_live"),
            "USER": env.get("DB_USER", "finai_live_user"),
            "PASSWORD": env.get("DB_PASSWORD", ""),
            "HOST": env.get("DB_HOST", "127.0.0.1"),
            "PORT": env.get("DB_PORT", "3306"),
            "OPTIONS": _mysql_options(env),
        }

    return "sqlite", {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_path,
        "OPTIONS": {
            "timeout": 30,  # Prevent connection hangs on long-running queries
        },
    }


def build_test_database(base_dir: Path, env: os._Environ | dict | None = None) -> tuple[str, dict]:
    """Return the configured backend for test execution."""
    env = env or os.environ
    explicit_backend = _normalized_backend(env.get("TEST_DB_BACKEND")) or _normalized_backend(env.get("DB_BACKEND"))
    legacy_backend = _normalized_backend(env.get("DB_ENGINE"))

    if explicit_backend == "mysql" or env.get("TEST_DB_NAME") or (not explicit_backend and legacy_backend == "mysql" and env.get("DB_NAME")):
        return "mysql", {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env.get("TEST_DB_NAME") or env.get("DB_NAME") or "finai_test",
            "USER": env.get("TEST_DB_USER") or env.get("DB_USER") or "root",
            "PASSWORD": env.get("TEST_DB_PASSWORD") or env.get("DB_PASSWORD") or "",
            "HOST": env.get("TEST_DB_HOST") or env.get("DB_HOST") or "127.0.0.1",
            "PORT": env.get("TEST_DB_PORT") or env.get("DB_PORT") or "3306",
            # No statement timeout under test unless one is asked for explicitly:
            # fixture setup and migration of a fresh test schema run long, and a
            # timeout there produces flaky failures that say nothing about the
            # code under test.
            "OPTIONS": _mysql_options({**env, "DB_STATEMENT_TIMEOUT_MS": env.get("TEST_DB_STATEMENT_TIMEOUT_MS", "0")}),
        }

    return "sqlite", {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {
            "timeout": 30,  # Prevent connection hangs during testing
        },
    }
