"""deploy_live.sh must refuse the wrong server, and must not change anything by default.

Both properties come from incidents. On 2026-08-18 a full production deploy
stage ran on the training box: all three servers carry the same
docker-compose.yml, and it defines web_live on every one of them, so the
commands found a stack called "live" and operated on it without a word. What
should have stopped it was an `echo "$(hostname)"` at the top of the previous
stage — and an echo prevents nothing, least of all in a stage that gets skipped.

The dry run matters for the same reason: an operator pasting a block to *look*
at the state must not discover that looking was deploying.
"""

from pathlib import Path
import re
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "deployment" / "docker" / "deploy_live.sh"
LIVE_IP = "72.62.239.220"


def _run(hostname_ip: str, *args):
    """Drive the real gate with `hostname -I` stubbed to a chosen address."""
    source = SCRIPT.read_text(encoding="utf-8")
    gate = source[source.index("IP=\"$(hostname -I"):source.index("cd \"$PROJECT_ROOT\"")]
    harness = f"""
set -Eeuo pipefail
LIVE_IP={LIVE_IP}
hostname() {{ [ "${{1:-}}" = "-I" ] && printf '{hostname_ip} 10.0.0.1\\n' || printf 'stub-host\\n'; }}
ok()  {{ printf 'OK %s\\n' "$1"; }}
die() {{ printf 'DIE %s\\n' "$1" >&2; exit 1; }}
{gate}
echo REACHED_BODY
"""
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)


def test_the_wrong_server_stops_the_deploy():
    """The planted defect: the training box, which carries an identical stack."""
    result = _run("69.62.115.97")

    assert result.returncode == 1
    assert "REACHED_BODY" not in result.stdout
    assert "69.62.115.97" in result.stderr


def test_the_live_server_is_let_through():
    result = _run(LIVE_IP)

    assert result.returncode == 0
    assert "REACHED_BODY" in result.stdout


