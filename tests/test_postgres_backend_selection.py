"""DB_BACKEND=postgres must actually select PostgreSQL.

Measured while rehearsing the migration: build_default_database knew mysql and
sqlite only, and its MySQL branch fires on a bare DB_NAME. A postgres
deployment sets DB_NAME, so it would have been handed
django.db.backends.mysql and failed on connect — with nothing in the error
pointing at the backend choice.

Two halves, and the first is easy to add without the second: the normaliser has
to recognise the word, and the branch has to be reached before MySQL's.
"""

from core.utils.database import build_default_database, _normalized_backend

BASE = "/tmp"


def test_the_word_postgres_is_recognised():
    for spelling in ("postgres", "postgresql", "PostgreSQL", "psql",
                     "django.db.backends.postgresql"):
        assert _normalized_backend(spelling) == "postgres", spelling


def test_db_backend_postgres_selects_the_postgres_engine():
    label, config = build_default_database(BASE, {"DB_BACKEND": "postgres"})

    assert label == "postgres"
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["PORT"] == "5432"


def test_postgres_wins_over_a_bare_db_name():
    """The ordering that makes the branch reachable at all.

    The MySQL branch fires on `env.get("DB_NAME")` alone. Every real deployment
    sets DB_NAME, so a postgres branch placed after it would never be reached
    and the failure would look like a connection problem.
    """
    label, config = build_default_database(
        BASE, {"DB_BACKEND": "postgres", "DB_NAME": "finai_live",
               "DB_HOST": "db", "DB_PORT": "5432"}
    )

    assert label == "postgres", "a bare DB_NAME still routed to MySQL"
    assert config["NAME"] == "finai_live"


def test_the_legacy_variable_works_too():
    label, _ = build_default_database(BASE, {"DB_ENGINE": "postgresql"})
    assert label == "postgres"


def test_mysql_and_sqlite_are_unchanged():
    """The branch is additive: nothing that worked may start choosing postgres."""
    assert build_default_database(BASE, {"DB_BACKEND": "mysql"})[0] == "mysql"
    assert build_default_database(BASE, {"DB_NAME": "finai_live"})[0] == "mysql"
    assert build_default_database(BASE, {})[0] == "sqlite"


def test_without_the_normaliser_the_branch_is_unreachable():
    """Plant the half-fix: the branch exists, the word is not recognised.

    Adding the branch alone reads as done and changes nothing — the code that
    decides never returns "postgres". This is the shape the repository keeps
    producing, so it gets its own assertion.
    """
    assert _normalized_backend("postgres") != "", (
        "the normaliser does not know the word, so the branch below it cannot "
        "be reached no matter how it is written"
    )
