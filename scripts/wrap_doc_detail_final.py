"""Final pass: wrap ALL remaining Arabic in document detail templates."""
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')

# (filename, old, new) — applied as plain str.replace, all occurrences.
EDITS = [
    # ── tabs that the wrapper missed ──
    ('bank_statement_detail.html',
     '                التفاصيل (المعاملات)',
     "                {% trans 'Details (Transactions)' %}"),
    ('expense_report_detail.html',
     '                التفاصيل (بنود المصروفات)',
     "                {% trans 'Details (Expense Lines)' %}"),
    ('vat_return_detail.html',
     '                التفاصيل ()',
     "                {% trans 'Details' %}"),
    ('payroll_detail.html',
     '                التفاصيل (الموظفون)',
     "                {% trans 'Details (Employees)' %}"),
    ('purchase_order_detail.html',
     '                التفاصيل (البنود)',
     "                {% trans 'Details (Line Items)' %}"),
    ('sales_receipt_detail.html',
     '                التفاصيل (البنود)',
     "                {% trans 'Details (Line Items)' %}"),

    # ── block titles with extra spaces ──
    ('vat_return_detail.html',
     '{%  block title %}تفاصيل الإقرار الضريبي{%  endblock %}',
     "{%  block title %}{% trans 'VAT Return Details' %}{%  endblock %}"),
    ('vat_return_detail.html',
     '>الإقرارات الضريبية<',
     ">{% trans 'VAT Returns' %}<"),
    ('expense_report_detail.html',
     '{%  block title %}تفاصيل تقرير المصروفات{%  endblock %}',
     "{%  block title %}{% trans 'Expense Report Details' %}{%  endblock %}"),
    ('expense_report_detail.html',
     '>تقارير المصروفات<',
     ">{% trans 'Expense Reports' %}<"),
    ('payroll_detail.html',
     '{%  block title %}تفاصيل كشف الرواتب{%  endblock %}',
     "{%  block title %}{% trans 'Payroll Details' %}{%  endblock %}"),
    ('payroll_detail.html',
     '>كشوف الرواتب<',
     ">{% trans 'Payroll Slips' %}<"),
    ('purchase_order_detail.html',
     '{%  block title %}تفاصيل أمر الشراء{%  endblock %}',
     "{%  block title %}{% trans 'Purchase Order Details' %}{%  endblock %}"),
    ('purchase_order_detail.html',
     '>أوامر الشراء<',
     ">{% trans 'Purchase Orders' %}<"),
    ('sales_receipt_detail.html',
     '{%  block title %}تفاصيل إيصال البيع{%  endblock %}',
     "{%  block title %}{% trans 'Sales Receipt Details' %}{%  endblock %}"),
    ('sales_receipt_detail.html',
     '>إيصالات البيع<',
     ">{% trans 'Sales Receipts' %}<"),

    # ── expense_report JS arrays ──
    ('expense_report_detail.html',
     "['رقم التقرير', this.doc.report_number],['الموظف', this.doc.employee_name],",
     "[\"{% trans 'Report Number' %}\", this.doc.report_number],[\"{% trans 'Employee' %}\", this.doc.employee_name],"),
    ('expense_report_detail.html',
     "['القسم', this.doc.department],['الغرض', this.doc.purpose],",
     "[\"{% trans 'Department' %}\", this.doc.department],[\"{% trans 'Purpose' %}\", this.doc.purpose],"),
    ('expense_report_detail.html',
     "['من', this.doc.report_period_from],['إلى', this.doc.report_period_to],",
     "[\"{% trans 'From' %}\", this.doc.report_period_from],[\"{% trans 'To' %}\", this.doc.report_period_to],"),
    ('expense_report_detail.html',
     "['تاريخ التقديم', this.doc.submitted_date],['المبلغ المطالَب', this.fmtNum(this.doc.total_claimed)],",
     "[\"{% trans 'Submission Date' %}\", this.doc.submitted_date],[\"{% trans 'Claimed Amount' %}\", this.fmtNum(this.doc.total_claimed)],"),
    ('expense_report_detail.html',
     "['VAT المدرجة', this.fmtNum(this.doc.vat_included)],['إيصالات مفقودة', this.doc.missing_receipts_count || 0],",
     "[\"{% trans 'VAT Included' %}\", this.fmtNum(this.doc.vat_included)],[\"{% trans 'Missing Receipts' %}\", this.doc.missing_receipts_count || 0],"),
    ('expense_report_detail.html',
     "get itemCols() { return ['التاريخ','الفئة','الوصف','المبلغ','إيصال']; }",
     "get itemCols() { return [\"{% trans 'Date' %}\",\"{% trans 'Category' %}\",\"{% trans 'Description' %}\",\"{% trans 'Amount' %}\",\"{% trans 'Receipt' %}\"]; }"),

    # ── purchase_order JS arrays ──
    ('purchase_order_detail.html',
     "['رقم الأمر', this.doc.po_number],['تاريخ الأمر', this.doc.po_date],",
     "[\"{% trans 'PO Number' %}\", this.doc.po_number],[\"{% trans 'PO Date' %}\", this.doc.po_date],"),
    ('purchase_order_detail.html',
     "['المورد', this.doc.vendor_name],['الرقم الضريبي', this.doc.vendor_vat_number],",
     "[\"{% trans 'Vendor' %}\", this.doc.vendor_name],[\"{% trans 'VAT Number' %}\", this.doc.vendor_vat_number],"),
    ('purchase_order_detail.html',
     "['مقدم الطلب', this.doc.requester_name],['القسم', this.doc.department],",
     "[\"{% trans 'Requester' %}\", this.doc.requester_name],[\"{% trans 'Department' %}\", this.doc.department],"),
    ('purchase_order_detail.html',
     "['مركز التكلفة', this.doc.cost_center],['الإجمالي', this.fmtNum(this.doc.total_amount) + ' ' + (this.doc.currency||'SAR')],",
     "[\"{% trans 'Cost Center' %}\", this.doc.cost_center],[\"{% trans 'Total' %}\", this.fmtNum(this.doc.total_amount) + ' ' + (this.doc.currency||'SAR')],"),
    ('purchase_order_detail.html',
     "['VAT', this.fmtNum(this.doc.vat_amount)],['تاريخ التسليم', this.doc.delivery_date],",
     "['VAT', this.fmtNum(this.doc.vat_amount)],[\"{% trans 'Delivery Date' %}\", this.doc.delivery_date],"),
    ('purchase_order_detail.html',
     "{ key: 'item_name',   label: 'اسم الصنف' },",
     "{ key: 'item_name',   label: \"{% trans 'Item Name' %}\" },"),
    ('purchase_order_detail.html',
     "{ key: 'description', label: 'الوصف' },",
     "{ key: 'description', label: \"{% trans 'Description' %}\" },"),
    ('purchase_order_detail.html',
     "{ key: 'qty',         label: 'الكمية',       fmt: 'num' },",
     "{ key: 'qty',         label: \"{% trans 'Quantity' %}\",       fmt: 'num' },"),
    ('purchase_order_detail.html',
     "{ key: 'unit',        label: 'الوحدة' },",
     "{ key: 'unit',        label: \"{% trans 'Unit' %}\" },"),
    ('purchase_order_detail.html',
     "{ key: 'unit_price',  label: 'سعر الوحدة',   fmt: 'money' },",
     "{ key: 'unit_price',  label: \"{% trans 'Unit Price' %}\",   fmt: 'money' },"),
    ('purchase_order_detail.html',
     "{ key: 'subtotal',    label: 'المبلغ قبل الضريبة', fmt: 'money' },",
     "{ key: 'subtotal',    label: \"{% trans 'Subtotal' %}\", fmt: 'money' },"),
    ('purchase_order_detail.html',
     "{ key: 'vat_amount',  label: 'الضريبة',      fmt: 'money' },",
     "{ key: 'vat_amount',  label: \"{% trans 'VAT' %}\",      fmt: 'money' },"),
    ('purchase_order_detail.html',
     "{ key: 'total',       label: 'الإجمالي',     fmt: 'money' },",
     "{ key: 'total',       label: \"{% trans 'Total' %}\",     fmt: 'money' },"),
    ('purchase_order_detail.html',
     "{ key: 'status',      label: 'الحالة' },",
     "{ key: 'status',      label: \"{% trans 'Status' %}\" },"),
    ('purchase_order_detail.html',
     "{ key: 'approved_by', label: 'المعتمد' },",
     "{ key: 'approved_by', label: \"{% trans 'Approved by' %}\" },"),
    ('purchase_order_detail.html',
     "{ key: 'notes',       label: 'ملاحظات' },",
     "{ key: 'notes',       label: \"{% trans 'Notes' %}\" },"),

    # ── vat_return JS arrays ──
    ('vat_return_detail.html',
     "['الممول', this.doc.taxpayer_name],['الرقم الضريبي', this.doc.vat_number],",
     "[\"{% trans 'Taxpayer' %}\", this.doc.taxpayer_name],[\"{% trans 'VAT Number' %}\", this.doc.vat_number],"),
    ('vat_return_detail.html',
     "['رقم السجل', this.doc.cr_number],['من', this.doc.period_from],",
     "[\"{% trans 'CR Number' %}\", this.doc.cr_number],[\"{% trans 'From' %}\", this.doc.period_from],"),
    ('vat_return_detail.html',
     "['إلى', this.doc.period_to],['تاريخ التقديم', this.doc.filing_date],",
     "[\"{% trans 'To' %}\", this.doc.period_to],[\"{% trans 'Filing Date' %}\", this.doc.filing_date],"),
]

# Generic patterns to apply across all detail files via re.sub.
# Each tuple: (regex, replacement).
GENERIC = [
    # JS array literals where label is Arabic. Most common form:
    # [<arabic-string>, this.doc.<field>] or this.fmtNum(...).
    # Replace any `'arabic'` literal that's the first arg in such pairs.
]


def main():
    base_dir = BASE / 'templates' / 'documents' / 'detail'
    grand = 0
    by_file = {}
    for fname, old, new in EDITS:
        path = base_dir / fname
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        if old in text:
            new_text = text.replace(old, new)
            path.write_text(new_text, encoding='utf-8')
            by_file[fname] = by_file.get(fname, 0) + 1
            grand += 1
    for f, n in sorted(by_file.items()):
        print(f"[ok] {f}: {n}")
    print(f"\nTotal: {grand}")


if __name__ == '__main__':
    main()
