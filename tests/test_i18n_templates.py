import re

from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings
from pathlib import Path


class I18nTemplateTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    @override_settings(LANGUAGE_CODE="ar")
    def test_login_page_renders_arabic_rtl(self):
        """Arabic renders RTL.

        The override is not optional here. `finai_backend/settings/test.py`
        deliberately sets LANGUAGE_CODE="en" so the suite asserts against stable
        English source strings; this test asked for the *default* language and
        therefore measured that override rather than the product. Production is
        Arabic-first — verified separately, and pinned below so a change to the
        production default cannot pass unnoticed.
        """
        self.client.cookies["django_language"] = "ar"
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)

    def test_production_default_language_is_arabic(self):
        """The product is Arabic-first; only the test overlay is English.

        Read from the canonical module rather than the active settings, because
        the active ones are the test overlay by design.
        """
        from finai_backend import settings_canonical

        self.assertEqual(settings_canonical.LANGUAGE_CODE, "ar")

    @override_settings(LANGUAGE_CODE="en")
    def test_login_page_renders_ltr_for_english(self):
        """When language is English the page renders LTR."""
        self.client.cookies["django_language"] = "en"
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="en"', content)
        self.assertIn('dir="ltr"', content)

    def test_language_switcher_supports_arabic_and_english(self):
        """Both Arabic and English are present in LANGUAGES setting."""
        language_codes = [code for code, _ in settings.LANGUAGES]
        self.assertIn("ar", language_codes)
        self.assertIn("en", language_codes)

    def test_branding_is_centralized_on_public_pages(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Brand name changed from "Tadgeeg AI" to "Tadgeeg"
        self.assertIn("Tadgeeg", content)
        self.assertTrue(settings.COMPANY_NAME in content or settings.COMPANY_NAME_AR in content)

    @override_settings(LANGUAGE_CODE="en")
    def test_landing_page_feature_cards_render_in_english(self):
        self.client.cookies["django_language"] = "en"
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="en"', content)
        # "95% automation" used to be asserted here. It was an unsourced
        # performance claim on a page enterprise buyers read, and it is gone —
        # see tests/test_no_fabricated_metrics.py. What replaced it is a
        # countable fact, so that is what the English page must show.
        self.assertIn("Automated audit rules", content)
        self.assertNotIn("95% Automation", content)
        # The feature deck was rewritten (§L.4, ten cards in one row). These
        # are the titles that exist now; the old ones were asserted for years
        # after they stopped being on the page.
        self.assertIn("Regulatory Compliance", content)
        self.assertIn("Fraud Detection", content)
        self.assertIn("Smart Insights", content)
        self.assertNotIn("أتمتة بنسبة 95%", content)
        self.assertNotIn("كشف الاحتيال", content)
        self.assertNotIn("تحليلات تنبؤية", content)

    def test_landing_feature_template_uses_english_source_literals(self):
        base = Path(settings.BASE_DIR)
        landing_tpl = (base / "templates" / "landing" / "index.html").read_text(encoding="utf-8")

        self.assertIn('{% trans "Regulatory Compliance" %}', landing_tpl)
        self.assertIn('{% trans "Fraud Detection" %}', landing_tpl)
        self.assertIn('{% trans "Smart Insights & Reports" %}', landing_tpl)
        self.assertNotIn('{% trans "امتثال كامل لـ ZATCA" %}', landing_tpl)
        self.assertNotIn('{% trans "ذكاء اصطناعي متقدم" %}', landing_tpl)
        self.assertNotIn('{% trans "كشف الاحتيال" %}', landing_tpl)
        self.assertNotIn('{% trans "تحليلات تنبؤية" %}', landing_tpl)

    def test_branding_is_exposed_on_auth_pages(self):
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Brand name changed from "Tadgeeg AI" to "Tadgeeg"
        self.assertIn("Tadgeeg", content)

    def test_audit_templates_include_i18n_and_bidi_tags(self):
        """Direction must be resolved — by the template OR by the base it extends.

        This used to demand `{% get_current_language_bidi %}` in every file.
        `audit/index.html` then moved to extending `layouts/dashboard_base.html`,
        which sets `dir` on <html> from LANGUAGE_BIDI for every page at once.
        That is strictly better, and the old assertion called it a failure.

        So the invariant is checked instead of the syntax: a template either
        resolves direction itself, or inherits a base that does.
        """
        base = Path(settings.BASE_DIR)
        templates = base / "templates"

        def resolves_direction(relpath):
            text = (templates / relpath).read_text(encoding="utf-8")
            if "{% get_current_language_bidi" in text:
                return True
            match = re.search(r'{%\s*extends\s+"([^"]+)"', text)
            return bool(match) and resolves_direction(match.group(1))

        for relpath in ("audit/index.html", "audit/detail.html"):
            self.assertIn("{% load i18n %}", (templates / relpath).read_text(encoding="utf-8"))
            self.assertTrue(
                resolves_direction(relpath),
                f"{relpath} resolves no text direction, and neither does its base",
            )

        audit_detail = (templates / "audit" / "detail.html").read_text(encoding="utf-8")
        self.assertIn("arrow-right", audit_detail)
        self.assertIn("arrow-left", audit_detail)

    def test_invoice_report_templates_use_language_direction(self):
        base = Path(settings.BASE_DIR)
        html_tpl = (base / "templates" / "reports" / "invoice_audit_report.html").read_text(encoding="utf-8")
        pdf_tpl = (base / "templates" / "reports" / "invoice_audit_report_pdf.html").read_text(encoding="utf-8")

        self.assertIn("{% get_current_language_bidi", html_tpl)
        self.assertIn("{% get_current_language_bidi", pdf_tpl)
        # The PDF template is standalone — it renders outside the dashboard
        # chrome — so it must carry the dir attribute itself.
        self.assertIn("dir=\"{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}\"", pdf_tpl)

        # The HTML report's heading is `{{ report_title|default:_("...") }}` —
        # a stored title when there is one, the translated default otherwise.
        # Asserting the bare `{% trans %}` form called that a regression when it
        # was an improvement. What matters is that the fallback is translated,
        # not which of gettext's two spellings produced it.
        self.assertRegex(html_tpl, r'_\(\s*"Invoice Audit Report"\s*\)|{%\s*trans\s+"Invoice Audit Report"\s*%}')
        self.assertIn("{% trans \"Invoice Audit Report\" %}", pdf_tpl)

    def test_executive_report_template_avoids_css_import_fonts(self):
        base = Path(settings.BASE_DIR)
        tpl = (base / "templates" / "reports" / "executive_report.html").read_text(encoding="utf-8")

        self.assertNotIn("@import url('https://fonts.googleapis.com", tpl)
        self.assertIn("https://fonts.googleapis.com/css2", tpl)

    def test_report_pdf_template_localizes_benchmark_status_labels(self):
        base = Path(settings.BASE_DIR)
        tpl = (base / "templates" / "reports" / "report_pdf.html").read_text(encoding="utf-8")

        self.assertNotIn("{{ m.compliance_rate_pct.status }}", tpl)
        self.assertNotIn("{{ m.duplicate_rate_pct.status }}", tpl)
        self.assertNotIn("{{ m.avg_risk_score.status }}", tpl)
        self.assertNotIn("{{ m.vat_compliance_rate_pct.status }}", tpl)
        self.assertIn("Above benchmark", tpl)
        self.assertIn("Below benchmark", tpl)
        self.assertIn("At benchmark", tpl)

    def test_document_audit_template_avoids_raw_narrative_keys(self):
        base = Path(settings.BASE_DIR)
        tpl = (base / "templates" / "reports" / "document_audit_report.html").read_text(encoding="utf-8")

        self.assertNotIn(">EXECUTIVE_SUMMARY<", tpl)
        self.assertNotIn(">SCOPE_AND_METHODOLOGY<", tpl)
        self.assertNotIn(">KEY_FINDINGS<", tpl)
        self.assertNotIn(">ANOMALIES_SECTION<", tpl)
        self.assertNotIn(">COMPLIANCE_SECTION<", tpl)
        self.assertNotIn(">RECOMMENDATIONS<", tpl)
        self.assertNotIn(">CONCLUSION<", tpl)
        self.assertNotIn(">MANAGEMENT_RESPONSE_PLACEHOLDER<", tpl)

    def test_document_audit_template_uses_django_i18n_tags(self):
        base = Path(settings.BASE_DIR)
        tpl = (base / "templates" / "reports" / "document_audit_report.html").read_text(encoding="utf-8")

        self.assertIn("{% load i18n", tpl)
        self.assertIn("{% get_current_language_bidi as LANGUAGE_BIDI %}", tpl)
        self.assertIn('{% trans "Document Audit Report" %}', tpl)
