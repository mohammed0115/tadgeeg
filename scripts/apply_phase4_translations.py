"""Apply translations for new Phase 4 backend i18n strings."""
import polib

AR_PATH = '/home/mohamed/tadgeeg/locale/ar/LC_MESSAGES/django.po'
EN_PATH = '/home/mohamed/tadgeeg/locale/en/LC_MESSAGES/django.po'

AR_NEW = {
    'Two-factor authentication is not enabled for this account.': 'المصادقة الثنائية غير مُفعَّلة لهذا الحساب.',
    'Identity verified.': 'تم التحقّق من الهوية.',
    'The code is required to verify before disabling.': 'الرمز مطلوب للتحقّق قبل إلغاء التفعيل.',
    'Invalid document type. Available types: %(types)s': 'نوع المستند غير صالح. الأنواع المتاحة: %(types)s',
    'For invoices use: POST /api/v1/invoices/upload/': 'للفواتير استخدم: POST /api/v1/invoices/upload/',
    'pyotp / qrcode is not available on the server.': 'مكتبتا pyotp / qrcode غير متاحتين على الخادم.',
    'pyotp is not available on the server.': 'مكتبة pyotp غير متاحة على الخادم.',
    'Code and secret are required.': 'الرمز والمفتاح السرّي مطلوبان.',
    'The code is invalid or expired.': 'الرمز غير صحيح أو منتهي الصلاحية.',
    'Two-factor authentication has been enabled successfully.': 'تم تفعيل المصادقة الثنائية بنجاح.',
    'pyotp is not available.': 'مكتبة pyotp غير متاحة.',
    'The code is required.': 'الرمز مطلوب.',
    'Two-factor authentication is not enabled.': 'المصادقة الثنائية غير مُفعَّلة.',
    'The code is incorrect.': 'الرمز غير صحيح.',
    'Two-factor authentication has been disabled.': 'تم إلغاء تفعيل المصادقة الثنائية.',
    'User does not belong to an organization.': 'المستخدم لا ينتمي إلى مؤسسة.',
    'No files were uploaded.': 'لم يتم رفع أي ملفات.',
    'Purchase order not found.': 'أمر الشراء غير موجود.',
    'Rejection reason is required.': 'سبب الرفض مطلوب.',
    'action must be approve or reject': 'يجب أن تكون قيمة action هي approve أو reject.',
    'Email or password is incorrect': 'البريد الإلكتروني أو كلمة المرور غير صحيحة',
}

ar = polib.pofile(AR_PATH)
ar_applied, ar_missing = 0, []
for entry in ar:
    if entry.obsolete or entry.msgid_plural:
        continue
    if not (('fuzzy' in entry.flags) or (not entry.msgstr and entry.msgid != "")):
        continue
    if entry.msgid in AR_NEW:
        entry.msgstr = AR_NEW[entry.msgid]
        if 'fuzzy' in entry.flags:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        ar_applied += 1
    else:
        ar_missing.append(entry.msgid)
ar.save(AR_PATH)
print(f"AR applied: {ar_applied}, missing: {len(ar_missing)}")
for m in ar_missing[:10]:
    print(f"  AR missing: {m!r}")

en = polib.pofile(EN_PATH)
en_fixed = 0
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
        en_fixed += 1
en.save(EN_PATH)
print(f"EN fixed: {en_fixed}")

for path, name in [(AR_PATH, 'AR'), (EN_PATH, 'EN')]:
    p = polib.pofile(path)
    e = sum(1 for x in p if not x.msgstr and not x.obsolete and x.msgid != "" and not x.msgid_plural)
    f = sum(1 for x in p if 'fuzzy' in x.flags and not x.obsolete)
    print(f"{name}: empty={e}, fuzzy={f}")
