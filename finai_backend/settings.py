"""
DEPRECATED — kept as a delegation shim to prevent drift.

At runtime, Python imports the `finai_backend.settings` PACKAGE (the
`settings/` directory and its `__init__.py`), not this file. The package
chains through `settings/base.py` → `settings_canonical.py`. So this file
is dead code from a runtime perspective.

It is preserved (a) because some tooling, IDEs, and old `.env` workflows
historically pointed here, and (b) to avoid silently breaking developer
muscle memory. Any value defined here is overridden by whatever the
package exports.

Maintenance rule: do NOT add settings here. Edit
`finai_backend/settings_canonical.py` (the single source of truth) and
the `settings/*.py` overlays for environment-specific overrides
(`production.py`, `test.py`).

This shim re-exports the canonical settings so a direct
`from finai_backend.settings import X` (in code that bypasses the
package) still gets the right value.
"""
from finai_backend.settings_canonical import *  # noqa: F401, F403
