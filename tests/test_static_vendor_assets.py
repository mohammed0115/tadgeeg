import re
from pathlib import Path

from django.test import SimpleTestCase


class StaticVendorAssetsTests(SimpleTestCase):
    def test_vendor_sourcemap_references_point_to_existing_files(self):
        vendor_dir = Path(__file__).resolve().parents[1] / "static" / "vendor"
        missing = []
        pattern = re.compile(r"^//# sourceMappingURL=(?P<target>\S+)\s*$")

        for asset_path in vendor_dir.glob("*.js"):
            for line_number, line in enumerate(asset_path.read_text(encoding="utf-8").splitlines(), start=1):
                match = pattern.match(line.strip())
                if not match:
                    continue

                target_path = asset_path.parent / match.group("target")
                if not target_path.exists():
                    missing.append(f"{asset_path}:{line_number} -> {target_path.name}")

        self.assertFalse(
            missing,
            "Vendored static assets reference missing source maps, which breaks collectstatic in production:\n"
            + "\n".join(missing),
        )
