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
