"""Every third-party import must be declared in the file the image installs.

`scipy` was pinned in `requirements.lock.txt` and absent from
`requirements.txt`. The Dockerfile installs `requirements.txt`. So
`apps/analytics/benford_service.py`, whose `from scipy import stats` sits at
module level, could not be imported in any built image — the module would raise
ModuleNotFoundError the moment anything touched it.

Nothing caught this, and nothing would have: the lock file *looked* like the
declaration, the local dev machine had whatever pip last resolved, and the one
place the gap shows is a container nobody imports that module in.

The check is deliberately about the *installed* file rather than the lock file.
A dependency that only the lock file knows about is not installed anywhere that
matters.
"""

from __future__ import annotations

import ast
import re
import sys

import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO / "requirements.txt"

#: Distribution name → the module name it actually provides. Only listed where
#: the two differ; everything else is matched by normalising the name.
PROVIDES = {
    "pillow": "PIL",
    "pyjwt": "jwt",
    "python-dotenv": "dotenv",
    "psycopg2-binary": "psycopg2",
    "scikit-learn": "sklearn",
    "mysqlclient": "MySQLdb",
    "django-storages": "storages",
    "djangorestframework": "rest_framework",
    "djangorestframework-simplejwt": "rest_framework_simplejwt",
    "pymupdf": "fitz",
    "beautifulsoup4": "bs4",
    "python-magic": "magic",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "pyyaml": "yaml",
    "google-auth": "google",
    "protobuf": "google",
    "python-barcode": "barcode",
    "qrcode": "qrcode",
    "sentry-sdk": "sentry_sdk",
    "drf-spectacular": "drf_spectacular",
    "django-cors-headers": "corsheaders",
    "django-countries": "django_countries",
    "django-filter": "django_filters",
    "python-dateutil": "dateutil",
    "typing-extensions": "typing_extensions",
    "pytest-django": "pytest_django",
}

#: Imports that are legitimately absent from requirements.txt.
EXEMPT = {
    # First-party.
    "apps", "core", "navigation", "finai_backend", "tests",
    # Test-only tooling; the suite is not what the image runs.
    "pytest", "polib", "faker", "factory",
}


def _declared_modules():
    modules = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[><=!\[;]", line)[0].strip().lower()
        if not name:
            continue
        modules.add(PROVIDES.get(name, name.replace("-", "_")))
    return modules


def _top_level_imports():
    """Module-level third-party imports across the shipped code.

    Only module level: an import inside a function is a deliberate optional
    dependency and fails where the caller can handle it. A top-level one takes
    the whole module down at import time — which is the failure mode this file
    exists for.
    """
    found = {}
    for pattern in ("apps/**/*.py", "core/**/*.py", "navigation/*.py",
                    "finai_backend/*.py"):
        for path in REPO.glob(pattern):
            rel = str(path.relative_to(REPO))
            if "/migrations/" in rel or "/tests/" in rel or "test_" in path.name:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:                      # module level only
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.setdefault(alias.name.split(".")[0], rel)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        found.setdefault(node.module.split(".")[0], rel)
    return found


def test_every_top_level_third_party_import_is_declared():
    declared = _declared_modules()
    stdlib = sys.stdlib_module_names

    missing = []
    for module, where in sorted(_top_level_imports().items()):
        if module in stdlib or module in EXEMPT or module.startswith("_"):
            continue
        if module in declared:
            continue
        missing.append(f"{module}  (imported at module level in {where})")

    assert not missing, (
        "third-party imports missing from requirements.txt — the Dockerfile "
        "installs that file, so these modules cannot be imported in a built "
        "image:\n  " + "\n  ".join(missing)
    )


def test_scipy_specifically_is_declared():
    """The one that got through, named so a rename cannot lose it quietly."""
    assert "scipy" in _declared_modules(), (
        "scipy is imported at module level by apps/analytics/benford_service.py"
    )


#: Declared, and imported INSIDE a function so the module still loads without
#: them — which is exactly why their absence is invisible. Each one silences a
#: feature rather than raising: no scipy meant Benford could not run, no
#: sklearn meant the anomaly detector returned zero anomalies, and "zero
#: anomalies" reads as "the books are clean". Three separate packages have now
#: been declared-but-uninstalled in this repository; this test is the tripwire.
FEATURE_CRITICAL_MODULES = {
    "scipy": "Benford chi-square (apps/analytics/benford_service.py)",
    "sklearn": "Isolation Forest anomaly detection (apps/analytics/anomaly_service.py)",
    "numpy": "numeric core for both of the above",
}


@pytest.mark.parametrize("module,feature", sorted(FEATURE_CRITICAL_MODULES.items()))
def test_feature_critical_modules_are_actually_importable(module, feature):
    """Declaring a dependency is not the same as having it.

    A lazy import inside a function turns a missing package into a quietly
    degraded feature. For an audit product the degraded state is worse than the
    crash: the run completes, reports nothing, and looks like a pass.
    """
    import importlib

    try:
        importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - the failure IS the message
        pytest.fail(
            f"{module} is declared in requirements but not installed here, so "
            f"{feature} silently does nothing. Install it: pip install -r requirements.txt"
        )


def test_the_lock_file_does_not_contradict_requirements():
    """A package pinned below its declared floor would install the wrong build."""
    lock = {}
    for line in (REPO / "requirements.lock.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][^\s;#]*)", line.strip())
        if match:
            lock[match.group(1).lower().replace("_", "-")] = match.group(2)

    conflicts = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?>=([0-9][^\s,;]*)", line)
        if not match:
            continue
        name, floor = match.group(1).lower().replace("_", "-"), match.group(2)
        pinned = lock.get(name)
        if pinned and _version(pinned) < _version(floor):
            conflicts.append(f"{name}: requirements.txt wants >={floor}, lock pins {pinned}")

    assert not conflicts, "lock file contradicts requirements.txt:\n  " + "\n  ".join(conflicts)


def _version(text):
    parts = []
    for piece in text.split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)
