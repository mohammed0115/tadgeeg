"""Where narrative text comes from, and what happens when it cannot.

**The requirement.** The platform must keep working when OpenAI is unreachable
— rate-limited, key rotated, network partitioned, or simply down. Today every
call assumes success: there is no fallback anywhere, so an OpenAI outage is a
Tadgeeg outage for anything that narrates.

**What a local LLM would actually cost here, measured.** The production image
is 2.81 GB. `torch` adds ~2.5 GB installed; a 7B model quantised to Q4 adds ~4
GB on disk and needs ~5 GB of RAM while generating. Your host runs live, dev
and test side by side, each with a web container, a celery worker, MySQL and
Redis. On CPU, a 7B model produces an Arabic paragraph in roughly 30–120
seconds against OpenAI's 2.

So a local transformer is not a fallback, it is an outage with extra steps: a
user waiting ninety seconds for a worse paragraph is worse served than one told
plainly that the narrative is unavailable. And a small model that hallucinates
a figure into an audit narrative is worse than either — this product's entire
argument is that its numbers can be defended.

**What this module does instead.** Three tiers, tried in order:

  1. `OpenAIProvider`     — the good one, when it answers
  2. `LocalModelProvider` — opt-in, off by default, for anyone who does have
                            the hardware. The port exists so adding it is
                            configuration, not a rewrite.
  3. `TemplateProvider`   — deterministic, instant, zero dependencies, and
                            **always available**

Tier 3 is the important one and it is not a consolation prize. The rule engine
already produces structured evidence for every finding — field, actual value,
expected value — so a narrative assembled from that is *more* defensible than a
generated one: it cannot invent a number, and every sentence traces to a rule.
It is worse prose and better evidence.

**Dependency inversion.** Callers depend on `AIProvider`, never on `openai`.
Adding a provider means adding a class; the four modules that currently import
`openai` directly can migrate one at a time.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger("core.ai.providers")


@dataclass(frozen=True)
class Narrative:
    """Generated text, plus where it came from.

    `provider` and `is_generated` are not metadata for logs — they belong on
    screen. A template-assembled paragraph and a model-written one carry
    different weight in a workpaper, and a reader who cannot tell which they
    are looking at will assume the more impressive one.
    """

    text: str
    provider: str
    #: False when assembled deterministically from rule evidence. Such text
    #: cannot contain an invented figure, which is a property worth exposing.
    is_generated: bool = True
    language: str = "ar"
    degraded: bool = False
    warnings: tuple = field(default_factory=tuple)


class AIProvider(ABC):
    """A source of narrative text.

    Deliberately narrow. A port with one method is a port callers can reason
    about; one with `chat()`, `embed()`, `classify()` and `summarise()` becomes
    a second SDK that every implementation must fake.
    """

    name: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap check. Must not make a network call — this runs on the hot path."""

    @abstractmethod
    def narrate(self, evidence: dict, *, language: str = "ar") -> Narrative:
        """Turn structured audit evidence into prose."""


class OpenAIProvider(AIProvider):
    """The primary provider."""

    name = "openai"

    def is_available(self) -> bool:
        return bool(getattr(settings, "OPENAI_API_KEY", ""))

    def narrate(self, evidence: dict, *, language: str = "ar") -> Narrative:
        from core.services.ai_service import generate_audit_narrative

        result = generate_audit_narrative(evidence, language=language)
        text = (result or {}).get("narrative") or (result or {}).get("summary") or ""
        if not text.strip():
            # An empty answer is a failure, not a narrative. Raising lets the
            # chain fall through instead of storing a blank paragraph.
            raise RuntimeError("OpenAI returned an empty narrative")
        return Narrative(text=text, provider=self.name, language=language)


class LocalModelProvider(AIProvider):
    """A locally hosted model. Off unless deliberately configured.

    `is_available()` returns False when `LOCAL_LLM_ENDPOINT` is unset, which is
    the default, so nothing here runs by accident. It speaks to an
    OpenAI-compatible HTTP endpoint (llama.cpp server, Ollama, vLLM, LM Studio)
    rather than loading weights in-process: a model loaded inside gunicorn
    holds its memory for the life of the worker and turns three workers into
    fifteen gigabytes of resident RAM.

    Running it as a separate service also means it can live on different
    hardware from the web tier, which is the only arrangement that makes a
    local model practical on a host already carrying three environments.
    """

    name = "local"

    @property
    def endpoint(self) -> str:
        return getattr(settings, "LOCAL_LLM_ENDPOINT", "") or ""

    def is_available(self) -> bool:
        return bool(self.endpoint)

    def narrate(self, evidence: dict, *, language: str = "ar") -> Narrative:
        import json

        import requests

        from core.security.outbound_guard import assert_outbound_allowed

        # The endpoint is operator-configured, but "operator-configured" is not
        # the same as safe: this runs server-side, so it goes through the same
        # SSRF guard as any other outbound call.
        assert_outbound_allowed(self.endpoint)

        prompt = TemplateProvider().narrate(evidence, language=language).text
        # timeout is passed below from LOCAL_LLM_TIMEOUT.
        response = requests.post(  # nosec B113
            f"{self.endpoint.rstrip('/')}/v1/chat/completions",
            json={
                "model": getattr(settings, "LOCAL_LLM_MODEL", "local"),
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT_AR if language == "ar" else _SYSTEM_PROMPT_EN},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 600,
            },
            timeout=getattr(settings, "LOCAL_LLM_TIMEOUT", 45),
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"].strip()
        if not text:
            raise RuntimeError("local model returned an empty narrative")

        return Narrative(
            text=text,
            provider=self.name,
            language=language,
            warnings=("Generated by a local model — verify figures against the findings table.",),
        )


