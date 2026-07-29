"""Add Arabic translations for the G2.3/G3.2/G3.3/G6 governance UI (TADGEEG).

Conservative: only sets a msgstr when the entry is missing or currently empty,
so existing professional translations are never overwritten. Compiles the .mo
at the end. Run: python scripts/apply_ar_ui_translations3.py
"""
from __future__ import annotations

import pathlib

import polib

PO = pathlib.Path("locale/ar/LC_MESSAGES/django.po")

# English source → professional Arabic. Common strings already in the catalog
# (Dashboard, Audit, Open, Total, Status, …) are included for completeness but
# only applied when still untranslated.
AR = {
    # Findings register
    "Findings Register": "سجل الملاحظات",
    "One normalized view of GL risk findings (ISA 315) and control deficiencies (ISA 265), each showing its link to an assessed risk.":
        "عرض موحّد لملاحظات مخاطر دفتر الأستاذ (ISA 315) وأوجه قصور الرقابة (ISA 265)، يُظهر ارتباط كلٍّ منها بمخاطرة مُقيَّمة.",
    "Read-only aggregation across finding types. Advisory — supports the audit file; not an opinion. No ledger writes.":
        "تجميع للقراءة فقط عبر أنواع الملاحظات. استشاري — يدعم ملف التدقيق؛ ليس رأيًا. لا يكتب في دفتر الأستاذ.",
    "GL findings": "ملاحظات دفتر الأستاذ",
    "Control deficiencies": "أوجه قصور الرقابة",
    "Linked to risk": "مرتبطة بمخاطرة",
    "Unlinked": "غير مرتبطة",
    "GL finding": "ملاحظة دفتر أستاذ",
    "Deficiency": "قصور رقابي",
    "Source": "المصدر",
    "Reference": "المرجع",
    "Risk link": "ارتباط المخاطرة",
    "Linked": "مرتبطة",
    "No findings recorded yet for this engagement.": "لا ملاحظات مسجَّلة بعد لهذا الارتباط.",
    "Choose an engagement to view its findings register.": "اختر ارتباطًا لعرض سجل ملاحظاته.",
    # Issues
    "Audit Issues": "ملاحظات التدقيق",
    "Track findings to closure: issue → remediation plan → remediated / accepted / closed. Deterministic; advisory; no ledger writes.":
        "تتبَّع الملاحظات حتى الإغلاق: ملاحظة ← خطة معالجة ← مُعالَجة / مقبولة / مغلقة. حتمي؛ استشاري؛ لا يكتب في دفتر الأستاذ.",
    "Issues support the audit file and management communications. They are not an audit opinion and never modify the ledger.":
        "تدعم الملاحظات ملف التدقيق ومراسلات الإدارة. وهي ليست رأي تدقيق ولا تُعدِّل دفتر الأستاذ إطلاقًا.",
    "Raise an issue": "تسجيل ملاحظة",
    "Raise issue": "تسجيل الملاحظة",
    "Severity": "الأهمية",
    "Owner": "المسؤول",
    "Due date": "تاريخ الاستحقاق",
    "Remediation plan": "خطة المعالجة",
    "Description": "الوصف",
    "Overdue": "متأخرة",
    "Critical": "حرجة",
    "Closed": "مغلقة",
    "Due": "الاستحقاق",
    "From GL finding": "من ملاحظة دفتر أستاذ",
    "Remediation": "المعالجة",
    "Management response": "رد الإدارة",
    "Record remediation": "تسجيل المعالجة",
    "Set status": "تعيين الحالة",
    "Note (management response)": "ملاحظة (رد الإدارة)",
    "Update": "تحديث",
    "No issues match. Raise one above.": "لا توجد ملاحظات مطابقة. سجّل واحدة أعلاه.",
    "Choose an engagement to manage its issues.": "اختر ارتباطًا لإدارة ملاحظاته.",
    # Reports
    "Engagement Reports": "تقارير الارتباط",
    "Versioned report snapshots assembled from the traceability spine, with preparer/reviewer/partner/EQR sign-offs (ISA 220/230).":
        "لقطات تقارير مُصدَّرة بإصدارات، مُجمَّعة من سلسلة التتبُّع، مع اعتمادات المُعِد/المراجع/الشريك/مراجع جودة الارتباط (ISA 220/230).",
    "Reports communicate audit results and a disclaimer — never an ISA 700 opinion, and never that the statements present fairly. No ledger writes.":
        "تُبلِّغ التقارير نتائج التدقيق مع إخلاء مسؤولية — وليست رأي ISA 700 إطلاقًا، ولا تُفيد بأن القوائم تعرض بعدالة. لا تكتب في دفتر الأستاذ.",
    "Build a report": "إنشاء تقرير",
    "Title (optional)": "العنوان (اختياري)",
    "Assemble draft": "تجميع مسودة",
    "A draft snapshots current risks, procedures, findings and issues. Regenerate a new version any time to refresh the facts.":
        "تلتقط المسودة المخاطر والإجراءات والملاحظات والقضايا الحالية. أعد التوليد كإصدار جديد في أي وقت لتحديث الوقائع.",
    "Assessed risks": "المخاطر المُقيَّمة",
    "Significant": "جوهرية",
    "Procedures": "الإجراءات",
    "Findings": "الملاحظات",
    "Open issues": "الملاحظات المفتوحة",
    "Overdue issues": "الملاحظات المتأخرة",
    "Sign-offs": "الاعتمادات",
    "Sign as": "التوقيع بصفة",
    "Note": "ملاحظة",
    "Sign off": "اعتماد",
    "ISA 220: the preparer of an artifact cannot also sign it off as reviewer/partner/EQR.":
        "ISA 220: لا يجوز لمُعِدّ المستند أن يعتمده أيضًا كمراجع/شريك/مراجع جودة.",
    "Regenerate as new version": "إعادة التوليد كإصدار جديد",
    "No reports yet. Assemble a draft above.": "لا توجد تقارير بعد. جمِّع مسودة أعلاه.",
    "Choose an engagement to build its reports.": "اختر ارتباطًا لإنشاء تقاريره.",
    # Team
    "Engagement Team": "فريق الارتباط",
    "Team": "الفريق",
    "Assign team members and roles (ISA 220). Roles drive sign-off segregation on the engagement's artifacts.":
        "عيّن أعضاء الفريق وأدوارهم (ISA 220). تُحدِّد الأدوار الفصل في اعتماد مستندات الارتباط.",
    "Membership records support ISA 220 direction, supervision and review. No ledger writes.":
        "تدعم سجلات العضوية التوجيه والإشراف والمراجعة وفق ISA 220. لا تكتب في دفتر الأستاذ.",
    "Members": "الأعضاء",
    "Partners": "الشركاء",
    "Reviewers": "المراجعون",
    "Preparers": "المُعِدّون",
    "Assign a member": "إضافة عضو",
    "User": "المستخدم",
    "Role": "الدور",
    "Responsibilities": "المسؤوليات",
    "Assign": "إضافة",
    "All active users in your organization are already assigned.": "جميع المستخدمين النشطين في مؤسستك معيَّنون بالفعل.",
    "Member": "العضو",
    "Assigned by": "عيَّنه",
    "Remove": "إزالة",
    "Remove this member?": "إزالة هذا العضو؟",
    "No members assigned yet.": "لا أعضاء معيَّنون بعد.",
    "Choose an engagement to manage its team.": "اختر ارتباطًا لإدارة فريقه.",
    # Nav + workspace
    "Team & Sign-off": "الفريق والاعتماد",
    "Report & Team": "التقرير والفريق",
    "Total findings": "إجمالي الملاحظات",
    "No findings recorded yet.": "لا ملاحظات مسجَّلة بعد.",
    "No issues yet. Track findings to closure here.": "لا ملاحظات بعد. تتبَّع الملاحظات حتى الإغلاق من هنا.",
    "Latest report": "آخر تقرير",
    "None yet": "لا يوجد بعد",
    "Team members": "أعضاء الفريق",
    "Team & sign-off": "الفريق والاعتماد",
    "Reports communicate results with a disclaimer — never an ISA 700 opinion.":
        "تُبلِّغ التقارير النتائج مع إخلاء مسؤولية — وليست رأي ISA 700 إطلاقًا.",
    "overdue": "متأخرة",
    "unlinked": "غير مرتبطة",
}


def main():
    po = polib.pofile(str(PO))
    by_id = {e.msgid: e for e in po}
    added = filled = skipped = 0
    for src, ar in AR.items():
        entry = by_id.get(src)
        if entry is None:
            po.append(polib.POEntry(msgid=src, msgstr=ar))
            added += 1
        elif not entry.msgstr.strip():
            entry.msgstr = ar
            if "fuzzy" in entry.flags:
                entry.flags.remove("fuzzy")
            filled += 1
        else:
            skipped += 1
    po.save(str(PO))
    mo = PO.with_suffix(".mo")
    po.save_as_mofile(str(mo))
    print(f"added={added} filled={filled} skipped(existing)={skipped}")
    print(f"saved {PO} and {mo}")


if __name__ == "__main__":
    main()
