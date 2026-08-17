"""update.sh must refuse to deploy when a pending unique constraint would fail.

An AddConstraint(UniqueConstraint) migration is applied to rows that already
exist, so duplicates make it fail. That failure is not a stopped deploy: migrate
runs inside entrypoint.sh under `set -e`, the container exits,
`restart: unless-stopped` restarts it, and it fails again — the site goes down in
a crash loop, and the backup taken moments earlier can only be used by taking the
site down further to restore it.

The check was first written as a runbook step. A runbook step is a step somebody
has to remember on the day, so it moved into the script, where it runs before the
dump is written, before the git reset, and before any container is touched.

Every assertion below drives the real function extracted from update.sh, with
`compose` stubbed to return what MySQL would. The runbook's own rule applies:
each check in this script was proven by making it fail.
"""

from pathlib import Path
import re
import subprocess

import pytest

UPDATE_SH = Path(__file__).resolve().parents[1] / "deployment" / "docker" / "update.sh"


def _function_source() -> str:
    text = UPDATE_SH.read_text(encoding="utf-8")
    match = re.search(
        r"(assert_no_unique_constraint_violations\(\) \{.*?\n\})", text, re.S
    )
    assert match, "assert_no_unique_constraint_violations is gone from update.sh"
    return match.group(1)


def _run(target: str, mysql_stdout: str, db_running: bool = True):
    """Drive the real function with compose/mysql stubbed."""
    running = "db_live" if db_running else ""
    harness = f"""
set -e
TARGET={target}
log() {{ printf 'LOG %s\\n' "$1"; }}
ok()  {{ printf 'OK %s\\n' "$1"; }}
err() {{ printf 'ERR %s\\n' "$1"; }}
compose() {{
  case "$1" in
    ps)   printf '%s\\n' "{running}" ;;
    exec) printf '%s' "{mysql_stdout}" ;;
  esac
}}
{_function_source()}
assert_no_unique_constraint_violations
echo REACHED_END
"""
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=30
    )


class TestItBlocksTheDeploy:
    def test_duplicates_abort_before_anything_changes(self):
        """The planted violation: rows that the constraint cannot accept."""
        r = _run("live", "3")
        assert r.returncode == 1, "a deploy that would crash-loop must not proceed"
        assert "REACHED_END" not in r.stdout
        assert "duplicate group(s)" in r.stdout
        assert "aborted before any code or container changed" in r.stdout

    def test_the_operator_is_told_how_to_look(self):
        r = _run("live", "2")
        assert "GROUP BY" in r.stdout, "an abort without the query is a dead end"
        assert "data decision" in r.stdout, "which row survives is not the deploy's call"

    def test_a_stopped_database_is_an_abort_not_a_silent_skip(self):
        r = _run("live", "0", db_running=False)
        assert r.returncode == 1
        assert "cannot check constraints" in r.stdout


class TestItLetsCleanDeploysThrough:
    def test_zero_duplicates_passes(self):
        r = _run("live", "0")
        assert r.returncode == 0
        assert "REACHED_END" in r.stdout
        assert "no duplicate" in r.stdout

    def test_a_missing_table_is_not_a_violation(self):
        """The constraint ships with the migration that creates the table."""
        r = _run("live", "")
        assert r.returncode == 0
        assert "REACHED_END" in r.stdout
        assert "table absent" in r.stdout

    def test_non_live_targets_are_skipped(self):
        r = _run("dev", "9")
        assert r.returncode == 0, "dev has no db_live to check"
        assert "REACHED_END" in r.stdout


