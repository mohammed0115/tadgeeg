"""From a `Document` to the typed record the audit pipeline needs.

**Why this exists.** `run_audit_compat(document_id, document_type)` does not
take a `Document` primary key. `document_id` is the primary key of the *typed*
record — the normalizer for `document_type` looks it up directly:

    # apps/rule_engine/normalizers/purchase_order_normalizer.py
    po = PurchaseOrder.objects.get(id=document_id)

Two id spaces, and passing one where the other is expected does not raise.
`apps/audit/tasks.py` passed a `Document` key with `document_type="sales_invoice"`;
the intersection of the two key spaces is empty, so `Invoice.DoesNotExist` fired,
the normalizer logged a warning and returned an EMPTY `NormalizedDocument`, and
the pipeline audited nothing and recorded an `AuditRun` for it. Measured:
`typed_data == {}`, no exception, while `document.purchaseorder` had 15 fields
waiting.

**Why the map is computed.** Every defect in this repository grew from a
hand-written list read as truth: the `Callers:` header, `testpaths`,
`requirements.lock`, "30 rules". So neither half of this map is written here:

  * which typed records a `Document` can have — read from the 20 reverse
    one-to-one relations Django already knows about;
  * what each typed model is called in the pipeline — read from the normalizer
    registry, by looking at which model each registered normalizer queries.

Name derivation is deliberately NOT used: it matches 15 of 20, and fails on
ExpenseReport → `expense`, GoodsReceiptNote → `grn`, PaymentVoucher →
`payment`, PayrollSheet → `payroll`, and VATReturn — which derives to
`v_a_t_return`.

`sales_invoice` IS in the map — it normalizes `invoices.Invoice` — and it never
takes part in resolution anyway, because `Invoice` is not among Django's
reverse relations on `Document`. `typed_accessors()` is what resolution walks,
and `Invoice` cannot appear there. The invoices path is not this module's
business and stays untouched by it.

(An earlier draft of this docstring claimed the map excluded `Invoice`. It did
not; the claim came from a narrower AST probe that matched `X.objects.get(...)`
and missed `Invoice.objects.select_related(...).get(...)`. A comment asserting
something the code contradicts is the exact defect this file exists to stop
repeating, so it is corrected here rather than quietly dropped.)
"""

from __future__ import annotations

import ast
import inspect
import logging
import textwrap
from functools import lru_cache

logger = logging.getLogger("finai")


class DocumentResolutionError(Exception):
    """Base for every failure to name what a Document actually is."""


class UnresolvedDocument(DocumentResolutionError):
    """No typed record hangs off this Document.

    Raised, never swallowed. A Document with no typed record has nothing for a
    normalizer to read, and auditing it produces an empty run that looks like a
    completed audit — which is the defect this module exists to end.
    """


class AmbiguousDocument(DocumentResolutionError):
    """More than one typed record hangs off this Document.

    The relations are one-to-one, so this should be impossible; if it happens
    the data is telling us something that the schema says cannot be true, and
    guessing which record to audit would bury it.
    """


def _model_queried_by(normalizer_class) -> set[str]:
    """The model names a normalizer's `normalize()` reads, via `ast`.

    Matches `<Model>.objects` anywhere in the method, so both
    `X.objects.get(...)` and `X.objects.select_related(...).get(...)` are seen.
    """
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(normalizer_class.normalize)))
    except (OSError, TypeError, SyntaxError):  # pragma: no cover - defensive
        return set()
    return {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "objects"
        and isinstance(node.value, ast.Name)
    }


@lru_cache(maxsize=1)
def typed_model_to_document_type() -> dict[str, str]:
    """`{"PurchaseOrder": "purchase_order", "VATReturn": "tax_return", ...}`

    Built from the normalizer registry, not written down. A normalizer that
    queries no model, or more than one, is left out rather than guessed at.
    """
    from apps.rule_engine.normalizers import DocumentNormalizerFactory

    mapping: dict[str, str] = {}
    for document_type, normalizer_class in DocumentNormalizerFactory._registry.items():
        models = _model_queried_by(normalizer_class)
        if len(models) != 1:
            logger.debug(
                "[resolution] normalizer %r queries %s — not mapped",
                document_type, sorted(models) or "nothing",
            )
            continue
        mapping[models.pop()] = document_type
    return mapping


@lru_cache(maxsize=1)
def typed_accessors() -> tuple[tuple[str, str], ...]:
    """`(("purchaseorder", "PurchaseOrder"), ...)` for every typed record a
    Document can carry.

    Read from Django's own reverse one-to-one relations. `ExtractedData` and
    `DocumentAnalysisResult` are excluded by the same rule that includes the
    rest: they are not in the normalizer map, because they are not document
    types.
    """
    from apps.documents.models import Document

    known = typed_model_to_document_type()
    return tuple(
        (field.get_accessor_name(), field.related_model.__name__)
        for field in Document._meta.get_fields()
        if field.auto_created
        and not field.concrete
        and field.one_to_one
        and field.related_model.__name__ in known
    )


def resolve(document):
    """Return `(typed_record, document_type)` for a `Document`.

    The pair `run_audit_compat` actually needs: a primary key its normalizer
    can find, and the name that selects that normalizer.

    Raises `UnresolvedDocument` or `AmbiguousDocument`. It does not return a
    default, and it does not fall back to the `Document` key — returning
    something plausible is exactly how the empty-audit defect stayed invisible.
    """
    mapping = typed_model_to_document_type()
    found = []
    for accessor, model_name in typed_accessors():
        try:
            record = getattr(document, accessor, None)
        except Exception:          # the reverse accessor raises when absent
            record = None
        if record is not None:
            found.append((record, mapping[model_name], model_name))

    if not found:
        raise UnresolvedDocument(
            f"Document {document.pk} (stored type {document.document_type!r}) "
            f"has no typed record. Checked "
            f"{len(typed_accessors())} relations. Auditing it would read an "
            f"empty document and record the result as a completed audit."
        )
    if len(found) > 1:
        raise AmbiguousDocument(
            f"Document {document.pk} carries {len(found)} typed records: "
            f"{sorted(name for _, _, name in found)}. The relations are "
            f"one-to-one, so this contradicts the schema."
        )

    record, document_type, _ = found[0]
    return record, document_type
