from typing import Optional

from apps.audit_engine.services.rules.base import BaseAuditRule, RuleResult


class EmptyDocumentRule(BaseAuditRule):
    """R001 — Flag documents that have no meaningful text content."""

    rule_code = "R001"
    rule_name = "Empty Document"
    audit_types = []  # applies to all types

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        text = (parse_result.text or "").strip()
        if len(text) < 50:
            return RuleResult(
                issues=[
                    {
                        "issue_code": self.rule_code,
                        "issue_type": "empty_section",
                        "severity": "critical",
                        "title": "Document appears empty or too short",
                        "description": (
                            f"Extracted text length is {len(text)} characters, "
                            "which is below the minimum threshold of 50."
                        ),
                        "suggested_fix": (
                            "Verify the file is not corrupted and contains readable text. "
                            "For scanned PDFs, ensure OCR is enabled."
                        ),
                        "confidence_score": 1.0,
                        "metadata": {"text_length": len(text)},
                    }
                ],
                score_impact=20.0,
            )
        return RuleResult()


class LowPageCountRule(BaseAuditRule):
    """R002 — Flag PDF files with no readable pages."""

    rule_code = "R002"
    rule_name = "Low Page Count"
    audit_types = []  # applies to all types; guards on file ext via page_count

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        # Only meaningful for PDFs — indicated by page_count being explicitly 0
        if parse_result.page_count == 0:
            return RuleResult(
                issues=[
                    {
                        "issue_code": self.rule_code,
                        "issue_type": "invalid_structure",
                        "severity": "high",
                        "title": "PDF has no readable pages",
                        "description": (
                            "The PDF document returned a page count of 0. "
                            "The file may be empty, password-protected, or corrupt."
                        ),
                        "suggested_fix": (
                            "Open the file manually to confirm it contains pages. "
                            "Remove password protection before uploading."
                        ),
                        "confidence_score": 1.0,
                        "metadata": {"page_count": 0},
                    }
                ],
                score_impact=10.0,
            )
        return RuleResult()


class MissingMetadataRule(BaseAuditRule):
    """R003 — Flag documents that carry no metadata."""

    rule_code = "R003"
    rule_name = "Missing Metadata"
    audit_types = []

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        metadata = parse_result.metadata or {}
        # Consider metadata "missing" if the dict is empty or all values are blank
        has_data = any(v for v in metadata.values() if v not in ("", None, [], {}))
        if not metadata or not has_data:
            return RuleResult(
                issues=[
                    {
                        "issue_code": self.rule_code,
                        "issue_type": "missing_field",
                        "severity": "low",
                        "title": "No document metadata found",
                        "description": (
                            "The file did not expose any metadata (title, author, sheet names, etc.). "
                            "This may indicate a stripped or auto-generated document."
                        ),
                        "suggested_fix": "Add document properties/metadata before submitting.",
                        "confidence_score": 0.9,
                        "metadata": {},
                    }
                ],
                score_impact=2.0,
            )
        return RuleResult()


class LowRowCountRule(BaseAuditRule):
    """R004 — Flag spreadsheets with too few data rows."""

    rule_code = "R004"
    rule_name = "Low Row Count"
    audit_types = []  # guards itself via row_count semantics

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        # Only relevant when row_count was set by CSV/Excel parser (> 0 indicates tabular data expected)
        row_count = parse_result.row_count

        # Skip if this is not a tabular document (row_count stays 0 for PDFs/images intentionally)
        if not parse_result.column_names and row_count == 0:
            # No columns detected either — non-tabular file, skip
            return RuleResult()

        issues = []

        if row_count == 0:
            issues.append(
                {
                    "issue_code": self.rule_code,
                    "issue_type": "empty_section",
                    "severity": "high",
                    "title": "No data rows found in spreadsheet",
                    "description": (
                        "The spreadsheet contains headers but no data rows. "
                        "The file may be a template or have been uploaded prematurely."
                    ),
                    "suggested_fix": "Populate the spreadsheet with at least one data row.",
                    "confidence_score": 1.0,
                    "metadata": {"row_count": row_count},
                }
            )
        elif row_count < 2:
            issues.append(
                {
                    "issue_code": self.rule_code,
                    "issue_type": "weak_completeness",
                    "severity": "medium",
                    "title": "Very few rows detected",
                    "description": (
                        f"Only {row_count} data row(s) found. "
                        "This may indicate an incomplete export."
                    ),
                    "suggested_fix": "Confirm the full dataset was exported before uploading.",
                    "confidence_score": 0.85,
                    "metadata": {"row_count": row_count},
                }
            )

        total_impact = sum(
            {"high": 10, "medium": 5}.get(i["severity"], 2) for i in issues
        )
        return RuleResult(issues=issues, score_impact=float(total_impact))


class MissingColumnHeadersRule(BaseAuditRule):
    """R005 — Flag tabular files that have no detectable column headers."""

    rule_code = "R005"
    rule_name = "Missing Column Headers"
    audit_types = []

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        # Only fire when we expect column data (sheet_names or row_count signals tabular)
        is_tabular = bool(parse_result.sheet_names) or parse_result.row_count > 0
        if not is_tabular:
            return RuleResult()

        if not parse_result.column_names:
            return RuleResult(
                issues=[
                    {
                        "issue_code": self.rule_code,
                        "issue_type": "missing_field",
                        "severity": "high",
                        "title": "No column headers detected",
                        "description": (
                            "The spreadsheet or CSV file does not contain column headers in the first row. "
                            "This will prevent automated field mapping."
                        ),
                        "suggested_fix": (
                            "Add a header row as the first row of the file "
                            "with descriptive column names."
                        ),
                        "confidence_score": 1.0,
                        "metadata": {},
                    }
                ],
                score_impact=10.0,
            )
        return RuleResult()


class WeakTextContentRule(BaseAuditRule):
    """R006 — Flag documents with very little text (< 20 words)."""

    rule_code = "R006"
    rule_name = "Weak Text Content"
    audit_types = []

    def apply(self, parse_result, audit_type: str, context: Optional[dict] = None) -> RuleResult:
        text = (parse_result.text or "").strip()
        word_count = len(text.split()) if text else 0

        if word_count < 20:
            return RuleResult(
                issues=[
                    {
                        "issue_code": self.rule_code,
                        "issue_type": "weak_completeness",
                        "severity": "medium",
                        "title": "Document has very little text content",
                        "description": (
                            f"Only {word_count} word(s) were extracted from this document. "
                            "This may indicate a scan with poor OCR quality, an image-only PDF, "
                            "or an incomplete document."
                        ),
                        "suggested_fix": (
                            "Ensure the document is machine-readable. "
                            "For scanned documents, run OCR pre-processing."
                        ),
                        "confidence_score": 0.9,
                        "metadata": {"word_count": word_count},
                    }
                ],
                score_impact=5.0,
            )
        return RuleResult()
