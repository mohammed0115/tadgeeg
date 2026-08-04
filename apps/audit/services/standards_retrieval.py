"""Retrieval over the standards texts — ZATCA, SOCPA, IFRS/IAS.

**Why the corpus is not in this repository.** A finding that says «مخالفة للمادة
٥٣ من اللائحة التنفيذية» is only useful if article 53 says what the citation
claims. I cannot supply those texts: writing plausible regulatory prose would
produce a system that cites confidently and wrongly, which is worse for an
audit product than one that cites nothing. So this module is the retrieval
side, and the corpus is loaded from documents the operator provides.

**Why keyword retrieval and not embeddings.** Two reasons, both about this
domain rather than about effort. Arabic regulatory text is highly templated —
matching «المادة ٥٣» matters more than matching a paraphrase — and an auditor
challenged on a citation has to be able to see *why* a passage was returned.
BM25-style scoring can be explained in a sentence; a cosine distance over an
opaque embedding cannot. When a labelled evaluation set exists (see the
validation harness in apps/auditing/models.py) the two can be compared on
measured retrieval quality rather than on which sounds more modern.

**The refusal is the safety property.** With no corpus loaded, `search()`
returns nothing and says so. It never falls back to the model's own memory of
what a standard says — that is precisely the failure mode this design exists to
prevent, and `test_standards_retrieval.py` pins it.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger("audit.standards")

#: Arabic and Latin word characters. Arabic diacritics are stripped separately.
_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)

#: Harakat and tatweel — present in some published texts, absent in others, and
#: never meaningful for matching.
_DIACRITICS = re.compile(r"[ؗ-ًؚ-ْـ]")


def normalize(text: str) -> str:
    """Fold the orthographic variants that Arabic legal text mixes freely.

    أ/إ/آ → ا and ة → ه and ى → ي: a citation typed «الماده» must find a corpus
    that spells it «المادة». Without this, retrieval silently misses on the
    most common words in the corpus.
    """
    text = _DIACRITICS.sub("", text or "")
    for variants, canonical in (("أإآٱ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        for ch in variants:
            text = text.replace(ch, canonical)
    return text.lower()


def tokenize(text: str) -> list:
    return _TOKEN.findall(normalize(text))


@dataclass
class Passage:
    """One citable unit — an article, a paragraph, a clause."""

    standard: str = ""      # "ZATCA-ER" | "IAS-7" | "ISA-315" …
    reference: str = ""     # "المادة 53" | "§15"
    text: str = ""
    source_uri: str = ""    # where the operator got it, for verification

    @property
    def citation(self) -> str:
        return f"{self.standard} — {self.reference}" if self.reference else self.standard


@dataclass
class RetrievalResult:
    passages: list = field(default_factory=list)
    reason: str = ""

    @property
    def available(self) -> bool:
        return bool(self.passages)


class StandardsRetriever:
    """BM25-ish scoring over a corpus supplied at load time."""

    K1 = 1.5
    B = 0.75

    def __init__(self, passages=None):
        self.passages = list(passages or [])
        self._tokens = [tokenize(p.text) for p in self.passages]
        self._lengths = [len(t) for t in self._tokens]
        self._avg_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._df = Counter()
        for tokens in self._tokens:
            for term in set(tokens):
                self._df[term] += 1

    @classmethod
    def from_database(cls, *, standard: str = ""):
        """Load whatever the operator has ingested. Empty is a valid state."""
        try:
            from apps.audit.models import StandardPassage
        except Exception:  # pragma: no cover - model not migrated yet
            return cls([])

        queryset = StandardPassage.objects.all()
        if standard:
            queryset = queryset.filter(standard=standard)
        return cls([
            Passage(standard=row.standard, reference=row.reference,
                    text=row.text, source_uri=row.source_uri)
            for row in queryset
        ])

    def search(self, query: str, *, limit: int = 3) -> RetrievalResult:
        """Passages that best match `query`, or an explicit refusal.

        The refusal matters more than the ranking. A caller that receives an
        empty result must NOT proceed to answer from the model's own memory of
        the standard: that produces a fluent citation of an article nobody has
        read, attached to an audit finding.
        """
        if not self.passages:
            return RetrievalResult(reason=(
                "No standards corpus is loaded. Ingest the ZATCA / SOCPA / IFRS "
                "texts before citing them; answering without a source would "
                "produce citations nobody can verify."
            ))

        terms = tokenize(query)
        if not terms:
            return RetrievalResult(reason="Empty query.")

        total = len(self.passages)
        scored = []
        for index, tokens in enumerate(self._tokens):
            counts = Counter(tokens)
            length = self._lengths[index] or 1
            score = 0.0
            for term in terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                # Standard BM25 idf, floored at zero so a term appearing in
                # every passage contributes nothing rather than going negative
                # and pushing genuinely relevant passages down the list.
                idf = max(0.0, math.log(1 + (total - self._df[term] + 0.5) / (self._df[term] + 0.5)))
                denominator = frequency + self.K1 * (
                    1 - self.B + self.B * length / (self._avg_length or 1)
                )
                score += idf * (frequency * (self.K1 + 1)) / denominator
            if score > 0:
                scored.append((score, index))

        if not scored:
            return RetrievalResult(reason="No passage in the loaded corpus matches this query.")

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return RetrievalResult(
            passages=[self.passages[index] for _, index in scored[:limit]],
            reason=f"{len(scored)} matching passages in a corpus of {total}.",
        )

    def explain(self, query: str, passage: Passage) -> list:
        """Which query terms this passage matched.

        An auditor challenged on a citation needs to see why it surfaced, and
        "the vector was close" is not an answer they can take to a client.
        """
        passage_terms = set(tokenize(passage.text))
        return [term for term in dict.fromkeys(tokenize(query)) if term in passage_terms]
