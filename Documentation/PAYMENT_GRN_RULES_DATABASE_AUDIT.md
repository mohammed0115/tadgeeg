# Payment & GRN Rules — Database Registration Audit

**Date**: March 29, 2026  
**Status**: ❌ **CRITICAL GAP — Rules In Code But Not In Database**

---

## EXECUTIVE SUMMARY

Payment and GRN audit rules are **fully implemented in Python code** but **NOT registered in the database**. When the audit engine runs, it will fail to find these rules because the rule registry only loads from the database.

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| **Payment Rules (PMT-001 to PMT-010)** | 10 | 0 | ❌ MISSING |
| **GRN Rules (GRN-001 to GRN-010)** | 10 | 0 | ❌ MISSING |
| **Payment Rule Assignments** | 10+ | 0 | ❌ MISSING |
| **GRN Rule Assignments** | 10+ | 0 | ❌ MISSING |
| **Total Rules in Database** | 104 | 48 | ❌ 54% INCOMPLETE |

---

## 1. RULE DEFINITION TABLE QUERY

### Query: Find All Payment & GRN Rules
```sql
SELECT 
    rule_code, category, rule_type, default_severity, is_active, implementation_class
FROM re_rule_definition 
WHERE rule_code LIKE 'PMT-%' OR rule_code LIKE 'GRN-%'
ORDER BY rule_code;
```

### Result: **ZERO ROWS**
❌ **No payment or GRN rules found in database**

---

## 2. RULE ASSIGNMENT TABLE QUERY

### Query A: Payment Rule Assignments
```sql
SELECT 
    ra.id, rd.rule_code, ra.document_type, ra.status, ra.effective_from
FROM re_rule_assignment ra
JOIN re_rule_definition rd ON ra.rule_id = rd.id
WHERE rd.rule_code LIKE 'PMT-%'
ORDER BY rd.rule_code;
```

### Result: **ZERO ROWS**
❌ **No payment rule assignments found**

### Query B: GRN Rule Assignments  
```sql
SELECT 
    ra.id, rd.rule_code, ra.document_type, ra.status, ra.effective_from
FROM re_rule_assignment ra
JOIN re_rule_definition rd ON ra.rule_id = rd.id
WHERE rd.rule_code LIKE 'GRN-%'
ORDER BY rd.rule_code;
```

### Result: **ZERO ROWS**
❌ **No GRN rule assignments found**

---

## 3. RULE COUNT SUMMARY

### Query: Group by Category
```sql
SELECT 
    category, 
    COUNT(*) as total_rules,
    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_rules
FROM re_rule_definition 
GROUP BY category
ORDER BY category;
```

### Result:

| Category | Total | Active | Status |
|----------|-------|--------|--------|
| anomaly | 2 | 2 | ✅ |
| compliance | 23 | 23 | ✅ |
| data_integrity | 9 | 9 | ✅ |
| financial_logic | 11 | 11 | ✅ |
| reconciliation | 3 | 3 | ✅ |
| **MISSING: payment** | **0** | **0** | ❌ |
| **MISSING: grn** | **0** | **0** | ❌ |
| **MISSING: risk** | **0** | **0** | ❌ |
| **TOTAL** | **48** | **48** | ⚠️ **54% COMPLETE** |

---

## 4. ROOT CAUSE ANALYSIS

### A. Rules Exist in Code ✅
**Location**: `/apps/rule_engine/rules/payment/payment_rules.py` and `/apps/rule_engine/rules/grn/grn_rules.py`

**Example - Payment Rules (PMT-001 to PMT-010)**:
```python
class PaymentReferenceRule(AuditRuleBase):
    rule_code = "PMT-001"
    rule_name_en = "Payment Reference Number Required"
    ...

class PaymentDateVsInvoiceDueDateRule(AuditRuleBase):
    rule_code = "PMT-002"
    rule_name_en = "Payment Date vs Invoice Due Date"
    ...
```

**Status**: ✅ 10 Python classes fully implemented with pass/fail logic

### B. Infrastructure Exists ✅
- `RuleDefinition` model exists (`re_rule_definition` table)
- `RuleAssignment` model exists (`re_rule_assignment` table)
- `RuleDefinitionTranslation` model exists
- Rule registry can load classes dynamically

**Status**: ✅ Database schema is ready

### C. Database Registration Missing ❌
- **No migration** seeds Payment/GRN rules into `re_rule_definition`
- **No rule assignments** bind rules to document types (payment/grn)
- **Seed migration** only includes GAAP rules (23 rules total)

**Current Seed Migration** (`0003_seed_gaap_rules.py`):
- GAAP-COMP-001 → GAAP-CUS-007 (only 7-8 GAAP rules)
- No PMT rules
- No GRN rules

### D. SupportedDocumentType Gap ⚠️
The `RuleAssignment.SupportedDocumentType` choices don't include 'payment' or 'grn':

