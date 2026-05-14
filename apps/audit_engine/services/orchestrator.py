"""DEPRECATED — superseded by AuditPipelineV2.

Use ``apps.rule_engine.services.compatibility.legacy_audit_adapter.LegacyAuditOrchestratorAdapter``
as a drop-in replacement.

The full legacy implementation was removed during the BIG4-audit cleanup
round (architectural finding A-1: three parallel audit apps). Importing
``AuditOrchestrator`` from here now raises so leftover call sites fail
loudly instead of silently using deprecated code.
"""
from __future__ import annotations


class _DeprecatedAuditOrchestrator:
    """Placeholder that fails loudly. Do not instantiate."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "AuditOrchestrator is removed. Use "
            "apps.rule_engine.services.compatibility.legacy_audit_adapter."
            "LegacyAuditOrchestratorAdapter instead."
        )


AuditOrchestrator = _DeprecatedAuditOrchestrator
