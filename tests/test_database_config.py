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
