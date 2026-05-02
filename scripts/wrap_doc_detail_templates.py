"""Wrap hardcoded Arabic in templates/documents/detail/*.html.

Same approach as wrap_arabic_in_admin_templates.py — pattern dictionary
applied via regex to the targeted set of files.
"""
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')
TARGETS = [
    'templates/documents/detail/bank_statement_detail.html',
    'templates/documents/detail/fixed_asset_detail.html',
    'templates/documents/detail/purchase_order_detail.html',
    'templates/documents/detail/vat_return_detail.html',
    'templates/documents/detail/expense_report_detail.html',
    'templates/documents/detail/payroll_detail.html',
    'templates/documents/detail/sales_receipt_detail.html',
]

# Comprehensive phrase map.
PHRASES = [
    # Page titles / breadcrumbs
    ('تفاصيل سجل الأصول الثابتة', 'Fixed Asset Record Details'),
    ('تفاصيل كشف الحساب البنكي', 'Bank Statement Details'),
    ('تفاصيل أمر الشراء', 'Purchase Order Details'),
    ('تفاصيل إقرار ضريبة القيمة المضافة', 'VAT Return Details'),
    ('تفاصيل تقرير المصروفات', 'Expense Report Details'),
    ('تفاصيل كشف الراتب', 'Payroll Slip Details'),
    ('تفاصيل إيصال البيع', 'Sales Receipt Details'),
    ('تفاصيل', 'Details'),

    # Listing breadcrumbs
    ('الأصول الثابتة', 'Fixed Assets'),
    ('كشوف الحسابات البنكية', 'Bank Statements'),
    ('أوامر الشراء', 'Purchase Orders'),
    ('إقرارات الضريبة', 'VAT Returns'),
    ('تقارير المصروفات', 'Expense Reports'),
    ('كشوف الرواتب', 'Payroll Slips'),
    ('إيصالات البيع', 'Sales Receipts'),

    # Table headers / labels
    ('التفاصيل (الأصول)', 'Details (Assets)'),
    ('التفاصيل (البنود)', 'Details (Line Items)'),
    ('التفاصيل (الموظفون)', 'Details (Employees)'),
    ('التفاصيل (المبيعات)', 'Details (Sales)'),
    ('التفاصيل (الكشف)', 'Details (Statement)'),
    ('التفاصيل (المصروفات)', 'Details (Expenses)'),
    ('بنود أمر الشراء', 'PO Line Items'),
    ('بنود الفاتورة', 'Invoice Line Items'),
    ('الشركة', 'Company'),
    ('القسم', 'Department'),
    ('السنة', 'Year'),
    ('الشهر', 'Month'),
    ('الموظف', 'Employee'),
    ('الراتب الأساسي', 'Basic Salary'),
    ('البدلات', 'Allowances'),
    ('الخصومات', 'Deductions'),
    ('صافي الراتب', 'Net Salary'),
    ('الأصل', 'Asset'),
    ('فئة الأصل', 'Asset Category'),
    ('قيمة الشراء', 'Purchase Value'),
    ('تاريخ الشراء', 'Purchase Date'),
    ('العمر الإنتاجي', 'Useful Life'),
    ('قيمة الإهلاك', 'Depreciation Value'),
    ('القيمة الدفترية', 'Book Value'),
    ('فترة الإقرار', 'Return Period'),
    ('مدفوعات', 'Payments'),
    ('المستلم', 'Recipient'),
    ('فئة المصروف', 'Expense Category'),
    ('وسيلة الدفع', 'Payment Method'),
    ('تاريخ المصروف', 'Expense Date'),
    ('تاريخ الفاتورة', 'Invoice Date'),
    ('تاريخ كشف الحساب', 'Statement Date'),
    ('تاريخ الإيصال', 'Receipt Date'),
    ('فترة كشف الحساب', 'Statement Period'),
    ('الرصيد الافتتاحي', 'Opening Balance'),
    ('الرصيد الختامي', 'Closing Balance'),
    ('عدد المعاملات', 'Transaction Count'),
    ('الرقم', 'Number'),
    ('البيان', 'Description'),
    ('المبلغ', 'Amount'),
    ('الرصيد', 'Balance'),
    ('السعر', 'Price'),
    ('الكمية', 'Quantity'),
    ('الإجمالي', 'Total'),
    ('الإجمالي قبل الضريبة', 'Subtotal'),
    ('ضريبة القيمة المضافة', 'VAT'),
    ('المورد', 'Vendor'),
    ('العميل', 'Customer'),
    ('رقم أمر الشراء', 'PO Number'),
    ('رقم الفاتورة', 'Invoice Number'),
    ('رقم كشف الحساب', 'Statement Number'),
    ('رقم الإيصال', 'Receipt Number'),
    ('رقم المرجع', 'Reference Number'),

    # JS notify / status messages
    ('خطأ في التحميل', 'Loading error'),
    ('تعذّر تحميل التفاصيل', 'Failed to load details'),
    ('تم حفظ الملاحظات', 'Notes saved'),
    ('فشل حفظ الملاحظات', 'Failed to save notes'),
    ('رُفع', 'Uploaded'),

    # Buttons / actions
    ('حفظ الملاحظات', 'Save Notes'),
    ('تحميل المرفق', 'Download Attachment'),
    ('رجوع', 'Back'),

    # Empty / labels
    ('لا توجد بنود مسجّلة', 'No line items recorded'),
    ('لا توجد ملاحظات', 'No notes'),
    ('أضف ملاحظاتك...', 'Add your notes...'),
    ('عرض', 'Showing'),
    ('من', 'of'),
    ('صفحة', 'Page'),
    ('ملاحظات', 'Notes'),
    ('ملاحظات داخلية', 'Internal Notes'),

    # Commonly seen
    ('السابق', 'Previous'),
    ('التالي', 'Next'),
    ('متجر', 'Store'),
    ('الحالة', 'Status'),
]


