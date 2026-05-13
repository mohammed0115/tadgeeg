"""AI Safety surface.

Closes four gaps the audit-review flagged:

  • Prompt versioning — every prompt sent to the model is a registered,
    hashed, immutable ``PromptTemplate`` row. Two engineers can't ship
    diverging prompts that produce different audit conclusions.

  • Output redaction — PII (Saudi national-id / Iqama / IBAN, credit
    card numbers) is masked in any text we LOG or PERSIST as evidence,
    regardless of whether the user pasted it into a chat.

  • Model registry — each model the platform may call is declared in
    ``MODEL_REGISTRY`` with cost / context-window / training-cutoff.
    Audit trail records which model produced each answer.

  • Cost cap — per-organization daily / monthly SAR cap. The
    ``CostLedger`` records every call; ``assert_within_budget()``
    refuses further calls when the cap is hit.

The module is intentionally framework-light: services + a single small
model (``CostLedger``). Existing AI services in ``apps/audit_engine``
plug in via the helpers in :mod:`apps.ai_safety.runtime`.
"""
