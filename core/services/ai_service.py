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

_IAS7_SYSTEM_PROMPT = """
You are an expert IFRS financial analyst specializing in IAS 7 (Statement of Cash Flows)
for GCC markets. You will receive historical transaction data and must produce a
fully IAS 7-compliant cash flow forecast.

════════════════════════════════════════
STRICT IAS 7 REQUIREMENTS — MANDATORY
════════════════════════════════════════

1. ACTIVITY CLASSIFICATION (IAS 7.14–7.17)
   Classify every cash movement into exactly ONE of:
   - operating:   receipts from customers, payments to suppliers/employees,
                  tax paid, interest paid (if operating policy)
   - investing:   purchase/sale of PPE, investments, loans given/collected
   - financing:   loan proceeds/repayments, dividends paid, equity issuance

2. PRESENTATION METHOD (IAS 7.18)
   - Use DIRECT method for operating activities (recommended by IAS 7)
   - If data is insufficient for direct, use INDIRECT and state it explicitly
   - Always declare: "method": "direct" | "indirect"

3. OPENING → CLOSING BALANCE EQUATION (IAS 7.45)
   closing_cash = opening_cash
               + net_operating
               + net_investing
               + net_financing
               + fx_effect
   This equation MUST balance. Never omit it.

4. FOREIGN CURRENCY EFFECT (IAS 7.25–7.28)
   - Report fx_effect on cash as a separate line
   - Use period-average rate for transactions, period-end rate for balances
   - If single-currency org: fx_effect = 0 (still include the field)

5. CASH & CASH EQUIVALENTS DEFINITION (IAS 7.7)
   - Cash: notes, coins, demand deposits
   - Cash equivalents: short-term investments ≤ 3 months maturity,
     readily convertible, insignificant risk of value change
   - Bank overdrafts repayable on demand are part of cash management

6. DISCOUNT / PRESENT VALUE
   - Apply discount rate to all forecast periods
   - Use SAMA rate (Saudi Arabia) or Central Bank rate for other GCC countries:
     SA: SAMA repo rate | UAE: CBUAE rate | BH: CBB rate
   - Formula: PV = FV / (1 + r)^n  where n = months / 12

7. NON-CASH TRANSACTIONS (IAS 7.43)
   - Exclude from cash flow statement
   - Disclose separately in notes field
   - Examples: asset acquisition via finance lease, debt-to-equity conversion

8. COMPARATIVE PERIODS (IAS 7.46)
   - Always include prior period actuals alongside forecast
   - Mark actuals as "actual": true, forecasts as "actual": false

════════════════════════════════════════
RESPONSE SCHEMA — RETURN ONLY THIS JSON
════════════════════════════════════════

{
  "ifrs_standard": "IAS 7",
  "presentation_method": "direct | indirect",
  "currency": "SAR | AED | KWD | ...",
  "discount_rate_pct": 0.0,
  "discount_rate_source": "SAMA repo rate | CBUAE | ...",

  "cash_equivalents_definition": "string — what is included",

  "periods": [
    {
      "period": "YYYY-MM",
      "actual": true | false,

      "opening_cash_balance": 0.0,

      "operating_activities": {
        "collections_from_customers": 0.0,
        "payments_to_suppliers": 0.0,
        "payments_to_employees": 0.0,
        "tax_paid": 0.0,
        "interest_paid": 0.0,
        "other_operating": 0.0,
        "net_operating": 0.0
      },

      "investing_activities": {
        "purchase_of_ppe": 0.0,
        "proceeds_from_disposal": 0.0,
        "purchase_of_investments": 0.0,
        "loans_advanced": 0.0,
        "loans_collected": 0.0,
        "net_investing": 0.0
      },

      "financing_activities": {
        "loan_proceeds": 0.0,
        "loan_repayments": 0.0,
        "dividends_paid": 0.0,
        "equity_issuance": 0.0,
        "net_financing": 0.0
      },

      "fx_effect_on_cash": 0.0,

      "net_change_in_cash": 0.0,
      "closing_cash_balance": 0.0,

      "present_value": 0.0,
      "confidence_lower": 0.0,
      "confidence_upper": 0.0,
      "confidence_pct": 0,

      "balance_check": {
        "equation": "opening + operating + investing + financing + fx = closing",
        "balanced": true | false,
        "variance": 0.0
      }
    }
  ],

  "non_cash_transactions": [],

  "trend_analysis": {
    "operating_trend": "increasing | decreasing | stable | volatile",
    "liquidity_ratio": 0.0,
    "cash_burn_rate": 0.0,
    "months_of_runway": 0
  },

  "key_drivers": ["string"],
  "risks": ["string"],
  "seasonal_patterns": ["string"],

  "auditor_notes": [
    "string — IAS 7 compliance observations"
  ]
}

════════════════════════════════════════
VALIDATION RULES — ENFORCE STRICTLY
════════════════════════════════════════

- closing_cash_balance = opening_cash_balance + net_operating
  + net_investing + net_financing + fx_effect_on_cash
  Tolerance: ±0.01 only. Flag balance_check.balanced = false if exceeded.

- All monetary values in the same currency. No mixing.

- confidence_pct must be between 40 and 95.
  Never claim 100% confidence on a forecast.

- If historical data < 6 months: reduce confidence_pct by 20 and add
  auditor_notes entry: "Limited history — forecast reliability reduced"

- If any activity type has no data: set all its sub-fields to 0.0,
  do NOT omit the section.

- Never hallucinate amounts not derivable from provided data.
  Use null only if data is genuinely unavailable for a sub-field.

- present_value calculation:
  n = (period_index + 1) in months from today
  PV = closing_cash_balance / (1 + discount_rate_pct/100)^(n/12)

════════════════════════════════════════
LANGUAGE
════════════════════════════════════════
- All field names: English (as schema above)
- auditor_notes, risks, key_drivers: Arabic or English matching org language
- Do NOT include any text outside the JSON object
"""


