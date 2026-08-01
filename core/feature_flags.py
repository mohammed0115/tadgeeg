"""Availability of optional feature modules.

Some app packages ship in the tree but are deliberately NOT registered in
``INSTALLED_APPS``. Importing their models raises at import time::

    RuntimeError: Model class apps.jobs.models.JobPost doesn't declare an
    explicit app_label and isn't in an application in INSTALLED_APPS.

Because ``include()`` imports a URLConf while the URL tree is being built,
a single such import anywhere in the routed tree stops the *process* from
starting — not just one endpoint. So installed code must never import from
an unregistered app; it asks here instead.

The check is against the app registry, not a settings constant, so it can
never drift from reality: register the app and the feature turns on with no
edit here.

See docs/adr/0003-quarantine-apps-jobs.md for the jobs quarantine and what
re-enabling requires.
"""

from __future__ import annotations

from django.apps import apps as django_apps


def is_app_installed(app_label: str) -> bool:
    """True if ``app_label`` (e.g. ``"apps.jobs"``) is in INSTALLED_APPS."""
    return any(cfg.name == app_label for cfg in django_apps.get_app_configs())


def jobs_enabled() -> bool:
    """True when the recruitment (jobs) module is registered and usable.

    Currently False on every deployment — ``apps.jobs`` is quarantined. Callers
    MUST branch on this before importing anything from ``apps.jobs``; importing
    unconditionally is what breaks process startup.
    """
    return is_app_installed("apps.jobs")


#: Value reported for jobs-derived counters while the module is quarantined.
#: ``None`` rather than ``0`` on purpose: zero is a factual claim ("no open
#: jobs"), and the truth is "we cannot know — the feature is off". Response
#: keys are kept so the API shape does not change for existing clients; the
#: companion ``jobs_feature_enabled`` flag lets a UI render "unavailable"
#: instead of a misleading zero.
JOBS_DISABLED_COUNT = None
