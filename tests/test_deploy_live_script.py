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
    """A run with no flag reads and exits before the backup, code or containers."""
    lines = _executed_lines()
    exits = next(i for i, l in enumerate(lines) if l.strip() == "exit 0")
    for changing in ("backup.sh", "git reset --hard", "$C build", "$C stop", "$C up -d"):
        first = next((i for i, l in enumerate(lines) if changing in l), None)
        assert first is not None, f"{changing} is gone from the script"
        assert first > exits, f"{changing} runs before the dry-run exit"


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