class TemplateProvider(AIProvider):
    """Deterministic narrative assembled from the rule evidence itself.

    Always available, instant, no dependencies, and structurally incapable of
    inventing a figure: every number in the output came out of a rule result.

    For an audit product that is not a downgrade in the way it first appears.
    A generated paragraph reads better and can be wrong in ways nobody catches;
    this one reads plainly and every sentence traces to a rule code. When the
    other two tiers are unavailable, this is what an auditor should see.
    """

    name = "template"

    def is_available(self) -> bool:
        return True

    def narrate(self, evidence: dict, *, language: str = "ar") -> Narrative:
        findings = evidence.get("findings") or []
        totals = evidence.get("totals") or {}
        arabic = language.startswith("ar")

        lines: list[str] = []

        checked = totals.get("total_rules") or len(findings)
        failed = totals.get("failed_rules") or sum(
            1 for f in findings if not f.get("passed", True)
        )

        if arabic:
            lines.append(f"فُحص {checked} بندًا، وأخفق منها {failed}.")
        else:
            lines.append(f"{checked} checks were applied; {failed} failed.")

        # Ordered by severity, because a narrative that opens with a low-severity
        # formatting note buries the one that matters.
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        ranked = sorted(
            (f for f in findings if not f.get("passed", True)),
            key=lambda f: order.get(str(f.get("severity", "")).lower(), 9),
        )

        for finding in ranked[:8]:
            code = finding.get("rule_code") or finding.get("code") or "—"
            field_name = finding.get("field")
            actual = finding.get("actual")
            expected = finding.get("expected")
            message = finding.get("message") or finding.get("description") or ""

            # The structured evidence path — a sentence nobody can dispute the
            # provenance of, because each part came from the rule result.
            if field_name and expected is not None:
                if arabic:
                    lines.append(
                        f"• [{code}] الحقل «{field_name}»: القيمة {actual!s} "
                        f"والمتوقَّع {expected!s}."
                    )
                else:
                    lines.append(
                        f"• [{code}] {field_name}: found {actual!s}, expected {expected!s}."
                    )
            elif message:
                lines.append(f"• [{code}] {message}")

        if len(ranked) > 8:
            remaining = len(ranked) - 8
            lines.append(
                f"وبقيت {remaining} ملاحظة أخرى في الجدول." if arabic
                else f"{remaining} further findings are listed in the table."
            )

        if not ranked:
            lines.append(
                "لم تُخفق أي قاعدة على هذا المستند." if arabic
                else "No rule failed on this document."
            )

        note = (
            "هذا النصّ مُجمَّع آليًّا من نتائج القواعد، لا مولَّد بنموذج لغوي — "
            "كل رقم فيه مأخوذ من نتيجة قاعدة."
            if arabic else
            "Assembled from rule results rather than generated by a language "
            "model — every figure here came from a rule result."
        )

        return Narrative(
            text="\n".join(lines),
            provider=self.name,
            is_generated=False,
            language=language,
            warnings=(note,),
        )


_SYSTEM_PROMPT_AR = (
    "أنت مساعد تدقيق مالي. اكتب فقرة موجزة بالعربية الفصحى تلخّص نتائج التدقيق "
    "أدناه. لا تخترع أي رقم لم يرد في النصّ. لا تُصدر رأيًا تدقيقيًّا."
)
_SYSTEM_PROMPT_EN = (
    "You are a financial audit assistant. Write a short paragraph summarising "
    "the audit results below. Do not invent any figure that is not in the text. "
    "Do not issue an audit opinion."
)


class NarrativeService:
    """Tries each provider in order and never fails.

    The chain is the whole design: a narrative is a nice-to-have, and taking
    the audit down because a third party is rate-limiting is the wrong trade.
    `TemplateProvider` is last and always available, so this method has no
    failure path — which is why callers do not need one either.
    """

    def __init__(self, providers: list[AIProvider] | None = None):
        self.providers = providers or [
            OpenAIProvider(),
            LocalModelProvider(),
            TemplateProvider(),
        ]

    def narrate(self, evidence: dict, *, language: str = "ar") -> Narrative:
        attempted: list[str] = []

        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                narrative = provider.narrate(evidence, language=language)
            except Exception as exc:  # noqa: BLE001
                # Every provider failure is logged with its name. "The AI is
                # broken" is unactionable; "openai timed out, local refused,
                # served the template" is a decision.
                logger.warning("[narrative] %s failed: %s", provider.name, exc)
                attempted.append(provider.name)
                continue

            if attempted:
                # Degraded, and it says so. A template paragraph presented as
                # though the model wrote it is the same misrepresentation as a
                # cached number presented as live.
                narrative = Narrative(
                    text=narrative.text,
                    provider=narrative.provider,
                    is_generated=narrative.is_generated,
                    language=narrative.language,
                    degraded=True,
                    warnings=narrative.warnings + (
                        f"Primary provider(s) unavailable: {', '.join(attempted)}.",
                    ),
                )
            return narrative

        # Unreachable while TemplateProvider is in the chain — kept because a
        # future edit could remove it, and an empty narrative is better than an
        # AttributeError on a page an auditor is reading.
        logger.error("[narrative] every provider failed or was unavailable")
        return Narrative(
            text="", provider="none", is_generated=False,
            language=language, degraded=True,
            warnings=("No narrative provider was available.",),
        )
