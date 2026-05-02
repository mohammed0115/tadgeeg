"""Wrap hardcoded Arabic strings in platform_admin templates with {% trans %}.

Operates only on the explicit `TARGETS` list. Handles:
  • {% block X %}عربي{% endblock %}
  • text content between tags: >عربي<
  • placeholder="عربي"
  • title="عربي" / :title="'عربي'"
  • x-text="'عربي'" / x-text="cond ? 'عربي' : 'عربي'"
  • notify('عربي', ...)
  • alert('عربي') / confirm('عربي')

Anything not in PHRASES is left for manual review.
"""
import re
from pathlib import Path

TARGETS = [
    'templates/platform_admin/seo.html',
    'templates/platform_admin/cms/homepage.html',
    'templates/platform_admin/cms/pages.html',
    'templates/platform_admin/cms/about.html',
    'templates/platform_admin/cms/pricing.html',
    'templates/platform_admin/cms/faq.html',
    'templates/platform_admin/cms/services.html',
    'templates/platform_admin/cms/intro_video.html',
    'templates/platform_admin/settings.html',
    'templates/platform_admin/monitoring.html',
    'templates/platform_admin/organizations.html',
    'templates/platform_admin/media.html',
]

# Arabic phrase → English msgid. Order matters: longer phrases first.
PHRASES = [
    # Bilingual labels (longer specific ones go first)
    ('العنوان الفرعي (EN)', 'Subtitle (EN)'),
    ('العنوان الفرعي (عربي)', 'Subtitle (Arabic)'),
    ('المحتوى الرئيسي (EN)', 'Main Content (EN)'),
    ('المحتوى الرئيسي (عربي)', 'Main Content (Arabic)'),
    ('نص CTA الرئيسي (EN)', 'Primary CTA Text (EN)'),
    ('نص CTA الثانوي (EN)', 'Secondary CTA Text (EN)'),
    ('اسم الخطة (EN)', 'Plan Name (EN)'),
    ('اسم الخطة (عربي)', 'Plan Name (Arabic)'),
    ('السؤال (EN)', 'Question (EN)'),
    ('السؤال (عربي)', 'Question (Arabic)'),
    ('الجواب (EN)', 'Answer (EN)'),
    ('الجواب (عربي)', 'Answer (Arabic)'),
    ('الوصف (EN)', 'Description (EN)'),
    ('الوصف (عربي)', 'Description (Arabic)'),
    ('العنوان (EN)', 'Title (EN)'),
    ('العنوان (عربي)', 'Title (Arabic)'),
    ('المحتوى (EN)', 'Content (EN)'),
    ('المحتوى (عربي)', 'Content (Arabic)'),
    ('الرسالة (EN)', 'Mission (EN)'),
    ('الرسالة (Mission)', 'Mission'),
    ('الرؤية (EN)', 'Vision (EN)'),
    ('الرؤية (Vision)', 'Vision'),
    ('نص زر التشغيل (عربي)', 'Play Button Text (Arabic)'),
    ('الأيقونة (Lucide)', 'Icon (Lucide)'),
    ('السعر (SAR)', 'Price (SAR)'),
    ('رابط الفيديو (YouTube / Vimeo)', 'Video URL (YouTube / Vimeo)'),

    # Page-specific page_title / breadcrumb_current values
    ('صفحة من نحن', 'About Page'),
    ('خطط الأسعار', 'Pricing Plans'),
    ('الفيديو التعريفي', 'Intro Video'),
    ('إدارة الخدمات', 'Service Management'),
    ('إدارة المنظمات', 'Organization Management'),
    ('المنظمات', 'Organizations'),
    ('إدارة المحتوى', 'Content Management'),
    ('الصفحات', 'Pages'),
    ('الأسعار', 'Pricing'),

    # H1 / page-description blocks
    ('تحرير صفحة من نحن', 'Edit About Page'),
    ('تعديل محتوى صفحة التعريف بالشركة', 'Edit company about page content'),
    ('محتوى من نحن', 'About Content'),
    ('إدارة خطط الاشتراك والأسعار المعروضة', 'Manage subscription plans and displayed pricing'),
    ('إدارة الفيديو التعريفي للمنصة المعروض في الموقع', 'Manage the platform intro video shown on the site'),
    ('تحرير قائمة الخدمات والميزات المعروضة', 'Edit list of services and features shown'),
    ('إدارة الأسئلة والأجوبة المعروضة على الموقع', 'Manage questions and answers shown on the site'),
    ('إدارة جميع المنظمات المسجلة في المنصة', 'Manage all organizations registered on the platform'),
    ('الإعدادات العامة لمنصة Get Solution', 'General settings for the Get Solution platform'),
    ('جميع صفحات CMS والمحتوى المنشور', 'All CMS pages and published content'),
    ('رفع وإدارة الصور والملفات', 'Upload and manage images and files'),
    ('إعدادات الفيديو', 'Video Settings'),

    # Pricing-specific
    ('الأكثر شيوعاً', 'Most Popular'),
    ('فترة الفوترة', 'Billing Period'),
    ('شهري', 'Monthly'),
    ('سنوي', 'Annual'),
    ('شهر', 'month'),
    ('مخفي', 'Hidden'),
    ('إخفاء', 'Hide'),
    ('تفعيل', 'Activate'),

    # Stats / cards / sections
    ('الإحصائيات', 'Stats'),
    ('الشركاء والعملاء', 'Partners & Customers'),
    ('إضافة شعار', 'Add Logo'),
    ('اسم الشركة', 'Company Name'),
    ('رابط الصورة المصغّرة', 'Thumbnail URL'),
    ('رابط صورة Hero', 'Hero Image URL'),
    ('رابط الصورة', 'Image URL'),
    ('تاريخ التأسيس', 'Founded Date'),
    ('عدد الموظفين', 'Employee Count'),
    ('مدة الفيديو', 'Video Duration'),
    ('عرض الفيديو التعريفي في الموقع', 'Show intro video on the site'),
    ('معاينة', 'Preview'),
    ('ترتيب العرض', 'Display Order'),

    # Empty / placeholder messages
    ('لا توجد إحصائيات. انقر إضافة إحصائية.', 'No stats yet. Click Add Stat.'),
    ('لا توجد إحصائيات. انقر إضافة إحصائية', 'No stats yet. Click Add Stat'),
    ('لا توجد خطط أسعار بعد.', 'No pricing plans yet.'),
    ('لا توجد منظمات مطابقة', 'No matching organizations'),
    ('لا توجد صفحات مطابقة', 'No matching pages'),
    ('لا توجد ملفات بعد', 'No files yet'),
    ('لا توجد إعدادات في هذه المجموعة', 'No settings in this group'),
    ('لا توجد أسئلة. انقر "إضافة سؤال" للبدء.', 'No questions. Click "Add Question" to start.'),
    ('لا توجد خدمات. انقر "إضافة خدمة" للبدء.', 'No services. Click "Add Service" to start.'),

    # Notifications
    ('تعذّر تحميل الأسئلة', 'Failed to load questions'),
    ('تعذّر تحميل الخدمات', 'Failed to load services'),
    ('تعذّر تحميل المؤسسات', 'Failed to load organizations'),
    ('تم حفظ الأسئلة', 'Questions saved'),
    ('تم حفظ الخدمات', 'Services saved'),
    ('تم حفظ الإعداد', 'Setting saved'),
    ('فشل حفظ الإعداد', 'Failed to save setting'),
    ('حفظ جميع الأسئلة', 'Save All Questions'),
    ('حفظ جميع الخدمات', 'Save All Services'),
    ('حفظ الإحصائيات', 'Save Stats'),

    # Settings sidebar labels
    ('عام', 'General'),
    ('البريد الإلكتروني', 'Email'),
    ('التكاملات', 'Integrations'),
    ('الأمان', 'Security'),
    ('الإشعارات', 'Notifications'),
    ('الفوترة', 'Billing'),
    ('حساس', 'Sensitive'),

    # Filters / select options
    ('جميع الحالات', 'All Statuses'),
    ('جميع الفئات', 'All Categories'),
    ('جميع الأنواع', 'All Types'),
    ('موقوف', 'Suspended'),
    ('مسودة', 'Draft'),
    ('منشورة', 'Published'),
    ('مؤرشفة', 'Archived'),

    # Tables
    ('المنظمة', 'Organization'),
    ('الخطة', 'Plan'),
    ('تاريخ التسجيل', 'Registration Date'),
    ('إجراءات', 'Actions'),
    ('الرابط', 'URL'),
    ('آخر تحديث', 'Last Updated'),
    ('إجمالي الصفحات', 'Total Pages'),
    ('الإجمالي:', 'Total:'),
    ('الإجمالي', 'Total'),
    ('الحجم', 'Size'),
    ('الملف', 'File'),

    # Stats / counts
    ('إجمالي المؤسسات', 'Total Organizations'),
    ('المؤسسات النشطة', 'Active Organizations'),
    ('عدد المستخدمين', 'User Count'),
    ('تاريخ الإنشاء', 'Created At'),

    # Search placeholders
    ('البحث بالعنوان أو الرابط...', 'Search by title or URL...'),
    ('البحث بالاسم أو البريد الإلكتروني...', 'Search by name or email...'),
    ('البحث بالاسم...', 'Search by name...'),
    ('البحث في الأسئلة...', 'Search in questions...'),
    ('بحث باسم المؤسسة...', 'Search by organization name...'),

    # Media
    ('اسحب الملفات وأفلتها هنا', 'Drag and drop files here'),
    ('اختر ملفات', 'Choose Files'),
    ('إضافة رابط', 'Add URL'),
    ('قيد الرفع', 'Uploading'),
    ('صور', 'Images'),
    ('فيديو', 'Video'),
    ('مستندات', 'Documents'),
    ('أو', 'or'),

    # Default new-item placeholders
    ('خدمة جديدة', 'New service'),
    ('سؤال جديد', 'New question'),
    ('إضافة منظمة', 'Add Organization'),
    ('إضافة خطة جديدة', 'Add new plan'),

    # Pages/about specifics
    ('قسم الإحصائيات', 'Stats Section'),
    ('قسم الميزات', 'Features Section'),
    ('قسم الموثوقية', 'Trust Section'),
    ('قسم Hero', 'Hero Section'),

    # Specific monitoring strings
    ('حالة الخوادم والخدمات في الوقت الفعلي', 'Server and service status in real time'),
    ('جميع الخدمات تعمل', 'All services are running'),
    ('يوجد مشكلة', 'There is an issue'),
    ('يعمل بشكل طبيعي', 'Running normally'),
    ('أداء منخفض', 'Degraded performance'),
    ('جاري الفحص...', 'Checking...'),
    ('متوقف', 'Down'),
    ('المعالج CPU', 'CPU'),
    ('الذاكرة RAM', 'RAM'),
    ('القرص الصلب', 'Disk'),
    ('أنوية', 'cores'),
    ('آخر الأخطاء والتحذيرات', 'Recent errors and warnings'),
    ('عرض كل السجلات', 'View all logs'),
    ('لا توجد أخطاء مؤخراً', 'No recent errors'),
    ('مراقبة النظام', 'System Monitoring'),
    ('تعذّر تحميل بيانات المراقبة', 'Failed to load monitoring data'),

    # Organizations
    ('قائمة المؤسسات', 'Organizations List'),
    ('إجمالي المؤسسات', 'Total Organizations'),
    ('المؤسسات النشطة', 'Active Organizations'),
    ('عدد المستخدمين', 'User Count'),
    ('تاريخ الإنشاء', 'Created At'),
    ('قائمة كل المؤسسات المسجلة على المنصة', 'List of all organizations registered on the platform'),
    ('تعذّر تحميل المؤسسات', 'Failed to load organizations'),
    ('بحث باسم المؤسسة...', 'Search by organization name...'),

    # Settings
    ('إعدادات المنصة', 'Platform Settings'),
    ('الإعدادات العامة', 'General Settings'),
    ('إعدادات النظام', 'System Settings'),
    ('تعذّر تحميل الإعدادات', 'Failed to load settings'),
    ('تم حفظ الإعدادات', 'Settings saved'),

    # Media
    ('مكتبة الوسائط', 'Media Library'),
    ('رفع وسائط', 'Upload Media'),
    ('تعذّر تحميل الوسائط', 'Failed to load media'),
    ('تم رفع الملف', 'File uploaded'),
    ('فشل رفع الملف', 'File upload failed'),

    # Homepage editor (CMS)
    ('تحرير الصفحة الرئيسية', 'Edit Homepage'),
    ('تعديل محتوى الصفحة الرئيسية للمنصة', 'Edit homepage content for the platform'),
    ('قسم Hero', 'Hero Section'),
    ('عنوان Hero', 'Hero Title'),
    ('العنوان الفرعي للبانر', 'Hero Subtitle'),
    ('العنوان الفرعي', 'Subtitle'),
    ('نص CTA الرئيسي', 'Primary CTA Text'),
    ('رابط CTA الرئيسي', 'Primary CTA URL'),
    ('نص CTA الثانوي', 'Secondary CTA Text'),
    ('رابط CTA الثانوي', 'Secondary CTA URL'),
    ('نص CTA', 'CTA Text'),
    ('رابط CTA', 'CTA URL'),
    ('قسم الإحصائيات', 'Stats Section'),
    ('قسم الميزات', 'Features Section'),
    ('قسم الموثوقية', 'Trust Section'),
    ('تدقيق مالي ذكي', 'Smart financial auditing'),
    ('أتمتة الامتثال...', 'Automate compliance...'),
    ('التسمية', 'Label'),
    ('القيمة', 'Value'),

    # Pages CMS
    ('إدارة الصفحات', 'Page Management'),
    ('إنشاء صفحة جديدة', 'Create New Page'),
    ('صفحة جديدة', 'New Page'),
    ('عنوان الصفحة', 'Page Title'),
    ('محتوى الصفحة', 'Page Content'),
    ('Slug', 'Slug'),
    ('تحديد ما إذا كانت الصفحة منشورة', 'Whether the page is published'),
    ('بحث عن صفحة...', 'Search for a page...'),

    # About CMS
    ('من نحن', 'About Us'),
    ('تعديل صفحة من نحن', 'Edit About Page'),
    ('قسم من نحن', 'About Section'),
    ('قيمنا الجوهرية', 'Core Values'),
    ('رسالتنا', 'Our Mission'),
    ('رؤيتنا', 'Our Vision'),
    ('رسالتنا هي...', 'Our mission is...'),
    ('رؤيتنا هي...', 'Our vision is...'),

    # Pricing CMS
    ('خطط التسعير', 'Pricing Plans'),
    ('تعديل خطط التسعير', 'Edit Pricing Plans'),
    ('الخطة المتقدمة', 'Advanced Plan'),
    ('السعر الشهري', 'Monthly Price'),
    ('السعر السنوي', 'Annual Price'),
    ('الخطة المميزة', 'Featured Plan'),
    ('عملة', 'Currency'),
    ('الميزات المضمنة', 'Included Features'),
    ('إضافة ميزة جديدة', 'Add new feature'),
    ('نص الميزة', 'Feature Text'),
    ('وصف الميزة', 'Feature Description'),

    # FAQ CMS
    ('الأسئلة الشائعة', 'FAQ'),
    ('تعديل الأسئلة الشائعة', 'Edit FAQ'),
    ('فئة الأسئلة', 'Question Category'),
    ('السؤال بالعربية؟', 'Question in Arabic?'),
    ('الجواب بالعربية...', 'Answer in Arabic...'),
    ('Question in English?', 'Question in English?'),
    ('Answer in English...', 'Answer in English...'),

    # Services CMS
    ('تعديل الخدمات', 'Edit Services'),
    ('قائمة الخدمات', 'Services List'),
    ('اسم الخدمة', 'Service Name'),
    ('وصف الخدمة...', 'Service description...'),
    ('وصف الخدمة', 'Service description'),
    ('أيقونة الخدمة', 'Service Icon'),

    # Intro video CMS
    ('فيديو تعريفي', 'Intro Video'),
    ('تعديل الفيديو التعريفي', 'Edit Intro Video'),
    ('شاهد كيف يعمل', 'See how it works'),
    ('وصف مختصر بالعربية...', 'Short description in Arabic...'),
    ('شاهد الفيديو', 'Watch the video'),
    ('رابط الفيديو', 'Video URL'),
    ('عنوان الفيديو', 'Video Title'),

    # SEO (already mostly done)
    ('إعدادات SEO', 'SEO Settings'),
    ('تحسين محركات البحث', 'Search Engine Optimization'),
    ('إعدادات SEO وبيانات التعريف لكل صفحة', 'SEO settings and metadata for each page'),
    ('اختر الصفحة:', 'Select Page:'),
    ('معاينة نتيجة Google', 'Google Search Preview'),
    ('وصف الصفحة يظهر هنا...', 'Page description appears here...'),

    # Headings: management area
    ('إدارة المحتوى', 'Content Management'),
    ('الصفحة الرئيسية', 'Homepage'),

    # Action verbs / button phrases
    ('حفظ التغييرات', 'Save Changes'),
    ('حفظ كل التغييرات', 'Save All Changes'),
    ('حفظ الإعدادات', 'Save Settings'),
    ('حفظ Hero', 'Save Hero'),
    ('حفظ المحتوى', 'Save Content'),
    ('حفظ الصفحة', 'Save Page'),
    ('حفظ الخطة', 'Save Plan'),
    ('حفظ السؤال', 'Save Question'),
    ('حفظ الخدمة', 'Save Service'),
    ('حفظ الفيديو', 'Save Video'),
    ('حفظ الإعدادات', 'Save Settings'),
    ('حفظ', 'Save'),
    ('إلغاء', 'Cancel'),
    ('تأكيد', 'Confirm'),
    ('حذف', 'Delete'),
    ('تعديل', 'Edit'),
    ('عرض', 'View'),
    ('إضافة', 'Add'),
    ('تحديث', 'Update'),
    ('بحث', 'Search'),
    ('إغلاق', 'Close'),
    ('العودة', 'Back'),
    ('التالي', 'Next'),
    ('السابق', 'Previous'),
    ('نشر', 'Publish'),
    ('مسوّدة', 'Draft'),
    ('منشور', 'Published'),
    ('غير نشط', 'Inactive'),
    ('نشط', 'Active'),

    # Generic labels
    ('الاسم', 'Name'),
    ('العنوان', 'Title'),
    ('الوصف', 'Description'),
    ('الترتيب', 'Order'),
    ('التاريخ', 'Date'),
    ('الحالة', 'Status'),
    ('النوع', 'Type'),
    ('الفئة', 'Category'),
    ('السعر', 'Price'),
    ('السؤال', 'Question'),
    ('الإجابة', 'Answer'),

    # Status / progress
    ('جاري الحفظ...', 'Saving...'),
    ('جاري التحميل...', 'Loading...'),
    ('جاري التحديث...', 'Updating...'),
    ('جاري الإنشاء...', 'Creating...'),
    ('جاري الحذف...', 'Deleting...'),

    # Notifications / feedback
    ('تم الحفظ بنجاح', 'Saved successfully'),
    ('تم الحذف بنجاح', 'Deleted successfully'),
    ('تم التحديث بنجاح', 'Updated successfully'),
    ('فشل الحفظ', 'Save failed'),
    ('فشل الحذف', 'Delete failed'),
    ('فشل التحديث', 'Update failed'),
    ('فشل التحميل', 'Load failed'),

    # Empty states
    ('لا توجد بيانات', 'No data'),
    ('لا توجد نتائج', 'No results'),

    # Specific platform admin headings (kept after seo)
    ('عنوان الصفحة', 'Page title'),
]


