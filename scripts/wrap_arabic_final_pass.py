"""Final cleanup pass for residual hardcoded Arabic in admin templates.

Surgical regex replacements for the specific patterns that the bulk wrapper
couldn't catch (JS literals, single-quoted ternaries, HTML attribute
fragments, multi-line text content).
"""
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')

# Each entry: (file_relpath, old_substring, new_substring).
# These are substring (not regex) replacements applied with str.replace.
EDITS = [
    # ── homepage.html ─────────────────────────────────────────────────────
    ('templates/platform_admin/cms/homepage.html',
     '<span class="text-emerald-500">(عربي)</span>',
     '<span class="text-emerald-500">({% trans "Arabic" %})</span>'),
    ('templates/platform_admin/cms/homepage.html',
     '            القيم الأساسية',
     '            {% trans "Core Values" %}'),
    ('templates/platform_admin/cms/homepage.html',
     "saving ? 'Saving...' : 'حفظ القيم'",
     '''saving ? "{% trans 'Saving...' %}" : "{% trans 'Save Values' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     '          تحسين محركات البحث للرئيسية',
     '          {% trans "Homepage SEO" %}'),
    ('templates/platform_admin/cms/homepage.html',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">Meta Title (عربي)</label>',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">{% trans "Meta Title (Arabic)" %}</label>'),
    ('templates/platform_admin/cms/homepage.html',
     "saving ? 'Saving...' : 'حفظ SEO'",
     '''saving ? "{% trans 'Saving...' %}" : "{% trans 'Save SEO' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "label: 'إحصائيات'",
     '''label: "{% trans 'Stats' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "label: 'الشركاء'",
     '''label: "{% trans 'Partners' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "label: 'فيديو'",
     '''label: "{% trans 'Video' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "label: 'من نحن'",
     '''label: "{% trans 'About Us' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "label: 'القيم'",
     '''label: "{% trans 'Values' %}"'''),
    ('templates/platform_admin/cms/homepage.html',
     "notify('تعذّر تحميل بيانات الصفحة الرئيسية', 'error')",
     '''notify("{% trans 'Failed to load homepage data' %}", 'error')'''),
    ('templates/platform_admin/cms/homepage.html',
     "notify(e.message || 'فشل الحفظ', 'error')",
     '''notify(e.message || "{% trans 'Save failed' %}", 'error')'''),

    # ── about.html ────────────────────────────────────────────────────────
    ('templates/platform_admin/cms/about.html',
     '            أعضاء الفريق',
     '            {% trans "Team Members" %}'),
    ('templates/platform_admin/cms/about.html',
     '<i data-lucide="plus" class="w-4 h-4"></i> إضافة عضو',
     '<i data-lucide="plus" class="w-4 h-4"></i> {% trans "Add Member" %}'),
    ('templates/platform_admin/cms/about.html',
     '<span class="text-xs font-semibold text-slate-500">عضو #<span x-text="idx+1"></span></span>',
     '<span class="text-xs font-semibold text-slate-500">{% trans "Member" %} #<span x-text="idx+1"></span></span>'),
    ('templates/platform_admin/cms/about.html',
     'placeholder="الدور / المسمى"',
     'placeholder="{% trans \'Role / Title\' %}"'),
    ('templates/platform_admin/cms/about.html',
     '<p class="col-span-2 text-sm text-slate-400 text-center py-4">لا يوجد أعضاء فريق بعد.</p>',
     '<p class="col-span-2 text-sm text-slate-400 text-center py-4">{% trans "No team members yet." %}</p>'),
    ('templates/platform_admin/cms/about.html',
     "saving ? 'Saving...' : 'حفظ الفريق'",
     '''saving ? "{% trans 'Saving...' %}" : "{% trans 'Save Team' %}"'''),
    ('templates/platform_admin/cms/about.html',
     "notify('تعذّر تحميل بيانات الصفحة', 'error')",
     '''notify("{% trans 'Failed to load page data' %}", 'error')'''),
    ('templates/platform_admin/cms/about.html',
     "notify('تم حفظ المحتوى', 'success')",
     '''notify("{% trans 'Content saved' %}", 'success')'''),
    ('templates/platform_admin/cms/about.html',
     "notify('تم حفظ الفريق', 'success')",
     '''notify("{% trans 'Team saved' %}", 'success')'''),

    # ── pricing.html ──────────────────────────────────────────────────────
    ('templates/platform_admin/cms/pricing.html',
     "editingPlan.id ? 'تعديل الخطة' : 'Add new plan'",
     '''editingPlan.id ? "{% trans 'Edit Plan' %}" : "{% trans 'Add new plan' %}"'''),
    ('templates/platform_admin/cms/pricing.html',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">الميزات (سطر لكل ميزة)</label>',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">{% trans "Features (one per line)" %}</label>'),
    ('templates/platform_admin/cms/pricing.html',
     'placeholder="رفع الملفات&#10;التقارير التلقائية&#10;دعم ZATCA"',
     'placeholder="{% trans \'File upload\' %}&#10;{% trans \'Automatic reports\' %}&#10;{% trans \'ZATCA support\' %}"'),
    ('templates/platform_admin/cms/pricing.html',
     "notify('تعذّر تحميل خطط الأسعار', 'error')",
     '''notify("{% trans 'Failed to load pricing plans' %}", 'error')'''),
    ('templates/platform_admin/cms/pricing.html',
     "notify('تم حفظ الخطة', 'success')",
     '''notify("{% trans 'Plan saved' %}", 'success')'''),
    ('templates/platform_admin/cms/pricing.html',
     "if (!confirm('هل أنت متأكد من حذف هذه الخطة؟')) return;",
     '''if (!confirm("{% trans 'Are you sure you want to delete this plan?' %}")) return;'''),
    ('templates/platform_admin/cms/pricing.html',
     "notify('تم حذف الخطة', 'success')",
     '''notify("{% trans 'Plan deleted' %}", 'success')'''),

    # ── intro_video.html ──────────────────────────────────────────────────
    ('templates/platform_admin/cms/intro_video.html',
     '<p class="text-xs text-slate-400">أضف رابط الصورة المصغّرة</p>',
     '<p class="text-xs text-slate-400">{% trans "Add the thumbnail URL" %}</p>'),
    ('templates/platform_admin/cms/intro_video.html',
     '<p class="text-xs font-semibold text-slate-500">حالة الفيديو</p>',
     '<p class="text-xs font-semibold text-slate-500">{% trans "Video Status" %}</p>'),
    ('templates/platform_admin/cms/intro_video.html',
     "form.is_active ? 'معروض في الموقع' : 'Hidden'",
     '''form.is_active ? "{% trans 'Shown on site' %}" : "{% trans 'Hidden' %}"'''),
    ('templates/platform_admin/cms/intro_video.html',
     '              فتح الفيديو',
     '              {% trans "Open Video" %}'),
    ('templates/platform_admin/cms/intro_video.html',
     "notify('تعذّر تحميل بيانات الفيديو', 'error')",
     '''notify("{% trans 'Failed to load video data' %}", 'error')'''),
    ('templates/platform_admin/cms/intro_video.html',
     "notify('تم حفظ الفيديو التعريفي', 'success')",
     '''notify("{% trans 'Intro video saved' %}", 'success')'''),

    # ── pages.html ────────────────────────────────────────────────────────
    ('templates/platform_admin/cms/pages.html',
     "editingPage.id ? 'تعديل الصفحة' : 'New Page'",
     '''editingPage.id ? "{% trans 'Edit Page' %}" : "{% trans 'New Page' %}"'''),
    ('templates/platform_admin/cms/pages.html',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">الرابط (Slug)</label>',
     '<label class="block text-xs font-semibold text-slate-500 mb-1.5">{% trans "URL (Slug)" %}</label>'),
    ('templates/platform_admin/cms/pages.html',
     "notify('تعذّر تحميل الصفحات', 'error')",
     '''notify("{% trans 'Failed to load pages' %}", 'error')'''),
    ('templates/platform_admin/cms/pages.html',
     "notify('تم حفظ الصفحة', 'success')",
     '''notify("{% trans 'Page saved' %}", 'success')'''),
    ('templates/platform_admin/cms/pages.html',
     "if (!confirm('هل أنت متأكد من حذف هذه الصفحة؟')) return;",
     '''if (!confirm("{% trans 'Are you sure you want to delete this page?' %}")) return;'''),
    ('templates/platform_admin/cms/pages.html',
     "notify('تم حذف الصفحة', 'success')",
     '''notify("{% trans 'Page deleted' %}", 'success')'''),

    # ── services.html ─────────────────────────────────────────────────────
    ('templates/platform_admin/cms/services.html',
     '{% block breadcrumb_current %}الخدمات{% endblock %}',
     '{% block breadcrumb_current %}{% trans "Services" %}{% endblock %}'),

    # ── faq.html ──────────────────────────────────────────────────────────
    ('templates/platform_admin/cms/faq.html',
     "filteredFaqs.length + ' سؤال'",
     '''filteredFaqs.length + " " + "{% trans 'questions' %}"'''),

    # ── settings.html (JS array of category labels) ───────────────────────
    ('templates/platform_admin/settings.html',
     "{ key: 'general',       label: 'عام',              icon: 'settings-2' },",
     "{ key: 'general',       label: \"{% trans 'General' %}\",          icon: 'settings-2' },"),
    ('templates/platform_admin/settings.html',
     "{ key: 'email',         label: 'البريد الإلكتروني', icon: 'mail' },",
     "{ key: 'email',         label: \"{% trans 'Email' %}\",            icon: 'mail' },"),
    ('templates/platform_admin/settings.html',
     "{ key: 'integrations',  label: 'التكاملات',        icon: 'plug' },",
     "{ key: 'integrations',  label: \"{% trans 'Integrations' %}\",     icon: 'plug' },"),
    ('templates/platform_admin/settings.html',
     "{ key: 'security',      label: 'الأمان',           icon: 'shield' },",
     "{ key: 'security',      label: \"{% trans 'Security' %}\",         icon: 'shield' },"),
    ('templates/platform_admin/settings.html',
     "{ key: 'notifications', label: 'الإشعارات',        icon: 'bell' },",
     "{ key: 'notifications', label: \"{% trans 'Notifications' %}\",    icon: 'bell' },"),
    ('templates/platform_admin/settings.html',
     "{ key: 'billing',       label: 'الفوترة',          icon: 'credit-card' },",
     "{ key: 'billing',       label: \"{% trans 'Billing' %}\",          icon: 'credit-card' },"),

    # ── monitoring.html ───────────────────────────────────────────────────
    ('templates/platform_admin/monitoring.html',
     "(metrics.cpu_cores || 0) + ' أنوية'",
     '''(metrics.cpu_cores || 0) + " " + "{% trans 'cores' %}"'''),

    # ── organizations.html ────────────────────────────────────────────────
    ('templates/platform_admin/organizations.html',
     'x-text="\'الإجمالي: \' + total"',
     'x-text="i18nTotalLabel + total"'),
    ('templates/platform_admin/organizations.html',
     'x-text="\'صفحة \' + page + \' من \' + totalPages"',
     'x-text="i18nPageWord + \' \' + page + \' \' + i18nOfWord + \' \' + totalPages"'),
    ('templates/platform_admin/organizations.html',
     "notify('تعذّر تحميل المنظمات', 'error')",
     '''notify("{% trans 'Failed to load organizations' %}", 'error')'''),
    ('templates/platform_admin/organizations.html',
     "notify('سيتم إضافة هذه الميزة قريباً', 'info')",
     '''notify("{% trans 'This feature will be added soon' %}", 'info')'''),
    ('templates/platform_admin/organizations.html',
     "const action = org.is_active ? 'تعطيل' : 'تفعيل';",
     '''const action = org.is_active ? "{% trans 'Deactivate' %}" : "{% trans 'Activate' %}";'''),
    ('templates/platform_admin/organizations.html',
     "if (!confirm(`هل أنت متأكد من ${action} المنظمة \"${org.name}\"؟`)) return;",
     'if (!confirm(`{% trans \'Are you sure you want to\' %} ${action} {% trans \'organization\' %} "${org.name}"?`)) return;'),
    ('templates/platform_admin/organizations.html',
     "notify(`تم ${action} المنظمة بنجاح`, 'success')",
     "notify(`{% trans 'Organization' %} ${action} {% trans 'successfully' %}`, 'success')"),
    ('templates/platform_admin/organizations.html',
     "notify('فشل تحديث الحالة', 'error')",
     '''notify("{% trans 'Status update failed' %}", 'error')'''),

    # ── media.html ────────────────────────────────────────────────────────
    ('templates/platform_admin/media.html',
     "files.length + ' ملف'",
     '''files.length + " " + "{% trans 'file' %}"'''),
    ('templates/platform_admin/media.html',
     '<th>تاريخ الرفع</th>',
     '<th>{% trans "Upload Date" %}</th>'),
    ('templates/platform_admin/media.html',
     "notify('تعذّر تحميل الملفات', 'error')",
     '''notify("{% trans 'Failed to load files' %}", 'error')'''),
    ('templates/platform_admin/media.html',
     "notify('تم رفع الملف: ' + file.name, 'success')",
     '''notify("{% trans 'File uploaded:' %} " + file.name, 'success')'''),
    ('templates/platform_admin/media.html',
     "notify('فشل رفع: ' + file.name, 'error')",
     '''notify("{% trans 'Failed to upload:' %} " + file.name, 'error')''',
     ),
    ('templates/platform_admin/media.html',
     "if (!confirm('هل أنت متأكد من حذف هذا الملف؟')) return;",
     '''if (!confirm("{% trans 'Are you sure you want to delete this file?' %}")) return;'''),
    ('templates/platform_admin/media.html',
     "notify('تم حذف الملف', 'success')",
     '''notify("{% trans 'File deleted' %}", 'success')'''),
    ('templates/platform_admin/media.html',
     "notify('تم نسخ الرابط', 'success')",
     '''notify("{% trans 'URL copied' %}", 'success')'''),
]


def main():
    applied = 0
    missing = []
    for tup in EDITS:
        rel = tup[0]
        old = tup[1]
        new = tup[2]
        path = BASE / rel
        if not path.exists():
            print(f"[skip] {rel} not found")
            continue
        text = path.read_text(encoding='utf-8')
        if old not in text:
            missing.append((rel, old[:80]))
            continue
        new_text = text.replace(old, new, 1)
        path.write_text(new_text, encoding='utf-8')
        applied += 1
    print(f"Applied: {applied}, missing: {len(missing)}")
    for rel, snippet in missing:
        print(f"  MISS {rel}: {snippet!r}")


if __name__ == '__main__':
    main()
