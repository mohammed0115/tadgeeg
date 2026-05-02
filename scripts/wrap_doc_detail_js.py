"""Replace JS array literals with hardcoded Arabic in document detail templates.

Strategy: in each Alpine `xxxDetail()` function, the labels for summary cards,
column headers, and notify/alert calls are inline. We replace each Arabic
literal with a server-rendered `{% trans 'EN' %}` so it picks up the active
language at render time.
"""
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')

# Universal substring → trans-wrapped substitution.
# Each entry: literal_substring → replacement.
SUBS = [
    # ── titles / breadcrumbs the bulk wrapper missed (extra spaces in `{%  block`) ──
    ("{%  block title %}تفاصيل كشف الحساب{%  endblock %}",
     "{%  block title %}{% trans 'Bank Statement Details' %}{%  endblock %}"),
    ("{%  block title %}تفاصيل سجل الأصول الثابتة{%  endblock %}",
     "{%  block title %}{% trans 'Fixed Asset Record Details' %}{%  endblock %}"),
    (">كشوفات البنوك<", ">{% trans 'Bank Statements' %}<"),

    # ── x-text "uploaded at" ──
    ("'رُفع: ' + fmtDate(doc.created_at)",
     "'{% trans \"Uploaded:\" %} ' + fmtDate(doc.created_at)"),

    # ── pagination "صفحة X / Y" ──
    ("'صفحة ' + currentPage + ' / ' + totalPages",
     "'{% trans \"Page\" %} ' + currentPage + ' / ' + totalPages"),

    # ── "التفاصيل (X)" tabs the wrapper missed ──
    (">                التفاصيل (المعاملات)<", ">{% trans 'Details (Transactions)' %}<"),
    (">                التفاصيل (الكشف)<",     ">{% trans 'Details (Statement)' %}<"),
    (">                التفاصيل (السطور)<",     ">{% trans 'Details (Line Items)' %}<"),

    # ── notify calls (universal across all 7 detail files) ──
    ("notify('تم الاعتماد', 'success')",
     "notify(\"{% trans 'Approved' %}\", 'success')"),
    ("notify('تم الحفظ', 'success')",
     "notify(\"{% trans 'Saved' %}\", 'success')"),
    ("notify('خطأ', 'error')",
     "notify(\"{% trans 'Error' %}\", 'error')"),
    ("notify('خطأ في التحميل', 'error')",
     "notify(\"{% trans 'Loading error' %}\", 'error')"),
    ("notify('تعذّر تحميل التفاصيل', 'error')",
     "notify(\"{% trans 'Failed to load details' %}\", 'error')"),

    # ── JS array of label/value pairs → wrap each Arabic key ──
    # bank_statement_detail.html
    ("['البنك', this.doc.bank_name],['رقم الحساب', this.doc.account_number],",
     "[\"{% trans 'Bank' %}\", this.doc.bank_name],[\"{% trans 'Account Number' %}\", this.doc.account_number],"),
    ("['IBAN', this.doc.iban],['اسم الحساب', this.doc.account_name],",
     "['IBAN', this.doc.iban],[\"{% trans 'Account Name' %}\", this.doc.account_name],"),
    ("['من', this.doc.statement_period_from],['إلى', this.doc.statement_period_to],",
     "[\"{% trans 'From' %}\", this.doc.statement_period_from],[\"{% trans 'To' %}\", this.doc.statement_period_to],"),
    ("['رصيد الافتتاح', this.fmtNum(this.doc.opening_balance)],['رصيد الختام', this.fmtNum(this.doc.closing_balance)],",
     "[\"{% trans 'Opening Balance' %}\", this.fmtNum(this.doc.opening_balance)],[\"{% trans 'Closing Balance' %}\", this.fmtNum(this.doc.closing_balance)],"),
    ("['إجمالي الإيداعات', this.fmtNum(this.doc.total_credits)],['إجمالي السحوبات', this.fmtNum(this.doc.total_debits)],",
     "[\"{% trans 'Total Credits' %}\", this.fmtNum(this.doc.total_credits)],[\"{% trans 'Total Debits' %}\", this.fmtNum(this.doc.total_debits)],"),
    ("['تطابق الرصيد', this.doc.balance_matches ? '✅ متطابق' : '❌ غير متطابق'],['عدد المعاملات', this.doc.transaction_count],",
     "[\"{% trans 'Balance Match' %}\", this.doc.balance_matches ? \"✅ {% trans 'Matched' %}\" : \"❌ {% trans 'Not matched' %}\"],[\"{% trans 'Transaction Count' %}\", this.doc.transaction_count],"),
    ("get itemCols() { return ['التاريخ','الوصف','دائن','مدين','الرصيد']; }",
     "get itemCols() { return [\"{% trans 'Date' %}\",\"{% trans 'Description' %}\",\"{% trans 'Credit' %}\",\"{% trans 'Debit' %}\",\"{% trans 'Balance' %}\"]; }"),

    # fixed_asset_detail.html
    ("['الشركة', this.doc.company_name],['القسم', this.doc.department],",
     "[\"{% trans 'Company' %}\", this.doc.company_name],[\"{% trans 'Department' %}\", this.doc.department],"),
    ("['السنة المالية', this.doc.fiscal_year],['عدد الأصول', this.doc.asset_count],",
     "[\"{% trans 'Fiscal Year' %}\", this.doc.fiscal_year],[\"{% trans 'Asset Count' %}\", this.doc.asset_count],"),
    ("['إجمالي التكلفة', this.fmtNum(this.doc.total_cost)],['إجمالي الإهلاك', this.fmtNum(this.doc.total_accumulated_depreciation)],",
     "[\"{% trans 'Total Cost' %}\", this.fmtNum(this.doc.total_cost)],[\"{% trans 'Total Depreciation' %}\", this.fmtNum(this.doc.total_accumulated_depreciation)],"),
    ("['القيمة الدفترية', this.fmtNum(this.doc.total_book_value)],['قيم سالبة', this.doc.negative_book_value_count || 0],",
     "[\"{% trans 'Book Value' %}\", this.fmtNum(this.doc.total_book_value)],[\"{% trans 'Negative Values' %}\", this.doc.negative_book_value_count || 0],"),
    ("['إهلاك مفرط', this.doc.over_depreciated_count || 0],['بدون معرّف', this.doc.missing_asset_id_count || 0],",
     "[\"{% trans 'Over Depreciated' %}\", this.doc.over_depreciated_count || 0],[\"{% trans 'Missing ID' %}\", this.doc.missing_asset_id_count || 0],"),
    ("get itemCols() { return ['المعرّف','الاسم','التصنيف','التكلفة','الإهلاك المتراكم','القيمة الدفترية']; }",
     "get itemCols() { return [\"{% trans 'ID' %}\",\"{% trans 'Name' %}\",\"{% trans 'Classification' %}\",\"{% trans 'Cost' %}\",\"{% trans 'Accumulated Depreciation' %}\",\"{% trans 'Book Value' %}\"]; }"),
]


def main():
    # Find all detail files
    paths = sorted(BASE.glob('templates/documents/detail/*.html'))
    grand = 0
    for p in paths:
        text = p.read_text(encoding='utf-8')
        new_text = text
        n = 0
        for old, new in SUBS:
            if old in new_text:
                new_text = new_text.replace(old, new)
                n += 1
        if new_text != text:
            p.write_text(new_text, encoding='utf-8')
            grand += n
            print(f"[ok] {p.name}: {n}")
    print(f"\nTotal: {grand}")


if __name__ == '__main__':
    main()