def _executed_lines() -> list[str]:
    """Lines that actually run — comments mention commands too."""
    return [
        line for line in UPDATE_SH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_check_runs_before_the_backup_and_the_git_reset():
    """Order is the point: read-only first, then the dump, then code changes.

    Matched against executed lines only. `git reset --hard` also appears twice in
    comments in this file, and an earlier version of this test matched one of
    them and reported the order backwards.
    """
    lines = _executed_lines()
    idx = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "assert_no_unique_constraint_violations":
            idx.setdefault("check", i)
        elif stripped == "backup_live_database":
            idx.setdefault("backup", i)
        elif stripped.startswith("git reset --hard"):
            idx.setdefault("reset", i)

    assert "check" in idx, "the pre-flight is no longer called"
    assert "backup" in idx and "reset" in idx
    assert idx["check"] < idx["backup"], (
        "the check must precede the backup it exists to avoid needing"
    )
    assert idx["check"] < idx["reset"], "the check must precede any code change"


def test_the_known_risky_constraint_is_covered():
    """The constraint this deploy ships must be in the pre-flight list.

    Deliberately narrow. An earlier version asserted that *every* UniqueConstraint
    added by AddConstraint anywhere in the tree was covered, and it was wrong on
    both ends: it matched `model_name=` as a constraint name, it counted
    CheckConstraints, and above all it could not tell a constraint pending on this
    database from one applied months ago — apps/invoices/0008 has been live since
    long before this check existed. Whether a migration is pending is a property
    of the target database, not of the source tree, so the test does not pretend
    to compute it.
    """
    covered = _function_source()
    assert "storage_management_filestoragemapping" in covered
    assert "uniq_storage_mapping_version_per_file" in covered
    assert "file_id, version_number" in covered


def test_a_constraint_on_a_newly_added_nullable_column_needs_no_check():
    """Why webhooks is absent from the list, asserted rather than asserted-in-prose."""
    root = Path(__file__).resolve().parents[1]
    body = (
        root / "apps/webhooks/migrations/0002_webhookdelivery_event_key_and_more.py"
    ).read_text(encoding="utf-8")
    assert "AddField" in body and "event_key" in body
    assert "null=True" in body, (
        "if event_key ever stops being nullable, every existing row collides "
        "and this constraint needs a pre-flight entry too"
    )
    assert "unique_webhook_endpoint_event" in body
    assert "unique_webhook_endpoint_event" not in _function_source(), (
        "covering it would be harmless but misleading: NULLs never collide"
    )


class TestRehearsalDumpDetection:
    """The rehearsal must not reject a directory that holds a real dump.

    `ls a b` exits non-zero when EITHER operand is missing, so the first version
    of this check — `ls "$DIR"/*.sql "$DIR"/*.sql.gz` — rejected a directory
    containing a perfectly good db.sql.gz merely because no plain .sql sat beside
    it. It stopped a real rehearsal with "the copy is incomplete", which is the
    worst kind of guard: one that blocks correct work and sends you looking for a
    problem that is not there.
    """

    REHEARSE_SH = (
        Path(__file__).resolve().parents[1] / "deployment" / "docker" / "rehearse_migrations.sh"
    )

    def _detect(self, tmp_path, filenames):
        """Run the real detection loop lifted from the script."""
        for name in filenames:
            (tmp_path / name).touch()
        text = self.REHEARSE_SH.read_text(encoding="utf-8")
        match = re.search(r"(  dump_found=0\n.*?dump_found\" -eq 1 \])", text, re.S)
        assert match, "the dump detection loop is gone from rehearse_migrations.sh"
        snippet = match.group(1).replace('|| \\\n', '|| ')
        harness = f'SRC_DIR="{tmp_path}"\n{snippet} && echo FOUND || echo MISSING\n'
        out = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, timeout=30
        ).stdout
        return "FOUND" in out

    def test_a_gzipped_dump_alone_is_accepted(self, tmp_path):
        """The exact case that was wrongly rejected: backup.sh writes db.sql.gz."""
        assert self._detect(tmp_path, ["db.sql.gz", "MANIFEST.txt"]) is True

    def test_a_plain_dump_alone_is_accepted(self, tmp_path):
        assert self._detect(tmp_path, ["db.sql"]) is True

    def test_both_together_are_accepted(self, tmp_path):
        assert self._detect(tmp_path, ["db.sql", "db.sql.gz"]) is True

    def test_a_directory_with_no_dump_is_still_rejected(self, tmp_path):
        """The guard must keep catching a truncated copy — that was its purpose."""
        assert self._detect(tmp_path, ["MANIFEST.txt"]) is False

    def test_the_original_ls_form_produced_the_false_alarm(self, tmp_path):
        """Plant the defect and show it rejecting a valid backup directory."""
        (tmp_path / "db.sql.gz").touch()
        broken = subprocess.run(
            ["bash", "-c", f'ls "{tmp_path}"/*.sql "{tmp_path}"/*.sql.gz >/dev/null 2>&1'],
            capture_output=True, text=True, timeout=30,
        )
        assert broken.returncode != 0, (
            "if this ever passes, `ls` stopped failing on a missing operand and "
            "the original bug would not have occurred"
        )