def _build_ias7_user_message(
    historical_data: list[dict],
    periods: int,
    currency: str,
    opening_balance: float,
    discount_rate: float,
    discount_source: str,
    org_country: str = "SA",
) -> str:
    return f"""Forecast the next {periods} months.

Organization country: {org_country}
Currency: {currency}
Opening cash balance (latest month): {opening_balance}
Discount rate: {discount_rate}% ({discount_source})

Historical data ({len(historical_data)} months):
{json.dumps(historical_data, ensure_ascii=False, default=str)}

Requirements:
1. Classify all transactions into operating / investing / financing
2. Use direct method if sufficient data, indirect otherwise
3. Verify closing balance equation for every period
4. Apply {discount_rate}% annual discount rate for present values
5. Include fx_effect (set to 0 if single-currency)
6. Return ONLY the JSON schema specified in the system prompt
"""


def forecast_cash_flow(
    historical_data: list[dict],
    periods: int = 6,
    currency: str = "SAR",
    opening_balance: float = 0.0,
    discount_rate: float = 6.0,
    discount_source: str = "SAMA repo rate",
    org_country: str = "SA",
) -> dict:
    """
    Forecast future cash flows using AI — IAS 7 compliant.

    Args:
        historical_data: List of monthly cash flow dicts.
        periods:         Number of future months to forecast.
        currency:        ISO currency code (SAR, AED, …).
        opening_balance: Opening cash balance of the latest historical month.
        discount_rate:   Annual discount rate % for present value calculations.
        discount_source: Source label for the discount rate (e.g. "SAMA repo rate").
        org_country:     GCC country code (SA / AE / BH / KW / OM / QA).

    Returns:
        IAS 7-structured dict with periods, trend_analysis, auditor_notes, etc.
    """
    try:
        content = _chat([
            {"role": "system", "content": _IAS7_SYSTEM_PROMPT},
            {"role": "user", "content": _build_ias7_user_message(
                historical_data, periods, currency,
                opening_balance, discount_rate, discount_source, org_country,
            )},
        ])
        return json.loads(content)
    except Exception as e:
        logger.error(f"Cash flow forecast error: {e}")
        return {"periods": [], "error": str(e)}


# ─── Executive Report AI Narrative ────────────────────────────────────────────

