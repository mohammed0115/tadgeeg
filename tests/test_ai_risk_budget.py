from unittest.mock import patch

from django.test import override_settings

from core.services import ai_budget
from core.services.ai_budget import org_context
from core.services.invoice_ai_service import analyze_invoice_risk


@override_settings(OPENAI_API_KEY="test-key")
def test_risk_analysis_stops_before_provider_when_org_budget_is_exhausted():
    exhausted = ai_budget.BudgetExceeded("org-1", 2000, 1000)
    with org_context("org-1"), patch(
        "core.services.ai_budget.guard_current", side_effect=exhausted
    ), patch("openai.OpenAI") as openai:
        result = analyze_invoice_risk({"invoice_number": "INV-1"})

    assert result["error"] == "AI budget exceeded"
    openai.assert_not_called()
