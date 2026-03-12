"""
AI Service — OpenAI-powered financial intelligence:
  - Anomaly detection & fraud scoring
  - Natural language query translation
  - Financial insights generation
  - Audit narrative generation
  - Compliance checking
"""

import json
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger("finai")


def _get_client():
    """Get OpenAI client instance."""
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat(messages: list, json_mode: bool = True, temperature: float = 0) -> str:
    """Single helper to call OpenAI chat completion."""
    client = _get_client()
    kwargs = {
        "model": settings.OPENAI_MODEL,
        "messages": messages,
        "max_tokens": settings.OPENAI_MAX_TOKENS,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


# ─── Anomaly Detection ─────────────────────────────────────────────────────────

def detect_anomalies_ai(transactions: list[dict], historical_context: dict = None) -> dict:
    """
    Analyze a batch of transactions for anomalies using GPT.

    Args:
        transactions: List of transaction dicts (max 200 per call for token limits).
        historical_context: Optional statistics about normal patterns.

    Returns:
        dict with 'anomalies' list and 'summary'.
    """
    context_text = ""
    if historical_context:
        context_text = f"""
Historical context:
- Average transaction amount: {historical_context.get('avg_amount', 'N/A')}
- Typical transaction frequency: {historical_context.get('avg_daily_count', 'N/A')} per day
- Common vendors: {', '.join(historical_context.get('top_vendors', [])[:5])}
"""

    system_prompt = """You are an expert financial fraud detective and auditor specializing in GCC financial markets.
Analyze transactions for anomalies, fraud patterns, and audit risks.
Return ONLY a JSON object with this structure:
{
  "anomalies": [
    {
      "transaction_id": "string",
      "risk_score": 0-100,
      "severity": "low|medium|high|critical",
      "anomaly_type": "string",
      "description": "string",
      "recommendation": "string",
      "evidence": ["string"]
    }
  ],
  "summary": {
    "total_analyzed": 0,
    "anomalies_found": 0,
    "critical_count": 0,
    "high_count": 0,
    "medium_count": 0,
    "low_count": 0,
    "overall_risk_level": "low|medium|high|critical",
    "key_findings": ["string"]
  }
}"""

    # Limit transactions to prevent token overflow
    tx_sample = transactions[:150]

    user_message = f"""{context_text}

Analyze these {len(tx_sample)} transactions for anomalies.
Focus on: duplicate amounts, Benford's Law violations, round-number bias, 
unusual timing, suspicious vendors, and fraud patterns common in GCC markets
including ghost employees, fictitious invoices, and VAT manipulation.

Transactions:
{json.dumps(tx_sample, ensure_ascii=False, default=str)}"""

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"AI anomaly detection error: {e}")
        return {"anomalies": [], "summary": {"error": str(e)}, "total_analyzed": len(transactions)}


# ─── Fraud Pattern Scoring ─────────────────────────────────────────────────────

def score_fraud_risk(transaction: dict, organization_context: dict = None) -> dict:
    """
    Score a single transaction for fraud risk.

    Returns:
        dict with risk_score (0-100), risk_factors, recommendation.
    """
    system_prompt = """You are a forensic accounting expert. 
Score the fraud risk of a single financial transaction.
Return ONLY JSON:
{
  "risk_score": 0-100,
  "risk_level": "low|medium|high|critical",
  "risk_factors": ["string"],
  "fraud_patterns_detected": ["string"],
  "recommendation": "string",
  "requires_investigation": true/false,
  "confidence": 0-100
}"""

    org_info = ""
    if organization_context:
        org_info = f"Organization: {organization_context.get('name')}, Country: {organization_context.get('country')}, Industry: {organization_context.get('industry')}"

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{org_info}\n\nScore this transaction:\n{json.dumps(transaction, ensure_ascii=False, default=str)}"},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"Fraud scoring error: {e}")
        return {"risk_score": 0, "risk_level": "unknown", "error": str(e)}


# ─── Natural Language Query ────────────────────────────────────────────────────

def nl_to_django_filter(natural_query: str, available_fields: list[str]) -> dict:
    """
    Convert a natural language query to Django ORM filter kwargs.

    Args:
        natural_query: e.g. "transactions over 50000 SAR last 30 days"
        available_fields: List of model field names available.

    Returns:
        dict with 'filters', 'order_by', 'explanation'.
    """
    system_prompt = f"""You are a Django ORM expert. Convert natural language queries about financial transactions to Django filter kwargs.

Available model fields: {', '.join(available_fields)}

Return ONLY JSON:
{{
  "filters": {{"field__lookup": "value"}},
  "exclude": {{"field__lookup": "value"}},
  "order_by": ["-field"],
  "limit": 50,
  "explanation": "Human-readable description of what this query does",
  "sql_hint": "Optional raw SQL description"
}}

Use Django ORM lookups: __gte, __lte, __contains, __icontains, __in, __date, __range, __isnull, etc.
For date ranges use ISO format. For amounts use numbers (not strings).
Handle Arabic input correctly."""

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Convert to Django filter: {natural_query}"},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"NL to filter error: {e}")
        return {"filters": {}, "explanation": f"Could not parse query: {e}", "error": str(e)}


