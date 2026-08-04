"""The platform must narrate when OpenAI cannot, and must say when it did.

Before this there was no fallback anywhere: every call assumed OpenAI answered,
so an OpenAI outage was a Tadgeeg outage for anything that narrates.

Two properties matter more than which provider wins. First, the chain has no
failure path — the template tier is always available, so callers need no
`except`. Second, degradation is *declared*: a template paragraph presented as
though a model wrote it is the same misrepresentation as a cached number
presented as live, and this codebase has now removed that pattern three times.
"""

from unittest import mock

import pytest

from core.ai.providers import (
    AIProvider,
    LocalModelProvider,
    Narrative,
    NarrativeService,
    OpenAIProvider,
    TemplateProvider,
)

EVIDENCE = {
    "totals": {"total_rules": 30, "failed_rules": 2},
    "findings": [
        {"rule_code": "VAT-002", "passed": False, "severity": "critical",
         "field": "vat_amount", "actual": 99.0, "expected": "15.0 (= 100.0 × 15%)"},
        {"rule_code": "INV-003", "passed": False, "severity": "low",
         "field": "vendor_name", "actual": "", "expected": "قيمة غير فارغة"},
        {"rule_code": "INV-001", "passed": True, "severity": "info"},
    ],
}


class _Broken(AIProvider):
    name = "broken"

    def is_available(self):
        return True

    def narrate(self, evidence, *, language="ar"):
        raise RuntimeError("upstream is down")


# ── The floor ────────────────────────────────────────────────────────────────

def test_the_template_provider_is_always_available():
    """The property the whole chain rests on."""
    assert TemplateProvider().is_available() is True


def test_the_chain_never_fails_even_when_everything_upstream_does():
    service = NarrativeService(providers=[_Broken(), _Broken(), TemplateProvider()])
    narrative = service.narrate(EVIDENCE)

    assert narrative.text
    assert narrative.provider == "template"


def test_a_template_narrative_invents_no_figure():
    """Structurally, not by instruction: every number is copied from a finding.

    This is why the fallback is not a consolation prize. A generated paragraph
    reads better and can be wrong in ways nobody catches; this one cannot
    contain a figure that no rule produced.
    """
    text = TemplateProvider().narrate(EVIDENCE).text

    assert "99.0" in text and "vat_amount" in text
    assert "30" in text and "2" in text


def test_findings_are_ordered_by_severity():
    """A narrative that opens with a low-severity note buries the critical one."""
    text = TemplateProvider().narrate(EVIDENCE).text
    assert text.index("VAT-002") < text.index("INV-003")


def test_passing_rules_do_not_appear_as_findings():
    assert "INV-001" not in TemplateProvider().narrate(EVIDENCE).text


def test_a_clean_document_says_so():
    clean = {"totals": {"total_rules": 30, "failed_rules": 0}, "findings": []}
    text = TemplateProvider().narrate(clean).text
    assert "لم تُخفق" in text or "No rule failed" in text


# ── Degradation is declared ──────────────────────────────────────────────────

def test_a_fallback_is_marked_degraded_and_names_what_failed():
    """"The AI is broken" is unactionable. "openai failed, served the template"
    is a decision."""
    service = NarrativeService(providers=[_Broken(), TemplateProvider()])
    narrative = service.narrate(EVIDENCE)

    assert narrative.degraded is True
    assert any("broken" in w for w in narrative.warnings)


def test_a_first_choice_success_is_not_marked_degraded():
    class _Fine(AIProvider):
        name = "fine"

        def is_available(self):
            return True

        def narrate(self, evidence, *, language="ar"):
            return Narrative(text="ملخّص.", provider=self.name)

    narrative = NarrativeService(providers=[_Fine(), TemplateProvider()]).narrate(EVIDENCE)
    assert narrative.degraded is False


def test_template_output_declares_that_it_was_not_generated():
    """A reader who cannot tell assumes the more impressive answer."""
    narrative = TemplateProvider().narrate(EVIDENCE)

    assert narrative.is_generated is False
    assert narrative.warnings


def test_an_empty_model_answer_counts_as_a_failure(settings):
    """An empty string is not a narrative — storing it would leave a blank
    paragraph where an explanation should be."""
    settings.OPENAI_API_KEY = "sk-test"
    with mock.patch("core.services.ai_service.generate_audit_narrative",
                    return_value={"narrative": "   "}):
        with pytest.raises(RuntimeError, match="empty"):
            OpenAIProvider().narrate(EVIDENCE)


# ── Availability checks are cheap ────────────────────────────────────────────

def test_openai_availability_is_a_settings_check_not_a_network_call(settings):
    settings.OPENAI_API_KEY = ""
    assert OpenAIProvider().is_available() is False
    settings.OPENAI_API_KEY = "sk-test"
    assert OpenAIProvider().is_available() is True


def test_the_local_provider_is_off_unless_configured(settings):
    """Nothing here runs by accident — a local model is a deployment decision."""
    settings.LOCAL_LLM_ENDPOINT = ""
    assert LocalModelProvider().is_available() is False


def test_an_unavailable_provider_is_skipped_without_being_called(settings):
    settings.OPENAI_API_KEY = ""
    with mock.patch("core.services.ai_service.generate_audit_narrative") as generate:
        NarrativeService().narrate(EVIDENCE)
    generate.assert_not_called()


# ── The local provider still goes through the SSRF guard ────────────────────

def test_the_local_endpoint_is_checked_against_the_outbound_guard(settings):
    """Operator-configured is not the same as safe: this call is made
    server-side, so it faces the same guard as any other outbound request."""
    settings.LOCAL_LLM_ENDPOINT = "http://169.254.169.254"

    with pytest.raises(Exception):
        LocalModelProvider().narrate(EVIDENCE)


# ── Default chain ────────────────────────────────────────────────────────────

def test_the_default_chain_ends_in_the_template():
    providers = NarrativeService().providers

    assert isinstance(providers[-1], TemplateProvider), (
        "the last provider must be the one that cannot fail"
    )
    assert [p.name for p in providers] == ["openai", "local", "template"]


def test_callers_depend_on_the_port_not_on_openai():
    """Dependency inversion, asserted: the module must not import the SDK."""
    import inspect

    import core.ai.providers as module

    source = inspect.getsource(module)
    top_level = [
        line for line in source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    assert not any("openai" in line for line in top_level), (
        "core.ai.providers imports openai at module level — the point of the "
        "port is that it does not"
    )
