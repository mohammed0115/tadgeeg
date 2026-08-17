"""update.sh must not report a successful deploy for a site that does not serve.

Step 4 was labelled "Health check" and checked nothing: it ran `compose ps`,
printed twenty log lines, and then printed "✅ Update COMPLETE" unconditionally.
A container can be `running` while gunicorn returns 500 to every request, and the
deploy would still finish green. HTTP verification existed only in redeploy.sh
and in a manual runbook step — the same category of problem as the constraint
check that used to live there.

The gate is whether the app serves a page. /health/ is reported but deliberately
does not gate, because it aggregates components of unequal weight and returns 503
if any one is degraded. Measured on the dev host while the site served perfectly:

    {"status": "unhealthy", "database": "healthy", "redis": "degraded", ...}

Gating on that would fail every deploy over an absent cache and train everyone to
ignore the gate. A degraded database is the exception and is fatal.
"""

from pathlib import Path
import re
import subprocess

UPDATE_SH = Path(__file__).resolve().parents[1] / "deployment" / "docker" / "update.sh"


def _function_source() -> str:
    text = UPDATE_SH.read_text(encoding="utf-8")
    match = re.search(r"(assert_service_actually_serves\(\) \{.*?\n\})", text, re.S)
    assert match, "assert_service_actually_serves is gone from update.sh"
    return match.group(1)


def _run(http_code: str, health_json: str, target: str = "live"):
    """Drive the real function with compose exec stubbed to return canned answers.

    The stub distinguishes the two `python -c` calls by what the script asks for:
    the first fetches "/", the second "/health/".
    """
    harness = f"""
set -e
TARGET={target}
ok()   {{ printf 'OK %s\\n' "$1"; }}
err()  {{ printf 'ERR %s\\n' "$1"; }}
warn() {{ printf 'WARN %s\\n' "$1"; }}
web_services_for_target() {{ echo "web_live celery_live"; }}
compose() {{
  case "$*" in
    *health*) printf '%s' '{health_json}' ;;
    *logs*)   printf 'stub logs\\n' ;;
    *)        printf '%s' '{http_code}' ;;
  esac
}}
{_function_source()}
assert_service_actually_serves
echo REACHED_END
"""
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=30
    )


HEALTHY = '{"status": "healthy", "database": "healthy", "redis": "healthy"}'
REDIS_DEGRADED = '{"status": "unhealthy", "database": "healthy", "redis": "degraded"}'
DB_DEGRADED = '{"status": "unhealthy", "database": "degraded", "redis": "healthy"}'
DB_UNHEALTHY = '{"status": "unhealthy", "database": "unhealthy", "redis": "healthy"}'


class TestItBlocksABrokenDeploy:
    def test_a_five_hundred_stops_the_deploy(self):
        """The planted defect: the container runs, the app does not serve."""
        r = _run("500", HEALTHY)
        assert r.returncode == 1
        assert "REACHED_END" not in r.stdout
        assert "does not serve" in r.stdout

    def test_no_response_at_all_stops_the_deploy(self):
        r = _run("000", HEALTHY)
        assert r.returncode == 1
        assert "REACHED_END" not in r.stdout

    def test_a_degraded_database_is_fatal_even_when_the_page_renders(self):
        """A homepage can be served from cache while every write is failing."""
        for payload in (DB_DEGRADED, DB_UNHEALTHY):
            r = _run("200", payload)
            assert r.returncode == 1, f"should have aborted on {payload}"
            assert "DATABASE degraded" in r.stdout


class TestItLetsAWorkingDeployThrough:
    def test_two_hundred_and_healthy_passes(self):
        r = _run("200", HEALTHY)
        assert r.returncode == 0
        assert "REACHED_END" in r.stdout
        assert "serves / with HTTP 200" in r.stdout

    def test_a_redirect_counts_as_serving(self):
        for code in ("301", "302"):
            r = _run(code, HEALTHY)
            assert r.returncode == 0, f"{code} is a served response"

    def test_a_degraded_cache_warns_but_never_blocks(self):
        """The exact payload measured on the dev host while the site worked."""
        r = _run("200", REDIS_DEGRADED)
        assert r.returncode == 0, (
            "gating on an absent cache would fail every deploy and train "
            "everyone to ignore the gate"
        )
        assert "REACHED_END" in r.stdout
        assert "WARN" in r.stdout

    def test_an_unanswerable_health_endpoint_warns_but_never_blocks(self):
        r = _run("200", "")
        assert r.returncode == 0
        assert "components unverified" in r.stdout


def test_the_gate_runs_before_the_success_banner():
    """Order is the whole point: ✅ must be unreachable by a broken deploy."""
    lines = [
        line for line in UPDATE_SH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    call = next(
        i for i, line in enumerate(lines)
        if line.strip() == "assert_service_actually_serves"
    )
    banner = next(i for i, line in enumerate(lines) if "Update COMPLETE" in line)
    assert call < banner, "the success banner must not be printable without the gate"


def test_the_old_unconditional_banner_would_have_passed_a_broken_deploy():
    """Plant the previous behaviour and show it reports success on a 500."""
    harness = """
set -e
compose() { printf 'stub\\n'; }
compose ps
echo "Update COMPLETE"
"""
    r = subprocess.run(["bash", "-c", harness], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "Update COMPLETE" in r.stdout, (
        "this is what step 4 used to do regardless of whether the site worked"
    )
