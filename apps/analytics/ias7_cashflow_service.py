"""IAS 7 Statement of Cash Flows — Cash Flow Classification Service

Per IAS 7, all cash flows must be classified into three categories:
1. Operating Activities (§15) — Core business operations
2. Investing Activities (§16) — Long-term asset purchases/sales
3. Financing Activities (§17) — Capital structure changes

This service automatically classifies invoices using heuristics:
- Account codes (best: direct mapping from GL system)
- Cost centers (operational department mapping)
- Invoice description keywords
- Vendor type analysis
- Historical patterns (if available)

Each invoice gets:
- cash_flow_class: Operating | Investing | Financing | Unclassified
- cash_flow_subcategory: Detailed classification (e.g., "op_salary", "inv_equipment")
- cash_flow_confidence: 0.0-1.0 (1.0 = manually verified)
- Confidence < 0.7 triggers manual review flag

Per:
- IAS 7:2017 "Statement of Cash Flows"
- ISA 570:3 "Going Concern" (relies on cash flow forecasts)
- ISA 540 "Auditing Accounting Estimates" (cash flow projections)
- Big Four guidance on cash flow audit procedures
"""

import re
import logging
from decimal import Decimal
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger(__name__)


class IAS7CashFlowClassifier:
    """Automatically classify invoices per IAS 7 cash flow categories."""

    # ── Heuristic Mappings (IAS 7 §15-17) ─────────────────────────────────────
    
    # IAS 7 §15 — Operating Activities patterns
    OPERATING_KEYWORDS = {
        "salary", "wage", "payroll", "bonus", "commission",
        "supply", "supplies", "consumables", "stationery", "office",
        "utility", "utilities", "water", "electricity", "gas", "power",
        "rent", "lease", "leasing",
        "insurance", "premium",
        "maintenance", "repair", "repairs", "service", "cleaning",
        "fuel", "petrol", "diesel",
        "professional", "consultant", "consulting", "legal", "audit", "accounting",
        "training", "course", "education",
        "travel", "hotel", "flight", "transport", "transportation",
        "meal", "food", "catering",
        "telephone", "internet", "communication",
        "advertising", "marketing", "promotion",
        "customer", "client", "subscription",
        "royalty", "licensing",
        "employee", "hr", "human resources",
        "security", "guard",
        "postage", "shipping", "courier",
        "subscription", "software", "license",
    }

    # IAS 7 §16 — Investing Activities patterns
    INVESTING_KEYWORDS = {
        "equipment", "machinery", "machine", "tools", "tool",
        "property", "real estate", "building", "construction", "land",
        "vehicle", "car", "truck", "bus", "fleet",
        "computer", "laptop", "server", "it", "hardware",
        "software", "development", "platform",
        "patent", "trademark", "intellectual property", "ip",
        "intangible", "goodwill",
        "investment", "securities", "stocks", "bonds",
        "acquisition", "purchase", "capex",
        "refurbish", "upgrade", "renovation",
        "research", "development", "rd", "product development",
        "furniture", "fixture", "asset",
    }

    # IAS 7 §17 — Financing Activities patterns
    FINANCING_KEYWORDS = {
        "loan", "borrowing", "borrow", "credit", "financing",
        "debt", "bond", "debenture",
        "equity", "shares", "stock", "capital",
        "dividend", "distribution",
        "repayment", "repay", "paydown", "refinance",
        "interest", "fee", "charge",
        "bank", "banking",
        "principal", "installment",
    }

    # Account code patterns (SAP/Oracle GL codes typically)
    # Format: account_code_pattern -> (cash_flow_class, subcategory)
    ACCOUNT_CODE_PATTERNS = {
        # Operating — Expense accounts
        r"^61": ("operating", "op_salary"),           # 61xx = Salaries
        r"^62": ("operating", "op_supplies"),         # 62xx = Materials
        r"^63": ("operating", "op_utilities"),        # 63xx = Utilities
        r"^64": ("operating", "op_rent"),             # 64xx = Rent
        r"^65": ("operating", "op_maintenance"),      # 65xx = Repairs
        r"^66": ("operating", "op_professional"),     # 66xx = Services
        r"^67": ("operating", "op_travel"),           # 67xx = Travel
        r"^68": ("operating", "op_insurance"),        # 68xx = Insurance
        r"^69": ("operating", "op_other"),            # 69xx = Other operating

        # Investing — Fixed Assets
        r"^10": ("investing", "inv_property"),        # 10xx = Buildings
        r"^11": ("investing", "inv_equipment"),       # 11xx = Equipment
        r"^12": ("investing", "inv_intangible"),      # 12xx = Intangible assets
        r"^13": ("investing", "inv_investments"),     # 13xx = Long-term investments

        # Financing — Liabilities & Equity
        r"^20": ("financing", "fin_loan"),            # 20xx = Short-term debt
        r"^21": ("financing", "fin_loan"),            # 21xx = Long-term debt
        r"^30": ("financing", "fin_equity"),          # 30xx = Equity
        r"^31": ("financing", "fin_dividends"),       # 31xx = Dividends
    }

    # Cost center to cash flow class mapping
    COST_CENTER_PATTERNS = {
        r"1100": ("operating", "op_salary"),          # HR Department
        r"2200": ("operating", "op_supplies"),        # Procurement
        r"3300": ("operating", "op_utilities"),       # Facilities
        r"4400": ("operating", "op_maintenance"),     # Maintenance
        r"5500": ("investing", "inv_equipment"),      # Capital projects
        r"6600": ("financing", "fin_loan"),           # Finance department
    }

    # Vendor type heuristics
    VENDOR_TYPE_PATTERNS = {
        r"(salary|payroll|hr)": ("operating", "op_salary"),
        r"(supplier|distributor)": ("operating", "op_supplies"),
        r"(utility|water|electricity|gas company)": ("operating", "op_utilities"),
        r"(landlord|property|real estate)": ("operating", "op_rent"),
        r"(bank|financial|lender)": ("financing", "fin_loan"),
        r"(equipment|machinery|vendor)": ("investing", "inv_equipment"),
        r"(construction|contractor|developer)": ("investing", "inv_property"),
        r"(insurance|broker)": ("operating", "op_insurance"),
        r"(consultant|professional|legal)": ("operating", "op_professional"),
    }

    # Minimum confidence threshold to avoid manual review
    MIN_CONFIDENCE_THRESHOLD = 0.70

    def classify_invoice(self, invoice) -> Dict:
        """
        Classify a single invoice into IAS 7 cash flow categories.

        Args:
            invoice: Invoice model instance

        Returns:
            Dict with keys:
                - cash_flow_class: "operating" | "investing" | "financing" | "unclassified"
                - cash_flow_subcategory: Detailed subcategory code
                - cash_flow_confidence: 0.0-1.0 confidence score
                - reasoning: List of heuristics applied
        """
        
        reasoning = []
        scores = {"operating": [], "investing": [], "financing": []}

        # ── Strategy 1: Account Code Pattern Matching (Highest priority) ────────
        if invoice.account_code:
            account_result = self._classify_by_account_code(invoice.account_code)
            if account_result:
                cf_class, subcat = account_result
                scores[cf_class].append(0.95)  # Very high confidence
                reasoning.append(f"Account code '{invoice.account_code}' → {subcat}")
                result = self._finalize_classification(scores, reasoning, invoice)
                return result

        # ── Strategy 2: Cost Center Pattern Matching ────────────────────────────
        if invoice.cost_center:
            costctr_result = self._classify_by_cost_center(invoice.cost_center)
            if costctr_result:
                cf_class, subcat = costctr_result
                scores[cf_class].append(0.85)
                reasoning.append(f"Cost center '{invoice.cost_center}' → {subcat}")

        # ── Strategy 3: Vendor Type Analysis ──────────────────────────────────
        if invoice.vendor_name:
            vendor_result = self._classify_by_vendor_name(invoice.vendor_name)
            if vendor_result:
                cf_class, subcat = vendor_result
                scores[cf_class].append(0.75)
                reasoning.append(f"Vendor '{invoice.vendor_name}' → {subcat}")

        # ── Strategy 4: Invoice Description / Line Items ───────────────────────
        description = f"{invoice.ai_summary} {invoice.notes}".lower()
        desc_result = self._classify_by_keywords(description)
        if desc_result:
            cf_class, subcat, keyword_count = desc_result
            # Confidence based on keyword matches (0.5-0.8)
            confidence = 0.5 + min(0.3, keyword_count * 0.1)
            scores[cf_class].append(confidence)
            reasoning.append(f"Keywords: {', '.join([invoice.ai_summary[:30], invoice.notes[:30]])}")

        # ── Finalize Classification ───────────────────────────────────────────
        return self._finalize_classification(scores, reasoning, invoice)

    def _classify_by_account_code(self, account_code: str) -> Optional[Tuple[str, str]]:
        """Match account code against pattern library."""
        for pattern, (cf_class, subcat) in self.ACCOUNT_CODE_PATTERNS.items():
            if re.match(pattern, str(account_code)[:2]):
                return (cf_class, subcat)
        return None

    def _classify_by_cost_center(self, cost_center: str) -> Optional[Tuple[str, str]]:
        """Match cost center against pattern library."""
        for pattern, (cf_class, subcat) in self.COST_CENTER_PATTERNS.items():
            if re.search(pattern, str(cost_center)):
                return (cf_class, subcat)
        return None

    def _classify_by_vendor_name(self, vendor_name: str) -> Optional[Tuple[str, str]]:
        """Analyze vendor name to infer cash flow class."""
        vendor_lower = vendor_name.lower()
        for pattern, (cf_class, subcat) in self.VENDOR_TYPE_PATTERNS.items():
            if re.search(pattern, vendor_lower):
                return (cf_class, subcat)
        return None

    def _classify_by_keywords(self, text: str) -> Optional[Tuple[str, str, int]]:
        """Count keywords from description to determine class."""
        text_lower = text.lower()
        
        op_count = sum(1 for kw in self.OPERATING_KEYWORDS if kw in text_lower)
        inv_count = sum(1 for kw in self.INVESTING_KEYWORDS if kw in text_lower)
        fin_count = sum(1 for kw in self.FINANCING_KEYWORDS if kw in text_lower)

        # Return class with highest keyword count
        if max(op_count, inv_count, fin_count) == 0:
            return None

        if op_count >= inv_count and op_count >= fin_count:
            # Map to most common operating subcategory based on keywords
            if any(kw in text_lower for kw in ["salary", "wage", "payroll"]):
                return ("operating", "op_salary", op_count)
            elif any(kw in text_lower for kw in ["supply", "supplies", "consumables"]):
                return ("operating", "op_supplies", op_count)
            else:
                return ("operating", "op_other", op_count)

        if inv_count >= op_count and inv_count >= fin_count:
            if any(kw in text_lower for kw in ["equipment", "machinery"]):
                return ("investing", "inv_equipment", inv_count)
            elif any(kw in text_lower for kw in ["property", "real estate", "building"]):
                return ("investing", "inv_property", inv_count)
            else:
                return ("investing", "inv_other", inv_count)

        if fin_count >= op_count and fin_count >= inv_count:
            if any(kw in text_lower for kw in ["loan", "borrowing", "credit"]):
                return ("financing", "fin_loan", fin_count)
            elif any(kw in text_lower for kw in ["dividend", "distribution"]):
                return ("financing", "fin_dividends", fin_count)
            else:
                return ("financing", "fin_other", fin_count)

        return None

    def _finalize_classification(self, scores: Dict, reasoning: List, invoice) -> Dict:
        """Calculate final classification from accumulated scores."""
        
        # Calculate average score for each class
        final_scores = {}
        for cf_class, score_list in scores.items():
            if score_list:
                final_scores[cf_class] = sum(score_list) / len(score_list)
            else:
                final_scores[cf_class] = 0.0

        # Determine winning class
        winning_class = max(final_scores.keys(), key=lambda k: final_scores[k])
        confidence = final_scores[winning_class]

        # If no clear winner or confidence too low, mark as unclassified
        if confidence < 0.5:
            winning_class = "unclassified"
            confidence = 0.0
            reasoning.append("No clear classification pattern matched (confidence < 0.5)")

        # Determine subcategory based on class
        subcat = self._default_subcategory_for_class(winning_class)

        return {
            "cash_flow_class": winning_class,
            "cash_flow_subcategory": subcat,
            "cash_flow_confidence": round(confidence, 2),
            "reasoning": reasoning,
            "requires_review": confidence < self.MIN_CONFIDENCE_THRESHOLD,
        }

    def _default_subcategory_for_class(self, cf_class: str) -> str:
        """Return default subcategory for a cash flow class."""
        defaults = {
            "operating": "op_other",
            "investing": "inv_other",
            "financing": "fin_other",
            "unclassified": "",
        }
        return defaults.get(cf_class, "")

    def classify_batch(self, invoices: List) -> Dict:
        """
        Classify a batch of invoices and return statistics.

        Returns:
            {
                "total": int,
                "by_class": {"operating": int, "investing": int, ...},
                "by_confidence": {"high": int, "medium": int, "low": int, "unclassified": int},
                "requires_review_count": int,
                "samples": [{"invoice_id", "classification", ...}]
            }
        """
        classif_by_class = {"operating": 0, "investing": 0, "financing": 0, "unclassified": 0}
        classif_by_confidence = {"high": 0, "medium": 0, "low": 0, "unclassified": 0}
        requires_review = 0
        samples = []

        for invoice in invoices:
            result = self.classify_invoice(invoice)
            cf_class = result["cash_flow_class"]
            confidence = result["cash_flow_confidence"]

            classif_by_class[cf_class] += 1

            if cf_class == "unclassified":
                classif_by_confidence["unclassified"] += 1
            elif confidence >= 0.85:
                classif_by_confidence["high"] += 1
            elif confidence >= 0.70:
                classif_by_confidence["medium"] += 1
            else:
                classif_by_confidence["low"] += 1

            if result.get("requires_review"):
                requires_review += 1

            # Collect sample for audit trail
            if len(samples) < 10:  # Limit samples to 10 for reporting
                samples.append({
                    "invoice_id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "vendor": invoice.vendor_name,
                    "amount": str(invoice.total_amount),
                    "classification": cf_class,
                    "subcategory": result["cash_flow_subcategory"],
                    "confidence": result["cash_flow_confidence"],
                    "reasoning": result["reasoning"],
                })

        return {
            "total": len(invoices),
            "by_class": classif_by_class,
            "by_confidence": classif_by_confidence,
            "requires_review_count": requires_review,
            "samples": samples,
        }


