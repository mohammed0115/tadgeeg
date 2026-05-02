"""Translations for document detail templates Phase."""
import polib
AR_PATH = 'locale/ar/LC_MESSAGES/django.po'
EN_PATH = 'locale/en/LC_MESSAGES/django.po'

AR = {
    'Bank': 'البنك',
    'Balance Match': 'تطابق الرصيد',
    'Purpose': 'الغرض',
    'Cost': 'التكلفة',
    'Unit': 'الوحدة',
    'Seller': 'البائع',
    'Yes': 'نعم',
    'No': 'لا',
    'Taxpayer': 'الممول',
    'Standard Rated Sales': 'المبيعات الخاضعة',
    'Late Filing': 'تأخر التقديم',
    'Details (Transactions)': 'التفاصيل (المعاملات)',
    'Add your notes...': 'أضِف ملاحظاتك...',
    'Account Number': 'رقم الحساب',
    'Account Name': 'اسم الحساب',
    'Total Credits': 'إجمالي الإيداعات',
    'Total Debits': 'إجمالي السحوبات',
    'Matched': 'متطابق',
    'Not matched': 'غير متطابق',
    'Transaction Count': 'عدد المعاملات',
    'Credit': 'دائن',
    'Debit': 'مدين',
    'Balance': 'الرصيد',
    'Details (Expense Lines)': 'التفاصيل (بنود المصروفات)',
    'Report Number': 'رقم التقرير',
    'Employee': 'الموظف',
    'Submission Date': 'تاريخ التقديم',
    'Claimed Amount': 'المبلغ المطالَب',
    'VAT Included': 'الضريبة المُدرَجة',
    'Missing Receipts': 'إيصالات مفقودة',
    'Receipt': 'إيصال',
    'Fixed Asset Record Details': 'تفاصيل سجل الأصول الثابتة',
    'Details (Assets)': 'التفاصيل (الأصول)',
    'Fiscal Year': 'السنة المالية',
    'Asset Count': 'عدد الأصول',
    'Total Depreciation': 'إجمالي الإهلاك',
    'Negative Values': 'قيم سالبة',
    'Over Depreciated': 'إهلاك مفرط',
    'Missing ID': 'بدون معرّف',
    'Classification': 'التصنيف',
    'Accumulated Depreciation': 'الإهلاك المتراكم',
    'Payroll Slips': 'كشوف الرواتب',
    'Details (Employees)': 'التفاصيل (الموظفون)',
    'Payroll Slip': 'كشف الراتب',
    'Payment Date': 'تاريخ الدفع',
    'Total Gross Salary': 'إجمالي الرواتب',
    'Total Net Salary': 'صافي الرواتب',
    'Deductions': 'الخصومات',
    'Gross Salary': 'الراتب الإجمالي',
    'Net': 'الصافي',
    'PO Number': 'رقم أمر الشراء',
    'PO Date': 'تاريخ أمر الشراء',
    'Requester': 'مقدّم الطلب',
    'Delivery Date': 'تاريخ التسليم',
    'Item Name': 'اسم الصنف',
    'Approved by': 'المعتمد',
    'Details (Receipt Items)': 'التفاصيل (بنود الإيصال)',
    'Receipt Number': 'رقم الإيصال',
    'Seller VAT Number': 'الرقم الضريبي للبائع',
    'Customer': 'العميل',
    'Filing Date': 'تاريخ التقديم',
    'days': 'يوم',
    'On time': 'في الوقت',
    'You do not have permission to access platform management.': 'ليس لديك صلاحية للوصول إلى إدارة المنصّة.',
    'VAT Return Details': 'تفاصيل إقرار الضريبة',
    'Expense Report Details': 'تفاصيل تقرير المصروفات',
    'Payroll Details': 'تفاصيل كشف الراتب',
    'Purchase Order Details': 'تفاصيل أمر الشراء',
    'Sales Receipt Details': 'تفاصيل إيصال البيع',
    'Bank Statement Details': 'تفاصيل كشف الحساب البنكي',
    'Details (Statement)': 'التفاصيل (كشف الحساب)',
    'Details (Line Items)': 'التفاصيل (البنود)',
    'Details': 'التفاصيل',
    'Fixed Assets': 'الأصول الثابتة',
    'Bank Statements': 'كشوف الحسابات البنكية',
    'Purchase Orders': 'أوامر الشراء',
    'VAT Returns': 'إقرارات الضريبة',
    'Expense Reports': 'تقارير المصروفات',
    'Sales Receipts': 'إيصالات البيع',
    'Uploaded:': 'رُفع:',
    'Loading error': 'خطأ في التحميل',
    'Failed to load details': 'تعذّر تحميل التفاصيل',
    'Notes saved': 'تم حفظ الملاحظات',
    'Failed to save notes': 'فشل حفظ الملاحظات',
    'Save Notes': 'حفظ الملاحظات',
    'Download Attachment': 'تحميل المرفق',
    'No line items recorded': 'لا توجد بنود مسجّلة',
    'No notes': 'لا توجد ملاحظات',
    'Showing': 'عرض',
    'Notes': 'الملاحظات',
    'Internal Notes': 'ملاحظات داخلية',
    'Store': 'متجر',
    'Approved': 'معتمد',
    'Saved': 'تم الحفظ',
    'Error': 'خطأ',
    'Item Name': 'اسم الصنف',
    'Quantity': 'الكمية',
    'Unit Price': 'سعر الوحدة',
    'Subtotal': 'الإجمالي قبل الضريبة',
    'VAT': 'الضريبة',
    'Type': 'النوع',
    'VAT Rate': 'نسبة الضريبة',
    'VAT Amount': 'مبلغ الضريبة',
    'Duplicate Status': 'حالة التكرار',
    'Valid': 'صحيح',
    'Invalid': 'غير صحيح',
    'Missing': 'مفقود',
    'Receipt': 'إيصال',
    'Allowances': 'البدلات',
    'Net Salary': 'صافي الراتب',
    'Cost Center': 'مركز التكلفة',
    'VAT Number': 'الرقم الضريبي',
    'Vendor': 'المورد',
    'Department': 'القسم',
    'Total': 'الإجمالي',
    'Description': 'الوصف',
    'Date': 'التاريخ',
    'CR Number': 'رقم السجل التجاري',
    'From': 'من',
    'To': 'إلى',
    'Opening Balance': 'الرصيد الافتتاحي',
    'Closing Balance': 'الرصيد الختامي',
    'Output VAT': 'ضريبة المخرجات',
    'Input VAT': 'ضريبة المدخلات',
    'Net VAT Payable': 'صافي الضريبة المستحقّة',
    'Due Date': 'تاريخ الاستحقاق',
    'Page': 'صفحة',
    'Status': 'الحالة',
    'Employee Count': 'عدد الموظفين',
    'Book Value': 'القيمة الدفترية',
    'Category': 'الفئة',
    'Amount': 'المبلغ',
    'ID': 'المعرّف',
    'Name': 'الاسم',
    'Code': 'الرمز',
    'Quantity': 'الكمية',
    'Unit Price': 'سعر الوحدة',
    'Total Cost': 'التكلفة الإجمالية',
    'Allowances': 'البدلات',
}

