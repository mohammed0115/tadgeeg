"""The container entrypoint must run migrations in exactly one container.

web_live and celery_live both build from the same image and both wait on
`db_live: service_healthy`, so they were released together and ran
`manage.py migrate` at the same instant. DDL in MySQL is not transactional — it
auto-commits — so a race between two migrate processes can leave a half-applied
migration that no rollback undoes.

The gate matches by EXCLUSION, not inclusion, and that detail is the whole point:
the web services start as `sh -c "gunicorn ..."`, so $1 is `sh`, not `gunicorn`.
An allow-list of gunicorn/python would match nothing and silently skip migrations
in every container while looking correct — which is how the seeding gate above it
was already written, for the same reason.
"""

from pathlib import Path
import re
import subprocess

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker" / "entrypoint.sh"

# $1 as each service actually starts, taken from the compose files:
#   web_live / web_dev / web_test : sh -c "gunicorn finai_backend.wsgi:application ..."
#   celery_live / celery_dev      : celery -A finai_backend worker ...
#   celery_beat                   : celery -A finai_backend beat ...
WEB_ARGV0 = "sh"
CELERY_ARGV0 = "celery"


def _migrate_case_block() -> str:
    """The real case statement guarding migrate, lifted from the entrypoint."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(
        r"(case \"\$\{1:-\}\" in.*?python manage\.py migrate.*?\nesac)",
        text,
        re.S,
    )
    assert match, "the migrate call is no longer inside a case block"
    return match.group(1)


def _run(block: str, argv0: str) -> str:
    """Execute the block with `python` stubbed so we can see what it would call."""
    script = f"python() {{ echo \"PYTHON $*\"; }}\n{block}\n"
    result = subprocess.run(
        ["sh", "-s", argv0], input=script, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


class TestTheGateBehaves:
    def test_the_web_container_migrates(self):
        out = _run(_migrate_case_block(), WEB_ARGV0)
        assert "PYTHON manage.py migrate" in out, (
            "web must migrate; an unmigrated schema with a running site is the worse failure"
        )

    def test_the_celery_container_does_not_migrate(self):
        out = _run(_migrate_case_block(), CELERY_ARGV0)
        assert "PYTHON manage.py migrate" not in out
        assert "Skipping migrate" in out

    def test_exactly_one_of_the_two_migrates(self):
        block = _migrate_case_block()
        runs = [
            "PYTHON manage.py migrate" in _run(block, argv0)
            for argv0 in (WEB_ARGV0, CELERY_ARGV0)
        ]
        assert runs.count(True) == 1, f"expected exactly one migrating container, got {runs}"


class TestThePlantedViolations:
    """Each proves the guard fails on the mistake it exists to prevent."""

    def test_an_ungated_entrypoint_would_migrate_in_both(self):
        ungated = "python manage.py migrate --noinput --fake-initial"
        runs = [
            "PYTHON manage.py migrate" in _run(ungated, argv0)
            for argv0 in (WEB_ARGV0, CELERY_ARGV0)
        ]
        assert runs == [True, True], "this is the race the gate removes"

    def test_an_allow_list_gate_would_migrate_in_neither(self):
        """The trap the seeding comment warns about, reproduced."""
        allow_list = (
            'case "${1:-}" in\n'
            "  gunicorn|python)\n"
            "    python manage.py migrate --noinput\n"
            "    ;;\n"
            "esac"
        )
        runs = [
            "PYTHON manage.py migrate" in _run(allow_list, argv0)
            for argv0 in (WEB_ARGV0, CELERY_ARGV0)
        ]
        assert runs == [False, False], (
            "an allow-list matches neither container and silently skips every migration"
        )


def test_every_celery_service_in_every_compose_starts_with_celery():
    """The gate is worthless if a celery service is launched some other way."""
    root = Path(__file__).resolve().parents[1]
    for compose in ("docker-compose.yml", "deployment/docker/docker-compose.yml"):
        text = (root / compose).read_text(encoding="utf-8")
        # No service may override the image ENTRYPOINT, or the gate never runs.
        assert "entrypoint:" not in text, f"{compose} overrides the entrypoint"
        for match in re.finditer(r"command:\s*(>-?\s*\n\s*)?(?P<first>[^\s\n]+)", text):
            first = match.group("first")
            if first == "celery":
                break
        else:
            pytest.fail(f"{compose}: found no service whose command starts with celery")