class IAS7CashFlowService:
    """Integration service for IAS 7 cash flow classification in audit pipeline."""

    def __init__(self, organization, user=None):
        self.organization = organization
        self.user = user
        self.classifier = IAS7CashFlowClassifier()
        self.logger = logger

    def classify_invoices(self, invoices: List) -> Dict:
        """
        Classify invoices and apply classifications to database.

        Returns:
            {
                "success": bool,
                "classified_count": int,
                "unclassified_count": int,
                "requires_review_count": int,
                "statistics": {
                    "by_class": {...},
                    "by_confidence": {...},
                    "total_cashflow_value_by_class": {...}
                },
                "samples": [...]
            }
        """
        results = self.classifier.classify_batch(invoices)
        
        # Accumulate cash flow totals
        cashflow_value_by_class = {
            "operating": Decimal("0.00"),
            "investing": Decimal("0.00"),
            "financing": Decimal("0.00"),
            "unclassified": Decimal("0.00"),
        }

        # Apply classifications to invoices
        for invoice in invoices:
            classification = self.classifier.classify_invoice(invoice)
            
            invoice.cash_flow_class = classification["cash_flow_class"]
            invoice.cash_flow_subcategory = classification["cash_flow_subcategory"]
            invoice.cash_flow_confidence = classification["cash_flow_confidence"]
            invoice.save(update_fields=[
                "cash_flow_class",
                "cash_flow_subcategory",
                "cash_flow_confidence",
                "updated_at"
            ])

            # Accumulate totals
            cf_class = classification["cash_flow_class"]
            cashflow_value_by_class[cf_class] += invoice.total_amount

        return {
            "success": True,
            "classified_count": len(invoices) - results["by_class"]["unclassified"],
            "unclassified_count": results["by_class"]["unclassified"],
            "requires_review_count": results["requires_review_count"],
            "statistics": {
                "by_class": results["by_class"],
                "by_confidence": results["by_confidence"],
                "total_cashflow_value_by_class": {k: str(v) for k, v in cashflow_value_by_class.items()},
            },
            "samples": results["samples"],
        }

    def build_cashflow_statement(self, invoices: List) -> Dict:
        """
        Build simplified IAS 7 cash flow statement from classified invoices.

        Returns structured cash flow statement per IAS 7:2017
        """
        from collections import defaultdict
        from decimal import Decimal

        by_class_and_subcat = defaultdict(Decimal)
        
        for invoice in invoices:
            if invoice.is_deleted or invoice.cash_flow_class == "unclassified":
                continue
            
            key = (invoice.cash_flow_class, invoice.cash_flow_subcategory)
            by_class_and_subcat[key] += invoice.total_amount

        # Structure per IAS 7 format
        operating = Decimal("0.00")
        investing = Decimal("0.00")
        financing = Decimal("0.00")

        operating_details = {}
        investing_details = {}
        financing_details = {}

        for (cf_class, subcat), amount in by_class_and_subcat.items():
            if cf_class == "operating":
                operating += amount
                operating_details[subcat] = str(amount)
            elif cf_class == "investing":
                investing += amount
                investing_details[subcat] = str(amount)
            elif cf_class == "financing":
                financing += amount
                financing_details[subcat] = str(amount)

        net_change = operating - investing - financing

        return {
            "statement_date": timezone.now().isoformat(),
            "organization": str(self.organization),
            "standard": "IAS 7:2017",
            "cash_flows": {
                "operating_activities": {
                    "total": str(operating),
                    "details": operating_details,
                },
                "investing_activities": {
                    "total": str(investing),
                    "details": investing_details,
                },
                "financing_activities": {
                    "total": str(financing),
                    "details": financing_details,
                },
                "net_increase_in_cash": str(net_change),
            },
            "notes": {
                "scope": "Based on uploaded invoices classified per IAS 7:2017",
                "period": "Period covered by batch classification",
                "currency": invoices[0].currency if invoices else "SAR",
                "review_status": "Pending manual review of low-confidence classifications",
            },
        }