def test_an_echo_would_not_have_stopped_it():
    """What the script used to rely on, shown proceeding on the wrong host."""
    result = subprocess.run(
        ["bash", "-c", 'echo "══ $(hostname) ══"\necho REACHED_BODY'],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0 and "REACHED_BODY" in result.stdout


def _executed_lines() -> list[str]:
    return [
        line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_nothing_changes_without_apply():
    """Driven, not read: the dry run must invoke nothing that changes state.

    This began as a line-order check — every changing command had to appear
    after the `exit 0`. That held until the build moved above the dry-run exit
    so the migration plan could be read from the new image, and then the order
    heuristic failed on `git reset --hard` while the real question was whether
    it *runs*. Position is not the property; execution is.

    git, compose, curl and backup.sh are all replaced by recorders.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    body = source[source.index('say "2/8'):source.index('say "5/8')]

    harness = f"""
set -Eeuo pipefail
APPLY=0
SCRIPT_DIR=/nonexistent
C=compose_stub
compose_stub() {{ printf 'COMPOSE %s\n' "$*"; }}
git() {{ printf 'GIT %s\n' "$*"; [ "${{1:-}}" = "rev-parse" ] && echo same; return 0; }}
sql() {{ echo 0; }}
say()  {{ :; }}
ok()   {{ :; }}
warn() {{ :; }}
die()  {{ printf 'DIE %s\n' "$1"; exit 1; }}
{body}
echo REACHED_APPLY_ONLY_SECTION
"""
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=60)

    assert "GIT reset --hard" not in result.stdout, (
        "the dry run reset the working tree — it discards local changes, which "
        "is a change, not a check"
    )
    for forbidden in ("COMPOSE stop", "COMPOSE up -d", "backup.sh"):
        assert forbidden not in result.stdout, f"the dry run ran {forbidden}"
    assert "REACHED_APPLY_ONLY_SECTION" not in result.stdout, (
        "the dry run continued past its exit"
    )


def test_the_dry_run_still_builds_so_the_plan_is_real():
    """The plan has to be read from the new image, or it reports the old one.

    On 2026-08-19 the check ran before the build and answered "no pending
    migrations" while eight were waiting: it was asking the running image,
    which carried the previous code.
    """
    lines = _executed_lines()
    build = next(i for i, l in enumerate(lines) if "$C build" in l)
    plan = next(i for i, l in enumerate(lines) if "showmigrations --plan" in l)
    exits = next(i for i, l in enumerate(lines) if l.strip() == "exit 0")

    assert build < plan < exits, (
        "the migration plan must be read from a freshly built image, and both "
        "must happen before the dry run exits"
    )


def test_the_migration_runs_in_a_throwaway_container_before_the_restart():
    """The whole reason a failed migration cannot crash-loop production.

    Inside entrypoint.sh under `set -e` a failing migrate exits the container,
    `restart: unless-stopped` runs it again, and the site is down in a loop —
    measured on two environments on 2026-08-17. In a `--rm` container the same
    failure is a message, and the old container is still serving.
    """
    lines = _executed_lines()
    migrate = next(i for i, l in enumerate(lines) if "manage.py migrate --noinput" in l)
    run_rm = next(i for i, l in enumerate(lines) if "$C run --rm" in l and i <= migrate)
    up = next(i for i, l in enumerate(lines) if "$C up -d --no-deps" in l)

    assert run_rm <= migrate < up, "the migration must be thrown away, and precede the restart"


def test_no_secret_value_is_printed():
    """The keys are checked for presence; their values never reach an output call.

    Checked on what is passed to the output function, not on the whole line: an
    earlier version rejected `[ -n "$value" ] || die "..."`, where the variable
    is in the *test* and the message never interpolates it. A guard that flags
    correct code gets edited away, and then it guards nothing.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    printers = re.compile(r"\b(ok|warn|die|echo|printf)\b(.*)$")

    for line in source.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = printers.search(line)
        if not match:
            continue
        assert "$value" not in match.group(2), (
            f"a secret value would be printed: {line.strip()}"
        )

    assert 'ok "$key' in source, "the check must still report which key it verified"
    assert '[ -n "$value" ]' in source, "the presence check itself must remain"


def _sql_helper() -> str:
    """The real helper, lifted from the script."""
    source = SCRIPT.read_text(encoding="utf-8")
    line = next(l for l in source.splitlines() if l.startswith("sql() {"))
    return line


QUERY_WITH_QUOTES = (
    'SELECT COUNT(*) FROM information_schema.columns '
    'WHERE table_name="documents_documentcanonicaldata";'
)


def test_a_query_containing_double_quotes_survives_the_helper():
    """It did not, and that stopped a production deploy at the pre-flight.

    The helper passed the query to `mysql -e "$1"`. A query carrying its own
    double-quoted identifiers closed that wrapper early, MySQL read the table
    name as a bare column, and the run died on

        ERROR 1054 (42S22) Unknown column 'documents_documentcanonicaldata'

    Safely — nothing had been backed up, built or stopped yet — but on the
    checker rather than on the thing it checks, which is the worst place for a
    guard to fail: it looks like the database is wrong.

    `$C` is stubbed by a function that swallows the compose arguments and
    passes stdin through, which is what `compose exec -T` does to mysql.
    """
    harness = f"""
passthrough() {{ cat; }}
C=passthrough
{_sql_helper()}
sql '{QUERY_WITH_QUOTES}'
"""
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == QUERY_WITH_QUOTES, (
        f"the query was mangled on the way to mysql: {result.stdout!r}"
    )


def test_the_shipped_helper_mangled_it(tmp_path):
    """Plant the form that shipped and let a stub mysql report what it received.

    The mangling happens when the shell parses the command, not when the string
    is built — so the string has to be executed to see it. A `mysql` on PATH
    prints its arguments instead of connecting to anything.
    """
    stub = tmp_path / "mysql"
    stub.write_text('#!/bin/sh\nprintf "ARG:%s\\n" "$@"\n', encoding="utf-8")
    stub.chmod(0o755)

    harness = f'''
export PATH="{tmp_path}:$PATH"
passthrough() {{ shift 3; "$@"; }}
C=passthrough
sql() {{ $C exec -T db_live sh -c "exec mysql -N -B -e \\"$1\\""; }}
sql '{QUERY_WITH_QUOTES}'
'''
    result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    received = [l[4:] for l in result.stdout.splitlines() if l.startswith("ARG:")]

    assert received, f"the stub was never reached: {result.stdout!r} {result.stderr!r}"
    assert QUERY_WITH_QUOTES not in received, (
        "the old form delivered the query intact — it did not in production. "
        f"mysql received: {received!r}"
    )
    assert any("documents_documentcanonicaldata" in a and '"' not in a for a in received), (
        f"the identifier should arrive stripped of its quotes: {received!r}"
    )


def test_every_pre_flight_query_goes_through_the_helper():
    """No query may reach mysql by a route the test above does not cover."""
    for line in _executed_lines():
        if "mysql" in line and not line.startswith("sql() {"):
            assert "backup.sh" in line, f"a query bypasses the helper: {line.strip()}"