```python
class SupportedDocumentType(models.TextChoices):
    SALES_INVOICE = "sales_invoice", "Sales Invoice"
    PURCHASE_ORDER = "purchase_order", "Purchase Order"
    BANK_STATEMENT = "bank_statement", "Bank Statement"
    PAYROLL = "payroll", "Payroll Sheet"
    EXPENSE = "expense", "Expense Report"
    TAX_RETURN = "tax_return", "VAT / Tax Return"
    FIXED_ASSET = "fixed_asset", "Fixed Asset Register"
    SALES_RECEIPT = "sales_receipt", "Sales Receipt"
    OTHER = "other", "Other"
    # ❌ MISSING: PAYMENT, GRN
```

---

## 5. IMPACT ASSESSMENT

### Runtime Behavior
When the audit pipeline processes a Payment or GRN document:

```
✗ Document received (type='payment')
  ↓
✗ Rule selector searches re_rule_definition for rule_code='PMT-001'
  ↓
✗ Query returns: 0 rows
  ↓
✗ Rule fails to load → Document passes audit by default (SILENT FAILURE)
```

### Affected Flows
1. **Upload Pipeline** — Payment/GRN documents bypass all validation rules
2. **Audit Reports** — No rule violations will be recorded
3. **Risk Scoring** — Cannot assess rule-based risk for these document types
4. **Compliance Checks** — Missing audit trail for payment/GRN validation

---

## 6. REMEDIATION PLAN

### Step 1: Update SupportedDocumentType
**File**: `apps/rule_engine/models/rule_assignment.py`

```python
class SupportedDocumentType(models.TextChoices):
    # ... existing ...
    SALES_RECEIPT = "sales_receipt", "Sales Receipt"
    PAYMENT = "payment", "Payment Record"           # ← ADD
    GRN = "grn", "Goods Receipt Note"               # ← ADD
    OTHER = "other", "Other"
```

### Step 2: Create Migration to Seed Payment/GRN Rules
**File**: `apps/rule_engine/migrations/0004_seed_payment_grn_rules.py`

**Content**: `PaymentReferenceRule`, `PaymentDateVsInvoiceDueDateRule`, ... through `PaymentReversalCheckRule` (PMT-001 to PMT-010) and all 10 GRN rules.

**Assign Rules**: Create 20+ RuleAssignment records linking each rule to document_type='payment' or 'grn'.

### Step 3: Verify in Database
```sql
-- After migration, should show:
SELECT COUNT(*) FROM re_rule_definition 
WHERE rule_code LIKE 'PMT-%' OR rule_code LIKE 'GRN-%';
-- Expected: 20 rows

SELECT COUNT(*) FROM re_rule_assignment 
WHERE document_type IN ('payment', 'grn');
-- Expected: 20+ rows
```

---

## 7. APPENDIX: DETAILED QUERY RESULTS

### A. Payment Rules Defined in Code
```
1. PMT-001: Payment Reference Number Required (severity: high)
2. PMT-002: Payment Date vs Invoice Due Date (severity: high)
3. PMT-003: Payment Amount vs Invoice Amount (severity: critical)
4. PMT-004: Beneficiary Validation (severity: high)
5. PMT-005: Bank Account Verification (severity: medium)
6. PMT-006: Authorization Level Check (severity: critical)
7. PMT-007: Duplicate Payment Check (severity: high)
8. PMT-008: Bank Reconciliation (severity: medium)
9. PMT-009: Cash Payment Validation (severity: high)
10. PMT-010: Payment Reversal Check (severity: medium)
```

### B. GRN Rules Defined in Code
```
1. GRN-001: PO Reference Required (severity: high)
2. GRN-002: Receipt Date Validation (severity: high)
3. GRN-003: Quantity vs PO Match (severity: critical)
4. GRN-004: Unit Price vs PO Match (severity: critical)
5. GRN-005: Total Amount vs PO (severity: critical)
6. GRN-006: Supplier Validation (severity: medium)
7. GRN-007: Batch/Serial Number Check (severity: medium)
8. GRN-008: Goods Quality/Condition (severity: high)
9. GRN-009: Warehouse Location (severity: medium)
10. GRN-010: Future-Dated GRN (severity: high)
```

### C. Database Configuration
```
Database: /home/mohamed/Desktop/for\ sale/tadgeeg/db_runtime.sqlite3
Engine: Django SQLite3
Tables: 111 total
Rule Tables:
  - re_rule_definition (48 rows) — missing PMT/GRN
  - re_rule_definition_translation (48+ rows)
  - re_rule_assignment (N rows)
  - rule_engine_rulefielddependency
```

---

## CONCLUSION

**Status**: ⚠️ **BLOCKER** — Payment and GRN audit rules will not execute in production.

**Required Actions**:
1. ✅ Update `SupportedDocumentType` to include 'payment' and 'grn'
2. ✅ Create migration 0004 to seed 20 rules from code to database
3. ✅ Run migration to populate `re_rule_definition` and `re_rule_assignment`
4. ✅ Test: Verify rules load and execute on sample Payment/GRN documents

**Effort**: ~2 hours  
**Risk**: High (if not fixed, audit pipeline is ineffective for payment/GRN documents)