def generate_executive_report_narrative(
    computed_metrics: dict,
    language: str = "ar",
    org_name: str = "",
    country: str = "SA",
) -> dict | None:
    """
    Generate AI-assisted narrative for the Executive Audit Report.

    The AI receives ONLY programmatically computed metrics and interprets them.
    It NEVER invents figures — every claim must cite a provided data point.

    Args:
        computed_metrics: All programmatically computed KPIs and findings.
        language:         "ar" (default) or "en".
        org_name:         Organization name.
        country:          GCC country code (SA / AE / BH / KW / OM / QA).

    Returns:
        {
          "executive_summary":  str,        # 3–5 sentence narrative
          "anomaly_patterns":   str,        # plain-language anomaly description
          "auditor_opinion":    str,        # formal Unqualified/Qualified/Adverse opinion
          "key_risks":          list[str],  # top 3 risk statements
          "rule_rationale":     dict,       # rule_code → rationale string
        }
        Returns None if AI is unavailable or fails.
    """
    lang_instr = (
        "اكتب الرد بالكامل باللغة العربية الفصحى المهنية الرسمية."
        if language == "ar"
        else "Write entirely in formal professional English."
    )

    regulations = {
        "SA": "ZATCA Phase 2, Saudi VAT 15%, GAZT, IFRS (KSA)",
        "AE": "FTA UAE, UAE VAT 5%, IFRS",
        "BH": "NBR Bahrain, Bahrain VAT 10%",
        "KW": "Ministry of Finance Kuwait",
        "OM": "OTA Oman",
        "QA": "GAZT Qatar",
    }.get(country, "GCC financial regulations")

    system_prompt = (
        "أنت مدقق مالي معتمد (CPA/CIA) متخصص في منظمات الخليج العربي.\n"
        "مهمتك: تفسير الأرقام المحسوبة برمجيًا وصياغة تقرير تنفيذي احترافي.\n\n"
        "قواعد صارمة لا استثناء منها:\n"
        "1. استخدم الأرقام المقدمة فقط — لا تخترع أرقامًا أو نسبًا مئوية.\n"
        "2. كل جملة يجب أن تستند إلى رقم أو حقيقة مذكورة في البيانات.\n"
        "3. لا تضيف توقعات أو ادعاءات خارج نطاق البيانات المقدمة.\n"
        f"4. {lang_instr}\n\n"
        f"اللوائح المعمول بها: {regulations}\n\n"
        "أعد JSON بالهيكل التالي فقط:\n"
        "{\n"
        '  "executive_summary": "نص 3-5 جمل احترافية تلخص الوضع الكلي",\n'
        '  "anomaly_patterns": "وصف سردي للأنماط الشاذة المكتشفة فقط بناءً على الأعداد المقدمة",\n'
        '  "auditor_opinion": "رأي رسمي (غير متحفظ / متحفظ / سلبي / امتناع عن الرأي) مع التبرير بالأرقام",\n'
        '  "key_risks": ["خطر 1 مستند لبيانات فعلية", "خطر 2", "خطر 3"],\n'
        '  "rule_rationale": {\n'
        '    "<rule_code>": "تبرير قصير مبني على عدد حالات الفشل الفعلية"\n'
        '  }\n'
        "}"
    )

    # Compact payload — only the numbers, no raw records
    compact = {
        "organization":          org_name,
        "overall_score":         computed_metrics.get("overall_score"),
        "compliance_rate_pct":   computed_metrics.get("compliance_rate"),
        "risk_level":            computed_metrics.get("risk_level"),
        "avg_risk_score":        computed_metrics.get("avg_risk_score"),
        "total_documents":       computed_metrics.get("total_documents"),
        "top_issues_count":      computed_metrics.get("top_issues_count"),
        "critical_documents":    computed_metrics.get("total_critical"),
        "high_risk_documents":   computed_metrics.get("total_high"),
        "pass_rate_pct":         computed_metrics.get("pass_rate"),
        "failure_rate_pct":      computed_metrics.get("failure_rate"),
        "zatca_compliance_pct":  computed_metrics.get("zatca_compliance_rate"),
        "vat_failures":          computed_metrics.get("vat_failures"),
        "fraud_indicator_count": computed_metrics.get("fraud_indicator_count"),
        "structuring_alerts":    computed_metrics.get("structuring_alerts"),
        "ghost_employee_alerts": computed_metrics.get("ghost_employee_alerts"),
        "duplicate_alerts":      computed_metrics.get("duplicate_alerts"),
        "self_approval_alerts":  computed_metrics.get("self_approval_alerts"),
        "financial":             computed_metrics.get("financial", {}),
        "top_failed_rules":      computed_metrics.get("top_failed_rules", [])[:5],
    }

    try:
        content = _chat(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "البيانات المحسوبة برمجيًا:\n"
                        + json.dumps(compact, ensure_ascii=False, default=str)
                        + "\n\nاكتب التقرير التنفيذي بناءً على هذه البيانات فقط."
                    ),
                },
            ],
            temperature=0,
        )
        result = json.loads(content)
        result.setdefault("executive_summary", "")
        result.setdefault("anomaly_patterns", "")
        result.setdefault("auditor_opinion", "")
        result.setdefault("key_risks", [])
        result.setdefault("rule_rationale", {})
        return result
    except Exception as exc:
        logger.error("generate_executive_report_narrative failed: %s", exc)
        return None