# ─── Financial Insights ────────────────────────────────────────────────────────

def generate_financial_insights(financial_data: dict, organization: dict) -> dict:
    """
    Generate AI-powered financial insights and recommendations.

    Args:
        financial_data: Summary financial KPIs, ratios, trends.
        organization: Organization metadata.

    Returns:
        dict with insights, recommendations, risk_indicators, predictions.
    """
    system_prompt = """You are a senior CFO and financial auditing expert for GCC-based organizations.
Generate actionable financial insights.
Return ONLY JSON:
{
  "executive_summary": "string (2-3 sentences)",
  "key_insights": [
    {"category": "string", "insight": "string", "impact": "positive|negative|neutral", "priority": "low|medium|high"}
  ],
  "risk_indicators": [
    {"risk": "string", "severity": "low|medium|high|critical", "recommendation": "string"}
  ],
  "recommendations": ["string"],
  "financial_health_score": 0-100,
  "compliance_notes": ["string"],
  "audit_flags": ["string"]
}"""

    country = organization.get("country", "SA")
    regulations = {
        "SA": "ZATCA, GAZT, SAMA, Saudi VAT Law",
        "AE": "FTA, UAE VAT Law, Central Bank UAE",
        "BH": "NBR, Bahrain VAT Law",
    }.get(country, "GCC financial regulations")

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
Organization: {organization.get('name')} | Country: {country} | Industry: {organization.get('industry', 'Unknown')}
Applicable regulations: {regulations}

Financial data:
{json.dumps(financial_data, ensure_ascii=False, default=str)}

Generate comprehensive financial insights and audit recommendations.
"""},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"Insights generation error: {e}")
        return {"executive_summary": "Error generating insights", "error": str(e)}


# ─── Audit Report Narrative ────────────────────────────────────────────────────

def generate_audit_narrative(audit_data: dict, language: str = "en") -> dict:
    """
    Generate professional audit report narrative in English or Arabic.

    Args:
        audit_data: Dict containing findings, anomalies, compliance issues.
        language: 'en' or 'ar'.

    Returns:
        dict with report sections as text.
    """
    lang_instruction = (
        "Write the ENTIRE response in formal Arabic (فصحى)." if language == "ar"
        else "Write in formal professional English."
    )

    system_prompt = f"""You are a certified public accountant (CPA) writing an official audit report.
{lang_instruction}
Return ONLY JSON with these sections:
{{
  "executive_summary": "string",
  "scope_and_methodology": "string",
  "key_findings": "string",
  "anomalies_section": "string",
  "compliance_section": "string",
  "recommendations": "string",
  "conclusion": "string",
  "management_response_placeholder": "string"
}}"""

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate audit report based on:\n{json.dumps(audit_data, ensure_ascii=False, default=str)}"},
        ], temperature=0.2)
        return json.loads(content)
    except Exception as e:
        logger.error(f"Audit narrative error: {e}")
        return {"executive_summary": "Report generation failed.", "error": str(e)}


# ─── Compliance Checking ──────────────────────────────────────────────────────

def check_compliance_ai(transactions: list[dict], rules: list[dict], country: str = "SA") -> dict:
    """
    Check transactions against compliance rules using AI.

    Args:
        transactions: List of transaction dicts.
        rules: List of compliance rules {'rule_id', 'description', 'standard'}.
        country: GCC country code.

    Returns:
        dict with violations and compliance_score.
    """
    country_regulations = {
        "SA": "ZATCA e-invoicing (FATOORAH), Saudi VAT 15%, GAZT requirements, IFRS as adopted in KSA",
        "AE": "FTA requirements, UAE VAT 5%, Central Bank UAE regulations",
        "BH": "NBR Bahrain, Bahrain VAT 10%",
        "KW": "Ministry of Finance Kuwait, Zakat rules",
        "OM": "OTA, Oman Income Tax",
        "QA": "GTA Qatar, no current VAT",
    }

    system_prompt = f"""You are a GCC regulatory compliance expert.
