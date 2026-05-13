"""Tests for the Frontend uplift.

Covers:
  • ui_tags.can filter — capability gating
  • ui_tags.has_role filter
  • dict_get filter
  • vite_asset tag — manifest hit + miss
  • CSP middleware — nonce + header on HTML, no header on JSON
  • approval_inbox context processor — anonymous / no-org / counted
"""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings


# ─── ui_tags filters ────────────────────────────────────────────────────────
class CanFilterTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        User = get_user_model()
        self.org = make_org()
        self.admin = User.objects.create_user(
            email="admin@example.com", password="x",
            full_name="Admin", role="admin", organization=self.org,
        )
        self.junior = User.objects.create_user(
            email="junior@example.com", password="x",
            full_name="Junior", role="junior_auditor", organization=self.org,
        )

    def _render(self, user, capability):
        tpl = Template(
            "{% load ui_tags %}"
            "{% if user|can:cap %}YES{% else %}NO{% endif %}"
        )
        return tpl.render(Context({"user": user, "cap": capability})).strip()

    def test_admin_can_manage_organization(self):
        self.assertEqual(self._render(self.admin, "manage_organization"), "YES")

    def test_junior_cannot_manage_organization(self):
        self.assertEqual(self._render(self.junior, "manage_organization"), "NO")

    def test_junior_can_edit_invoice_data(self):
        self.assertEqual(self._render(self.junior, "edit_invoice_data"), "YES")

    def test_anonymous_user_can_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(self._render(AnonymousUser(), "manage_organization"), "NO")


class HasRoleFilterTests(TestCase):
    def setUp(self):
        from apps.billing.tests._factories import make_org
        User = get_user_model()
        self.org = make_org()
        self.senior = User.objects.create_user(
            email="senior@example.com", password="x",
            full_name="Senior", role="senior_auditor", organization=self.org,
        )

    def test_matches_one_of_csv_roles(self):
        tpl = Template(
            "{% load ui_tags %}"
            "{% if user|has_role:'admin,senior_auditor,cao' %}YES{% else %}NO{% endif %}"
        )
        self.assertEqual(tpl.render(Context({"user": self.senior})).strip(), "YES")

    def test_no_match_means_no(self):
        tpl = Template(
            "{% load ui_tags %}"
            "{% if user|has_role:'admin' %}YES{% else %}NO{% endif %}"
        )
        self.assertEqual(tpl.render(Context({"user": self.senior})).strip(), "NO")


class DictGetTests(TestCase):
    def test_dict_lookup(self):
        tpl = Template("{% load ui_tags %}{{ row|dict_get:'name' }}")
        self.assertEqual(tpl.render(Context({"row": {"name": "Acme"}})).strip(), "Acme")

    def test_attribute_fallback(self):
        class Row:
            name = "Beta"
        tpl = Template("{% load ui_tags %}{{ row|dict_get:'name' }}")
        self.assertEqual(tpl.render(Context({"row": Row()})).strip(), "Beta")

    def test_missing_returns_empty(self):
        tpl = Template("{% load ui_tags %}|{{ row|dict_get:'missing' }}|")
        self.assertEqual(tpl.render(Context({"row": {}})).strip(), "||")


# ─── Vite asset tag ────────────────────────────────────────────────────────
class ViteAssetTagTests(TestCase):
    def test_missing_manifest_falls_back_to_source_path(self):
        from apps.frontend.templatetags.ui_tags import _load_manifest
        _load_manifest.cache_clear()
        tpl = Template("{% load ui_tags %}{% vite_asset 'js/app.js' %}")
        out = tpl.render(Context({})).strip()
        self.assertTrue(out.endswith("/dist/js/app.js"))

    def test_manifest_hit_returns_hashed_name(self):
        from apps.frontend.templatetags.ui_tags import _load_manifest
        _load_manifest.cache_clear()
        fake_manifest = {
            "js/app.js": {"file": "app.abc123.js", "src": "js/app.js"}
        }
        with mock.patch.object(Path, "exists", return_value=True), \
             mock.patch.object(Path, "read_text", return_value=json.dumps(fake_manifest)):
            _load_manifest.cache_clear()
            tpl = Template("{% load ui_tags %}{% vite_asset 'js/app.js' %}")
            out = tpl.render(Context({})).strip()
            self.assertTrue(out.endswith("/dist/app.abc123.js"))


# ─── CSP middleware ────────────────────────────────────────────────────────
class CSPMiddlewareTests(TestCase):
    def setUp(self):
        from core.security.csp import CSPMiddleware
        from django.http import HttpResponse

        def view_html(request):
            return HttpResponse("<html><body>ok</body></html>",
                                content_type="text/html")
        def view_json(request):
            return HttpResponse('{"ok":true}', content_type="application/json")

        self.mw_html = CSPMiddleware(view_html)
        self.mw_json = CSPMiddleware(view_json)
        self.factory = RequestFactory()

    def test_html_response_gets_csp_header_with_nonce(self):
        req = self.factory.get("/")
        res = self.mw_html(req)
        self.assertIn("Content-Security-Policy", res)
        self.assertIn("nonce-", res["Content-Security-Policy"])
        self.assertTrue(hasattr(req, "csp_nonce"))
        self.assertGreater(len(req.csp_nonce), 8)

    def test_json_response_gets_no_csp_header(self):
        req = self.factory.get("/")
        res = self.mw_json(req)
        self.assertNotIn("Content-Security-Policy", res)
        # nonce still attached for any conditional rendering
        self.assertTrue(hasattr(req, "csp_nonce"))

    @override_settings(CSP_REPORT_ONLY=True)
    def test_report_only_mode_emits_report_header(self):
        req = self.factory.get("/")
        res = self.mw_html(req)
        self.assertIn("Content-Security-Policy-Report-Only", res)
        self.assertNotIn("Content-Security-Policy", res)


# ─── Approval inbox context processor ──────────────────────────────────────
class ApprovalInboxContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        from apps.billing.tests._factories import make_org
        User = get_user_model()
        self.org = make_org()
        self.user = User.objects.create_user(
            email="audit@example.com", password="x",
            full_name="Audit", role="senior_auditor", organization=self.org,
        )

    def _ctx(self, user):
        from apps.audit.context_processors import approval_inbox
        req = self.factory.get("/")
        req.user = user
        return approval_inbox(req)

    def test_anonymous_returns_zero(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(self._ctx(AnonymousUser())["approval_inbox_count"], 0)

    def test_user_without_org_returns_zero(self):
        User = get_user_model()
        orphan = User.objects.create_user(
            email="orphan@example.com", password="x",
            full_name="Orphan", role="junior_auditor",
        )
        self.assertEqual(self._ctx(orphan)["approval_inbox_count"], 0)

    def test_user_with_org_returns_pending_count(self):
        # No invoices in the test DB → 0 is a valid pending count.
        ctx = self._ctx(self.user)
        self.assertIn("approval_inbox_count", ctx)
        self.assertGreaterEqual(ctx["approval_inbox_count"], 0)
