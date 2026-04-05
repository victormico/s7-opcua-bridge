from __future__ import annotations

import unittest
from pathlib import Path


class TestDashboardService(unittest.TestCase):
    def test_dashboard_assets_exist(self) -> None:
        dashboard_dir = Path(__file__).resolve().parent.parent / "services" / "dashboard"
        self.assertTrue((dashboard_dir / "index.html").exists())
        self.assertTrue((dashboard_dir / "app.js").exists())
        self.assertTrue((dashboard_dir / "styles.css").exists())
        self.assertTrue((dashboard_dir / "Dockerfile").exists())

    def test_dashboard_wires_gateway_routes(self) -> None:
        app_js = (
            Path(__file__).resolve().parent.parent / "services" / "dashboard" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("/discover", app_js)
        self.assertIn("/save-config", app_js)
        self.assertIn("/status", app_js)
        self.assertIn("localStorage", app_js)
