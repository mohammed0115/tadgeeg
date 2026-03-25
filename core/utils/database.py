"""Database configuration helpers for SQLite/MySQL environments."""

from __future__ import annotations

import os
from pathlib import Path


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
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
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
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }

    return "sqlite", {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {
            "timeout": 30,  # Prevent connection hangs during testing
        },
    }
