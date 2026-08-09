# Tadgeeg AI Algorithms Catalog

## 1. Purpose
This document defines the AI and analytical algorithms Tadgeeg should implement, validate, and explain to enterprise clients.

## 2. Governance Principles
- AI supports auditors; it does not silently approve financial risk.
- Every AI result must include evidence.
- Every algorithm must have measurable input, output, thresholds, and tests.
- Public accuracy claims require validation datasets and benchmark reports.
- Rule engine remains the source of truth for deterministic compliance checks.

## 3. Algorithm Catalog

### 3.1 Invoice OCR and Field Extraction
**Purpose:** Extract invoice data from Arabic/English PDFs, images, and scans.  
**Inputs:** PDF, image, camera upload, OCR text, QR.  
**Outputs:** invoice number, date, supplier, VAT number, subtotal, VAT, total, currency, line items, confidence.  
**Metrics:** field accuracy, document accuracy, character error rate, processing time.  
**Controls:** Low-confidence fields go to manual review.

### 3.2 Handwritten Receipt Recognition
**Purpose:** Extract data from handwritten receipts and notes.  
**Inputs:** mobile images, scanned receipts.  
**Outputs:** merchant, amount, date, tax, notes, confidence.  
**Risk:** Accuracy varies by handwriting and image quality.  
**Control:** Never auto-approve high-value handwritten records without review.

### 3.3 VAT Calculation Verification
**Purpose:** Recalculate VAT and detect differences.  
**Inputs:** subtotal, rate, tax amount, total, country.  
**Outputs:** expected VAT, declared VAT, difference, severity.  
**Example Finding:** Declared VAT differs from expected VAT by SAR 1,250.

### 3.4 Duplicate Invoice Detection
**Purpose:** Prevent duplicate payment.  
**Methods:** file hash, invoice number + supplier, supplier + amount + date, text similarity, line-item similarity.  
**Outputs:** duplicate score, matched documents, evidence, action.

### 3.5 Benford's Law Detection
**Purpose:** Identify unnatural number distributions.  
**Inputs:** invoice totals, payments, journal amounts.  
**Suitability:** Only for large natural datasets with broad numeric spread.  
**Outputs:** deviation score, suspicious digits, affected records.

### 3.6 Outlier Transaction Detection
**Purpose:** Detect unusual amounts, dates, vendors, branches, or accounts.  
**Methods:** z-score, IQR, seasonal baseline, peer group comparison, isolation forest.  
**Outputs:** outlier score, expected range, actual value, explanation.

### 3.7 Vendor Risk Scoring
**Purpose:** Score supplier risk.  
**Inputs:** duplicates, VAT mismatches, bank account changes, abnormal frequency, missing PO/GRN.  
**Outputs:** risk score, category, top reasons, recommended controls.

### 3.8 Three-Way Matching
**Purpose:** Match purchase invoice against PO and GRN.  
**Checks:** supplier, quantities, prices, dates, totals, tolerances.  
**Outputs:** matched, partial_match, failed, missing_po, missing_grn.

### 3.9 Cash Flow Forecasting
**Purpose:** Forecast financial position for 3, 6, and 12 months.  
**Inputs:** cash inflows/outflows, receivables, payables, payroll, tax obligations, seasonality.  
**Outputs:** forecast, confidence interval, risk warnings.  
**Metrics:** MAPE, MAE, RMSE, bias.

### 3.10 Financial Report Consistency Validation
**Purpose:** Reconcile reports with ledgers, invoices, bank statements, and VAT returns.  
**Checks:** debit=credit, ledger rollforward, VAT return reconciliation, bank reconciliation.  
**Outputs:** consistency score, differences, affected accounts.

## 4. Required AI Finding Format
```json
{
  "algorithm_id": "DUPLICATE-INVOICE-01",
  "risk_score": 0.91,
  "severity": "high",
  "explanation": "Invoice is similar to an earlier invoice from the same supplier.",
  "evidence": {
    "supplier": "Example Supplier",
    "amount": 50000,
    "matched_invoice_id": "INV-10022"
  },
  "recommended_action": "Review before payment approval",
  "confidence": 0.88
}
```

## 5. Required Validation Evidence
For each algorithm:
- Dataset version.
- Number of records.
- Labeling method.
- Accuracy metrics.
- False positives.
- False negatives.
- Edge cases.
- Approval owner.
- Release date.
- Rollback plan.

## 6. Risk Controls
| Risk | Control |
|---|---|
| False fraud accusation | Human review and evidence |
| Bad OCR | Confidence threshold and correction UI |
| Model drift | Monthly validation |
| Regulatory error | Rule engine authority |
| Hallucinated explanation | Evidence-bound summaries only |
