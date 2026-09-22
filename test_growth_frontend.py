import tempfile
import unittest
from pathlib import Path

from app import create_app


class GrowthFrontendTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": str(Path(self.directory.name) / "ui.db"),
                               "SECRET_KEY": "growth-ui-test"})
        self.client = self.app.test_client()
        self.client.get("/login")
        with self.client.session_transaction() as saved:
            csrf = saved["csrf_token"]
        self.client.post("/demo", data={"csrf_token": csrf})

    def tearDown(self):
        self.directory.cleanup()

    def test_chat_has_growth_summary_and_accessible_four_step_wizard(self):
        html = self.client.get("/chat").get_data(as_text=True)
        for marker in ("growth-summary", "growth-create-dialog", "growth-capabilities", "growth-week",
                       "第 1 步", "第 2 步", "第 3 步", "第 4 步"):
            self.assertIn(marker, html)
        self.assertIn('aria-label="关闭成长主题创建向导"', html)
        self.assertIn('type="submit"', html)

    def test_mobile_chat_keeps_growth_creation_entry_outside_hidden_aside(self):
        html = self.client.get("/chat").get_data(as_text=True)
        self.assertIn('id="open-growth-create-mobile"', html)
        self.assertLess(html.index('id="open-growth-create-mobile"'), html.index('<aside class="connect-aside"'))

    def test_chat_script_calls_confirmed_growth_endpoints_and_escapes_text(self):
        script = Path("static/js/chat.js").read_text()
        for marker in ("/api/growth-experiments", "/capability-draft", "/capabilities/confirm",
                       "/weekly-draft", "/api/weekly-experiments/"):
            self.assertIn(marker, script)
        self.assertTrue("textContent" in script or "FS.escape" in script)

    def test_focus_exposes_growth_context_progressive_help_and_evidence_fields(self):
        html = self.client.get("/focus").get_data(as_text=True)
        for marker in ("focus-capability", "focus-hypothesis", "focus-expected-evidence", "focus-help",
                       "我卡住了", "evidence-content", "evidence-link", "reflection-difficulty",
                       "reflection-method", "reflection-capability", "reflection-adjustment", "retry-evidence"):
            self.assertIn(marker, html)
        script = Path("static/js/focus.js").read_text()
        self.assertIn("/api/growth-evidence", script)
        self.assertLess(script.index("changeSession('finish'"), script.index("/api/growth-evidence"))
        self.assertIn("growth-evidence-draft", script)
        self.assertIn("flushGrowthEvidence", script)

    def test_profile_contains_growth_map_statuses_and_source_links(self):
        html = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("growth-map", html)
        script = Path("static/js/profile.js").read_text()
        for marker in ("待验证", "练习中", "已有证据", "/echoes?event=", "/focus?task="):
            self.assertIn(marker, script)

    def test_weekly_review_exposes_editable_next_week_confirmation(self):
        html = self.client.get("/echoes").get_data(as_text=True)
        for marker in ("weekly-review", "next-week-form", "next-week-hypothesis", "next-week-action-title", "confirm-next-week"):
            self.assertIn(marker, html)
        script = Path("static/js/echoes.js").read_text()
        self.assertIn("next_week_proposal", script)
        self.assertIn("/api/weekly-experiments/0", script)


if __name__ == "__main__":
    unittest.main()