def esc_trans(en: str) -> str:
    """Escape an English msgid so it's safe inside `{% trans 'X' %}`."""
    return en.replace("\\", "\\\\").replace("'", r"\'")


def wrap_text_between_tags(html: str) -> tuple[str, int]:
    """Replace text content (>arabic<) — supports leading/trailing whitespace and newlines."""
    n = 0
    for ar, en in PHRASES:
        # `>` then optional whitespace/newlines then the phrase then optional ws then `<`
        pat = re.compile(r'(>\s*)' + re.escape(ar) + r'(\s*<)', re.DOTALL)
        new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
        html = new_html
        n += count
    return html, n


def wrap_block_headers(html: str) -> tuple[str, int]:
    """Convert {% block X %}arabic{% endblock %} headers."""
    n = 0
    for ar, en in PHRASES:
        pat = re.compile(
            r'({% block (?:page_title|breadcrumb_parent|breadcrumb_current|title) %})\s*'
            + re.escape(ar)
            + r'\s*({% endblock %})'
        )
        new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
        html = new_html
        n += count
    return html, n


def wrap_html_attributes(html: str) -> tuple[str, int]:
    """Replace placeholder/title/aria-label attributes with arabic content."""
    n = 0
    attrs = ['placeholder', 'title', 'aria-label', 'alt']
    for attr in attrs:
        for ar, en in PHRASES:
            pat = re.compile(
                r'(' + attr + r'=")' + re.escape(ar) + r'(")'
            )
            new_html, count = pat.subn(r"\1{% trans '" + esc_trans(en) + r"' %}\2", html)
            html = new_html
            n += count
    return html, n


