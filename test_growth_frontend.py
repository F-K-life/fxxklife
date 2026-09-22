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

    def test_chat_script_calls_confirmed_growth_endpoints_and_escapes_text(self):
        script = Path("static/js/chat.js").read_text()
        for marker in ("/api/growth-experiments", "/capability-draft", "/capabilities/confirm",
                       "/weekly-draft", "/api/weekly-experiments/"):
            self.assertIn(marker, script)
        self.assertTrue("textContent" in script or "FS.escape" in script)


if __name__ == "__main__":
    unittest.main()