Check transactions against {country_regulations.get(country, 'GCC regulations')}.
Return ONLY JSON:
{{
  "compliance_score": 0-100,
  "violations": [
    {{
      "transaction_id": "string",
      "rule_violated": "string",
      "standard": "ZATCA|VAT|IFRS|GAAP|SAMA|INTERNAL",
      "severity": "low|medium|high|critical",
      "description": "string",
      "corrective_action": "string"
    }}
  ],
  "summary": {{
    "total_checked": 0,
    "violations_found": 0,
    "critical_violations": 0,
    "missing_vat_numbers": 0,
    "incorrect_vat_amounts": 0,
    "missing_invoices": 0
  }},
  "recommendations": ["string"]
}}"""

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
Country: {country}
Rules to check: {json.dumps(rules[:20], ensure_ascii=False)}

Transactions:
{json.dumps(transactions[:100], ensure_ascii=False, default=str)}
"""},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"Compliance check error: {e}")
        return {"compliance_score": 0, "violations": [], "error": str(e)}


# ─── Benford's Law Analysis ───────────────────────────────────────────────────

def benford_analysis(amounts: list[float]) -> dict:
    """
    Perform Benford's Law analysis on a list of amounts.
    No AI required — pure statistical analysis.

    Returns:
        dict with observed vs expected distribution and chi-square result.
    """
    import math

    if not amounts:
        return {"error": "No amounts provided"}

    # Expected Benford distribution
    expected = {str(d): math.log10(1 + 1 / d) for d in range(1, 10)}

    # Get first digits
    first_digits = []
    for a in amounts:
        s = str(abs(a)).lstrip("0").replace(".", "")
        if s and s[0].isdigit() and s[0] != "0":
            first_digits.append(s[0])

    if not first_digits:
        return {"error": "Could not extract first digits"}

    n = len(first_digits)
    observed = {str(d): first_digits.count(str(d)) / n for d in range(1, 10)}

    # Chi-square statistic
    chi_square = sum(
        n * ((observed.get(str(d), 0) - expected[str(d)]) ** 2) / expected[str(d)]
        for d in range(1, 10)
    )

    # Critical value at p=0.05, df=8 is 15.507
    passes = chi_square < 15.507

    deviations = {
        str(d): {
            "observed": round(observed.get(str(d), 0) * 100, 2),
            "expected": round(expected[str(d)] * 100, 2),
            "deviation_pct": round(abs(observed.get(str(d), 0) - expected[str(d)]) / expected[str(d)] * 100, 2),
        }
        for d in range(1, 10)
    }

    suspicious_digits = [d for d, v in deviations.items() if v["deviation_pct"] > 20]

    return {
        "sample_size": n,
        "chi_square": round(chi_square, 4),
        "passes_benford": passes,
        "risk_level": "low" if passes else "high",
        "suspicious_digits": suspicious_digits,
        "distribution": deviations,
        "interpretation": (
            "Distribution follows Benford's Law — no significant manipulation detected."
            if passes else
            f"Distribution DEVIATES from Benford's Law (chi²={chi_square:.2f} > 15.51). "
            f"Suspicious leading digits: {', '.join(suspicious_digits)}. Consider further investigation."
        ),
    }


# ─── Cash Flow Forecasting ────────────────────────────────────────────────────

def forecast_cash_flow(historical_data: list[dict], periods: int = 6, currency: str = "SAR") -> dict:
    """
    Forecast future cash flows using AI.

    Args:
        historical_data: List of monthly {'month', 'inflow', 'outflow', 'net'} dicts.
        periods: Number of future months to forecast.
        currency: Currency code.

    Returns:
        dict with forecasted periods and confidence intervals.
    """
    system_prompt = f"""You are a financial forecasting expert for GCC markets.
Analyze historical cash flow data and forecast future periods.
Return ONLY JSON:
{{
  "forecasts": [
    {{
      "period": "YYYY-MM",
      "predicted_inflow": 0.0,
      "predicted_outflow": 0.0,
      "predicted_net": 0.0,
      "confidence_lower": 0.0,
      "confidence_upper": 0.0,
      "confidence_pct": 0-100
    }}
  ],
  "trend": "increasing|decreasing|stable|volatile",
  "seasonal_patterns": ["string"],
  "key_drivers": ["string"],
  "risks": ["string"],
  "currency": "{currency}"
}}"""

    try:
        content = _chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""
Forecast next {periods} months in {currency}.
Historical data ({len(historical_data)} months):
{json.dumps(historical_data, ensure_ascii=False, default=str)}
"""},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"Cash flow forecast error: {e}")
        return {"forecasts": [], "error": str(e)}
