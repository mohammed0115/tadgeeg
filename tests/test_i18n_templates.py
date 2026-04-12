from django.conf import settings
from django.test import Client, SimpleTestCase, override_settings
from pathlib import Path


class I18nTemplateTests(SimpleTestCase):
    def setUp(self):
        self.client = Client()

    def test_login_page_default_language_is_arabic_rtl(self):
        """Default language renders Arabic RTL."""
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="ar"', content)
        self.assertIn('dir="rtl"', content)

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
        self.assertIn("95% automation", content)
        self.assertIn("Full ZATCA compliance", content)
        self.assertIn("Advanced artificial intelligence", content)
        self.assertIn("Fraud detection", content)
        self.assertIn("Predictive analytics", content)
        self.assertNotIn("أتمتة بنسبة 95%", content)
        self.assertNotIn("كشف الاحتيال", content)
        self.assertNotIn("تحليلات تنبؤية", content)

    def test_landing_feature_template_uses_english_source_literals(self):
        base = Path(settings.BASE_DIR)
        landing_tpl = (base / "templates" / "landing" / "index.html").read_text(encoding="utf-8")

        self.assertIn('{% trans "Full ZATCA compliance" %}', landing_tpl)
        self.assertIn('{% trans "Advanced artificial intelligence" %}', landing_tpl)
        self.assertIn('{% trans "Fraud detection" %}', landing_tpl)
        self.assertIn('{% trans "Predictive analytics" %}', landing_tpl)
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
        base = Path(settings.BASE_DIR)
        audit_index = (base / "templates" / "audit" / "index.html").read_text(encoding="utf-8")
        audit_detail = (base / "templates" / "audit" / "detail.html").read_text(encoding="utf-8")

        self.assertIn("{% load i18n %}", audit_index)
        self.assertIn("{% get_current_language_bidi", audit_index)
        self.assertIn("{% load i18n %}", audit_detail)
        self.assertIn("{% get_current_language_bidi", audit_detail)
        self.assertIn("arrow-right", audit_detail)
        self.assertIn("arrow-left", audit_detail)

    def test_invoice_report_templates_use_language_direction(self):
        base = Path(settings.BASE_DIR)
        html_tpl = (base / "templates" / "reports" / "invoice_audit_report.html").read_text(encoding="utf-8")
        pdf_tpl = (base / "templates" / "reports" / "invoice_audit_report_pdf.html").read_text(encoding="utf-8")

        self.assertIn("{% get_current_language_bidi", html_tpl)
        self.assertIn("dir=\"{% if LANGUAGE_BIDI %}rtl{% else %}ltr{% endif %}\"", html_tpl)
        self.assertIn("{% trans \"Invoice Audit Report\" %}", html_tpl)
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
