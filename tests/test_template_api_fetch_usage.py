from pathlib import Path

from django.test import SimpleTestCase


class TemplateApiFetchUsageTests(SimpleTestCase):
    def test_templates_do_not_parse_api_fetch_result_twice(self):
        templates_dir = Path(__file__).resolve().parents[1] / "templates"
        offenders = []

        for template_path in templates_dir.rglob("*.html"):
            content = template_path.read_text(encoding="utf-8")
            for line_number, line in enumerate(content.splitlines(), start=1):
                if "apiFetch(" in line and ".then(r => r.json())" in line:
                    offenders.append(f"{template_path}:{line_number}")

        self.assertFalse(
            offenders,
            "apiFetch() already returns parsed data. Remove '.then(r => r.json())' from:\n"
            + "\n".join(offenders),
        )

    def test_invoice_upload_authenticates_without_a_localstorage_token(self):
        """Upload posts to the session-authenticated form endpoint, not the API.

        This used to require `apiFetch('/invoices/upload/')`. The page now
        posts multipart to `/auditor/upload/`, a Django view that answers with
        a redirect to the result page — `apiFetch` prefixes `/api/v1`, expects
        JSON back, and cannot carry either of those, so requiring it would mean
        breaking the upload to satisfy the test.

        What the original test was actually protecting still holds and is
        asserted directly: the request must authenticate by session + CSRF, and
        must not depend on a token in localStorage — the failure mode being an
        upload button that silently does nothing for a session-logged-in user.
        """
        template_path = Path(__file__).resolve().parents[1] / "templates" / "invoices" / "upload.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn("getCookie('csrftoken')", content,
                      "upload must send the CSRF token — Django rejects the POST otherwise")
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", content,
                      "the view branches on this header to answer AJAX rather than a full page")
        self.assertNotIn(
            "const token = TOKEN()",
            content,
            "Invoice upload should not depend on localStorage token presence to start uploading.",
        )
        self.assertNotIn("localStorage.getItem('access", content,
                         "same as above, spelled the other way")

    def test_invoice_upload_handles_an_expired_session(self):
        """A 401/403 has to become a visible message, not a silent no-op."""
        template_path = Path(__file__).resolve().parents[1] / "templates" / "invoices" / "upload.html"
        content = template_path.read_text(encoding="utf-8")

        self.assertIn("response.status === 401", content)
        self.assertIn("/login/", content)
