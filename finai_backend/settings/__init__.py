"""Settings package entry point.

`DJANGO_SETTINGS_MODULE=finai_backend.settings` is documented throughout the
project and should behave like the canonical settings module. Re-export the
base settings here so the package import stays backward compatible while the
environment-specific modules remain available.
"""

from pathlib import Path
import sys

_RUNNING_TESTS = "pytest" in Path(sys.argv[0]).name.lower() or "pytest" in sys.modules or any(
    arg == "test" for arg in sys.argv[1:]
)

if _RUNNING_TESTS:
    from .test import *  # noqa: F401,F403
else:
    from .base import *  # noqa: F401,F403
