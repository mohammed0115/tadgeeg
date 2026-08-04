"""One entry point for running an audit.

**The friction this removes.** `AuditPipelineV2.run()` needs a document id, a
document type and an organisation id. The Document already knows the last two —
so every caller looks them up, or worse, passes them down through a Celery
signature and a view and a compatibility shim. Two problems follow:

  · a wrong `document_type` audits a file against another type's rules and
    returns a confident, complete, wrong result. Nothing raises: the run
    finishes, the score is real, the rules were simply the wrong ones.
  · a caller that has a Document but not its organisation reaches for
    `request.user.organization`, which is not necessarily the document's owner.
    That is a cross-tenant audit waiting for the one request where they differ.

The facade takes a document id and derives the rest from the row itself. Both
mistakes become unrepresentable rather than discouraged.

**What it is not.** It does not wrap the pipeline's stages, re-implement its
idempotency, or add a layer over `AuditRun`. `AuditPipelineV2` is well built —
one responsibility per stage, `STAGE_CLASSES` open for extension — and hiding
it behind an abstraction that mirrors it would be a second thing to keep in
sync. This is a door, not a floor.

**Exceptions.** `process_document()` returns a result object in every case,
including failure. A caller in a Celery task, a view and a management command
all need the same answer to "did it work and why not", and three different
`except` blocks around the same pipeline is how the three drift apart. Callers
that genuinely want the exception can use `run_or_raise()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from django.db import transaction

logger = logging.getLogger("rule_engine.facade")

TriggerSource = Literal["upload", "manual", "scheduled", "reprocess"]


class AuditFacadeError(Exception):
    """Refused before the pipeline ran. The message is safe to show a user."""


@dataclass(frozen=True)
class AuditRunResult:
    """What happened, in a shape every caller can use without a try/except.

    Frozen because a result that callers can edit stops being a record of what
    happened and becomes a mutable bag — and the first thing anyone edits is
    the bit they did not like.
    """

    ok: bool
    audit_run_id: str | None = None
    status: str = ""
    risk_score: float | None = None
    risk_level: str = ""
    total_rules: int = 0
    failed_rules: int = 0
    warning_rules: int = 0
    error: str = ""
    #: True when the pipeline returned an existing run rather than executing.
    #: Callers that report "audit complete" to a user need to know they are
    #: looking at a previous answer.
    reused_existing: bool = False

    @property
    def needs_attention(self) -> bool:
        """Did the audit find something an auditor should look at?

        Distinct from `ok`, which is about whether the audit RAN. A clean
        document and a crashed pipeline are both "no failures" if you only
        count findings, and collapsing them is how an outage reads as a pass.
        """
        return self.ok and (self.failed_rules > 0 or self.warning_rules > 0)


class AuditFacade:
    """The single entry point external code should use to audit a document."""

    @staticmethod
    def process_document(
        document_id: UUID | str,
        *,
        triggered_by: TriggerSource = "upload",
        force_rerun: bool = False,
        dry_run: bool = False,
    ) -> AuditRunResult:
        """Audit one document. Never raises for a pipeline failure.

        The document type and organisation are read from the Document row, not
        accepted from the caller — see the module docstring for the two silent
        failures that removes.
        """
        try:
            return AuditFacade.run_or_raise(
                document_id,
                triggered_by=triggered_by,
                force_rerun=force_rerun,
                dry_run=dry_run,
            )
        except AuditFacadeError as exc:
            # A refusal: bad input, missing document, no organisation. The
            # message is written for a person.
            logger.warning("[facade] refused document=%s: %s", document_id, exc)
            return AuditRunResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            # A pipeline fault. Logged with a traceback because "the audit did
            # not run" is useless without knowing why, and returned rather than
            # raised so every caller handles it the same way.
            logger.exception("[facade] pipeline failed for document=%s", document_id)
            return AuditRunResult(
                ok=False,
                error=f"The audit could not be completed ({type(exc).__name__}).",
            )

    @staticmethod
    def run_or_raise(
        document_id: UUID | str,
        *,
        triggered_by: TriggerSource = "upload",
        force_rerun: bool = False,
        dry_run: bool = False,
    ) -> AuditRunResult:
        """As `process_document`, but lets exceptions out.

        For a Celery task that wants the retry machinery to see the failure,
        and for tests that would otherwise assert on a swallowed error.
        """
        from apps.documents.models import Document
        from apps.rule_engine.pipeline.v2.pipeline import AuditPipelineV2

        document = (
            Document.objects
            .select_related("organization")
            .filter(pk=document_id)
            .first()
        )
        if document is None:
            raise AuditFacadeError(f"No document with id {document_id}.")

        if document.organization_id is None:
            # Not a crash waiting to happen — an audit with no tenant has
            # nowhere to write its findings and no quota to consume.
            raise AuditFacadeError(
                f"Document {document_id} belongs to no organization; there is "
                f"nothing to audit it against."
            )

        if not document.document_type:
            raise AuditFacadeError(
                f"Document {document_id} has no document_type. Auditing it "
                f"would apply whichever ruleset the caller guessed."
            )

        logger.info(
            "[facade] auditing document=%s type=%s org=%s trigger=%s",
            document.pk, document.document_type, document.organization_id, triggered_by,
        )

        # atomic so a stage that fails halfway does not leave a half-written
        # AuditRun that later reads as a completed audit with missing results.
        with transaction.atomic():
            audit_run = AuditPipelineV2().run(
                document_id=str(document.pk),
                document_type=document.document_type,
                organization_id=str(document.organization_id),
                triggered_by=triggered_by,
                force_rerun=force_rerun,
                dry_run=dry_run,
            )

        return AuditFacade._to_result(audit_run, triggered_by=triggered_by,
                                      force_rerun=force_rerun)

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _to_result(audit_run, *, triggered_by: str, force_rerun: bool) -> AuditRunResult:
        """Translate an AuditRun into the facade's own result type.

        Deliberately not returning the model. A caller handed an AuditRun can
        save it, mutate it, or follow a relation the facade never meant to
        expose — and then the facade is not a boundary, it is a suggestion.
        """
        reused = (
            not force_rerun
            and triggered_by != "reprocess"
            and getattr(audit_run, "status", "") == "completed"
        )

        return AuditRunResult(
            ok=audit_run.status in ("completed", "partial"),
            audit_run_id=str(audit_run.id),
            status=audit_run.status,
            risk_score=float(audit_run.risk_score) if audit_run.risk_score is not None else None,
            risk_level=audit_run.risk_level or "",
            total_rules=audit_run.total_rules or 0,
            failed_rules=audit_run.failed_rules or 0,
            warning_rules=audit_run.warning_rules or 0,
            reused_existing=reused,
            error="" if audit_run.status != "failed" else "The pipeline reported a failed run.",
        )
