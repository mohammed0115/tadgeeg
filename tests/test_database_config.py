from pathlib import Path

from core.utils.database import build_default_database, build_test_database


BASE_DIR = Path(__file__).resolve().parents[1]


def test_default_database_uses_sqlite_when_requested():
    backend, config = build_default_database(BASE_DIR, {"DB_BACKEND": "sqlite", "SQLITE_NAME": "local.sqlite3"})
    assert backend == "sqlite"
    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert str(config["NAME"]).endswith("local.sqlite3")


def test_default_database_uses_mysql_when_requested():
    backend, config = build_default_database(
        BASE_DIR,
        {
            "DB_BACKEND": "mysql",
            "DB_NAME": "finai_live",
            "DB_USER": "finai",
            "DB_PASSWORD": "secret",
            "DB_HOST": "db",
            "DB_PORT": "3307",
        },
    )
    assert backend == "mysql"
    assert config["ENGINE"] == "django.db.backends.mysql"
    assert config["NAME"] == "finai_live"
    assert config["HOST"] == "db"
    assert config["PORT"] == "3307"


def test_test_database_prefers_mysql_when_test_backend_enabled():
    backend, config = build_test_database(
        BASE_DIR,
        {
            "TEST_DB_BACKEND": "mysql",
            "TEST_DB_NAME": "finai_test",
            "TEST_DB_USER": "finai_test",
            "TEST_DB_PASSWORD": "pw",
        },
    )
    assert backend == "mysql"
    assert config["ENGINE"] == "django.db.backends.mysql"
    assert config["NAME"] == "finai_test"


def test_test_database_falls_back_to_in_memory_sqlite():
    backend, config = build_test_database(BASE_DIR, {})
    assert backend == "sqlite"
    assert config["ENGINE"] == "django.db.backends.sqlite3"
    assert config["NAME"] == ":memory:"


# ── Statement timeout ─────────────────────────────────────────────────────────
# A slow query used to pin a gunicorn worker until the 120s worker timeout, so
# three of them took the site down. `max_execution_time` bounds that. The
# syntax below was validated against a real mysql:8.4: the init_command is
# accepted, a slow SELECT aborts with error 3024, and INSERT..SELECT is
# untouched — which is why the docstring in core/utils/database.py says the
# guard covers reads only.

def _init_command(env):
    return build_default_database(BASE_DIR, {"DB_NAME": "finai_live", **env})[1]["OPTIONS"]["init_command"]


def test_web_connections_get_a_statement_timeout_below_the_gunicorn_timeout():
    """30s < gunicorn's 120s: MySQL gives up first and names the query."""
    assert "max_execution_time=30000" in _init_command({})


def test_statement_timeout_is_overridable():
    assert "max_execution_time=5000" in _init_command({"DB_STATEMENT_TIMEOUT_MS": "5000"})


def test_zero_disables_the_statement_timeout_for_celery():
    """celery_live/celery_dev set this: an audit run legitimately reads for minutes."""
    assert "max_execution_time" not in _init_command({"DB_STATEMENT_TIMEOUT_MS": "0"})


def test_sql_mode_is_never_lost_when_the_timeout_is_added():
    """Regression: STRICT_TRANS_TABLES silently dropped would let bad data in."""
    for env in ({}, {"DB_STATEMENT_TIMEOUT_MS": "0"}, {"DB_STATEMENT_TIMEOUT_MS": "5000"}):
        assert "sql_mode='STRICT_TRANS_TABLES'" in _init_command(env)


def test_garbage_timeout_falls_back_to_the_default_rather_than_crashing():
    """A typo'd env var must not take the site down at import time."""
    for bad in ("abc", "-1", "", "   ", "30_000ms"):
        assert "max_execution_time=30000" in _init_command({"DB_STATEMENT_TIMEOUT_MS": bad})


def test_connect_timeout_is_set_so_a_half_open_db_host_cannot_hang_a_worker():
    _, config = build_default_database(BASE_DIR, {"DB_NAME": "finai_live"})
    assert config["OPTIONS"]["connect_timeout"] == 10
    _, config = build_default_database(BASE_DIR, {"DB_NAME": "finai_live", "DB_CONNECT_TIMEOUT": "3"})
    assert config["OPTIONS"]["connect_timeout"] == 3


def test_the_test_database_has_no_statement_timeout_by_default():
    """Fixture setup and schema migration run long; a timeout there is flake."""
    _, config = build_test_database(BASE_DIR, {"TEST_DB_BACKEND": "mysql", "TEST_DB_NAME": "finai_test"})
    assert "max_execution_time" not in config["OPTIONS"]["init_command"]