ar = polib.pofile(AR_PATH)
applied, missing = 0, []
for entry in ar:
    if entry.obsolete or entry.msgid_plural:
        continue
    if not (('fuzzy' in entry.flags) or (not entry.msgstr and entry.msgid != "")):
        continue
    if entry.msgid in AR:
        entry.msgstr = AR[entry.msgid]
        if 'fuzzy' in entry.flags:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        applied += 1
    else:
        missing.append(entry.msgid)
ar.save(AR_PATH)
print(f"AR applied: {applied}, missing: {len(missing)}")
for m in missing:
    print(f"  MISS: {m!r}")

en = polib.pofile(EN_PATH)
fixed = 0
for entry in en:
    if entry.obsolete or entry.msgid_plural:
        continue
    is_fuzzy = 'fuzzy' in entry.flags
    is_empty = not entry.msgstr and entry.msgid != ""
    if is_fuzzy or is_empty:
        entry.msgstr = entry.msgid
        if is_fuzzy:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        fixed += 1
en.save(EN_PATH)
print(f"EN fixed: {fixed}")

for path, name in [(AR_PATH, 'AR'), (EN_PATH, 'EN')]:
    p = polib.pofile(path)
    e = sum(1 for x in p if not x.msgstr and not x.obsolete and x.msgid != "" and not x.msgid_plural)
    f = sum(1 for x in p if 'fuzzy' in x.flags and not x.obsolete)
    print(f"{name}: empty={e}, fuzzy={f}")