def esc_trans(en: str) -> str:
    return en.replace("\\", "\\\\").replace("'", r"\'")


def wrap_text_between_tags(html: str) -> tuple[str, int]:
    n = 0
    for ar, en in PHRASES:
        pat = re.compile(r'(>\s*)' + re.escape(ar) + r'(\s*<)', re.DOTALL)
        new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
        html = new_html
        n += count
    return html, n


def wrap_block_headers(html: str) -> tuple[str, int]:
    n = 0
    for ar, en in PHRASES:
        pat = re.compile(
            r'(\{%\s*\s?block\s+(?:page_title|breadcrumb_parent|breadcrumb_current|title)\s*%\})\s*'
            + re.escape(ar)
            + r'\s*(\{%\s*\s?endblock\s*%\})'
        )
        new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
        html = new_html
        n += count
    return html, n


def wrap_html_attributes(html: str) -> tuple[str, int]:
    n = 0
    for attr in ('placeholder', 'title', 'aria-label', 'alt'):
        for ar, en in PHRASES:
            pat = re.compile(r'(' + attr + r'=")' + re.escape(ar) + r'(")')
            new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
            html = new_html
            n += count
    return html, n


def wrap_alpine_ternary(html: str) -> tuple[str, int]:
    n = 0
    for ar, en in PHRASES:
        pat = re.compile(r"(x-text=\"[^\"]*?)'" + re.escape(ar) + r"'", re.DOTALL)
        while True:
            new_html, count = pat.subn(r"\1'" + esc_trans(en) + r"'", html)
            if count == 0:
                break
            html = new_html
            n += count
    return html, n


def wrap_js_notify(html: str) -> tuple[str, int]:
    n = 0
    for caller in ('notify', 'alert', 'confirm'):
        for ar, en in PHRASES:
            pat = re.compile(r'(' + caller + r'\(\s*)' + r"'" + re.escape(ar) + r"'")
            new_html, count = pat.subn(r"\1'" + esc_trans(en) + r"'", html)
            html = new_html
            n += count
    return html, n


def ensure_load_i18n(html: str) -> str:
    if '{% load i18n %}' in html:
        return html
    m = re.search(r'(\{%\s*extends[^%]+%\})', html)
    if m:
        return html[:m.end()] + '\n{% load i18n %}' + html[m.end():]
    return '{% load i18n %}\n' + html


def main():
    grand = 0
    for rel in TARGETS:
        path = BASE / rel
        if not path.exists():
            continue
        original = path.read_text(encoding='utf-8')
        out = ensure_load_i18n(original)
        out, n_blk = wrap_block_headers(out)
        out, n_txt = wrap_text_between_tags(out)
        out, n_at  = wrap_html_attributes(out)
        out, n_xt  = wrap_alpine_ternary(out)
        out, n_nf  = wrap_js_notify(out)
        if out != original:
            path.write_text(out, encoding='utf-8')
            print(f"[ok] {rel}: blk={n_blk} txt={n_txt} attr={n_at} alpine={n_xt} js={n_nf}")
            grand += n_blk + n_txt + n_at + n_xt + n_nf
        else:
            print(f"[--] {rel}")
    print(f"\nGrand: {grand}")


if __name__ == '__main__':
    main()
