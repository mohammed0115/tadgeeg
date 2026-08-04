"""Retrieval over the standards corpus — and the refusal that makes it safe.

The one property that matters more than ranking quality: with no corpus loaded,
this must return nothing and say why. A retrieval layer that quietly falls back
to the model's own recollection of what article 53 says produces a fluent
citation of a passage nobody has read, attached to an audit finding, in front
of a regulator. Every other test here is about retrieval being *explainable*,
which is the second-order version of the same requirement.
"""

import pytest

from apps.audit.services.standards_retrieval import (
    Passage,
    StandardsRetriever,
    normalize,
    tokenize,
)


ZATCA = [
    Passage(standard="ZATCA-ER", reference="المادة 53",
            text="يجب أن تتضمن الفاتورة الضريبية رقم التسجيل الضريبي للمورد وتاريخ الإصدار.",
            source_uri="https://zatca.gov.sa/ar/RulesRegulations"),
    Passage(standard="ZATCA-ER", reference="المادة 54",
            text="تحتفظ المنشأة بالفواتير الضريبية مدة لا تقل عن ست سنوات من نهاية الفترة الضريبية.",
            source_uri="https://zatca.gov.sa/ar/RulesRegulations"),
    Passage(standard="IAS-7", reference="§15",
            text="Cash flows from operating activities are primarily derived from the principal "
                 "revenue-producing activities of the entity.",
            source_uri="https://www.ifrs.org/"),
]


# ── The refusal ──────────────────────────────────────────────────────────────

def test_an_empty_corpus_returns_nothing_and_says_why():
    """THE safety property. Silence here would become a fabricated citation."""
    result = StandardsRetriever([]).search("الرقم الضريبي")

    assert result.available is False
    assert result.passages == []
    assert "No standards corpus is loaded" in result.reason


def test_a_query_with_no_match_is_refused_rather_than_answered_loosely():
    result = StandardsRetriever(ZATCA).search("زرافات في الميزانية العمومية")

    assert result.available is False
    assert "No passage" in result.reason


def test_an_empty_query_is_refused():
    assert StandardsRetriever(ZATCA).search("   ").available is False


# ── Arabic normalisation ─────────────────────────────────────────────────────

def test_hamza_and_taa_marbuta_variants_are_folded():
    """Legal texts mix أ/ا and ة/ه freely; a citation typed one way must find a
    corpus spelled the other, or retrieval misses on the commonest words."""
    assert normalize("الماده") == normalize("المادة")
    assert normalize("إصدار") == normalize("اصدار")
    assert normalize("علي") == normalize("على")


def test_diacritics_do_not_prevent_a_match():
    published = "يَجِبُ أَنْ تَتَضَمَّنَ الفَاتُورَةُ"
    assert "يجب" in tokenize(published)


def test_a_query_spelled_with_variants_still_retrieves():
    result = StandardsRetriever(ZATCA).search("الماده 53 رقم التسجيل الضريبي")

    assert result.available is True
    assert result.passages[0].reference == "المادة 53"


# ── Ranking ──────────────────────────────────────────────────────────────────

def test_the_most_relevant_passage_ranks_first():
    result = StandardsRetriever(ZATCA).search("مدة الاحتفاظ بالفواتير ست سنوات")

    assert result.passages[0].reference == "المادة 54"


def test_results_are_limited():
    result = StandardsRetriever(ZATCA).search("الفاتورة الضريبية", limit=1)
    assert len(result.passages) == 1


def test_english_and_arabic_passages_coexist_in_one_corpus():
    result = StandardsRetriever(ZATCA).search("operating activities cash flows")

    assert result.available is True
    assert result.passages[0].standard == "IAS-7"


# ── Explainability ───────────────────────────────────────────────────────────

def test_a_result_can_explain_which_terms_matched():
    """"The vector was close" is not something an auditor can take to a client."""
    retriever = StandardsRetriever(ZATCA)
    result = retriever.search("رقم التسجيل الضريبي")
    matched = retriever.explain("رقم التسجيل الضريبي", result.passages[0])

    assert matched, "no matched terms reported — the citation is unexplainable"
    assert all(term in normalize("رقم التسجيل الضريبي") for term in matched)


def test_every_passage_carries_a_citation_and_a_source():
    """A citation nobody can look up is the problem this table exists to solve."""
    result = StandardsRetriever(ZATCA).search("الفاتورة الضريبية")

    for passage in result.passages:
        assert passage.citation.strip()
        assert passage.standard
        assert passage.source_uri, "a passage with no provenance cannot be verified"


def test_the_reason_reports_the_corpus_size_behind_the_answer():
    result = StandardsRetriever(ZATCA).search("الفاتورة")
    assert "corpus of 3" in result.reason


# ── The model side ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_loading_from_an_empty_database_is_a_refusal_not_a_crash():
    retriever = StandardsRetriever.from_database()
    assert retriever.search("anything").available is False


@pytest.mark.django_db
def test_a_standard_and_reference_pair_is_unique():
    """The same article ingested twice would be returned twice and double-count
    in the ranking."""
    from django.db.utils import IntegrityError

    from apps.audit.models import StandardPassage

    StandardPassage.objects.create(standard="ZATCA-ER", reference="المادة 53", text="أ")
    with pytest.raises(IntegrityError):
        StandardPassage.objects.create(standard="ZATCA-ER", reference="المادة 53", text="ب")


@pytest.mark.django_db
def test_ingested_passages_are_retrievable():
    from apps.audit.models import StandardPassage

    StandardPassage.objects.create(
        standard="ZATCA-ER", reference="المادة 53",
        text="يجب أن تتضمن الفاتورة الضريبية رقم التسجيل الضريبي للمورد.",
        source_uri="https://zatca.gov.sa/",
    )

    result = StandardsRetriever.from_database(standard="ZATCA-ER").search("رقم التسجيل الضريبي")

    assert result.available is True
    assert result.passages[0].reference == "المادة 53"