def wrap_alpine_ternary(html: str) -> tuple[str, int]:
    """Convert `x-text="cond ? 'arA' : 'arB'"` so each Arabic literal becomes a server-rendered translated literal."""
    n = 0
    for ar, en in PHRASES:
        # Replace single-quoted Arabic literal anywhere inside x-text= "..."
        # Cheap approach: any single-quoted occurrence of ar inside a single-line attribute.
        pat = re.compile(r"(x-text=\"[^\"]*?)'" + re.escape(ar) + r"'", re.DOTALL)
        # Apply iteratively until no more matches (since multiple may exist in one attr)
        while True:
            new_html, count = pat.subn(r"\1'" + esc_trans(en) + r"'", html)
            if count == 0:
                break
            html = new_html
            n += count
    return html, n


def wrap_js_notify(html: str) -> tuple[str, int]:
    """Replace notify('arabic', ...) and alert('arabic') with the English literal."""
    n = 0
    js_callers = ['notify', 'alert', 'confirm']
    for caller in js_callers:
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
    base = Path('/home/mohamed/tadgeeg')
    grand_total = 0
    for rel in TARGETS:
        path = base / rel
        if not path.exists():
            print(f"[skip] {rel}")
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
            total = n_blk + n_txt + n_at + n_xt + n_nf
            print(f"[ok] {rel}: blk={n_blk} txt={n_txt} attr={n_at} alpine={n_xt} js={n_nf}  (={total})")
            grand_total += total
        else:
            print(f"[--] {rel}")
    print(f"\nGrand total: {grand_total}")


if __name__ == '__main__':
    main()
