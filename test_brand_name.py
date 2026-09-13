import tempfile
import unittest
from pathlib import Path

from app import create_app


class BrandNameTests(unittest.TestCase):
    def test_repository_has_no_old_display_brand(self):
        root = Path(__file__).parent
        old_names = ("\u672a\u6765\u7684\u6211", "Future\u0020Self")
        suffixes = {".cmd", ".html", ".js", ".md", ".py"}
        offenders = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in {".git", ".venv", "instance"} for part in path.parts):
                continue
            content = path.read_text(encoding="utf-8")
            if any(old_name.casefold() in content.casefold() for old_name in old_names):
                offenders.append(str(path.relative_to(root)))
        self.assertEqual([], offenders)

    def test_login_and_chat_use_self_echo_brand(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({
                "TESTING": True,
                "DATABASE": str(Path(directory) / "brand.db"),
                "SECRET_KEY": "brand-test-secret",
                "STARTUP_NONCE": "brand-test-process",
            })
            client = app.test_client()

            login = client.get("/login").get_data(as_text=True)
            self.assertIn("明日见", login)
            self.assertIn("SELF ECHO", login)
            self.assertNotIn("\u672a\u6765\u7684\u6211", login)
            self.assertNotIn("FUTURE\u0020SELF", login)

            with client.session_transaction() as saved:
                csrf_token = saved["csrf_token"]
            client.post("/demo", data={"csrf_token": csrf_token})
            chat = client.get("/chat").get_data(as_text=True)
            self.assertIn("明日见 Self Echo", chat)
            self.assertIn("SELF ECHO", chat)
            self.assertNotIn("\u672a\u6765\u7684\u6211", chat)
            self.assertNotIn("FUTURE\u0020SELF", chat)


if __name__ == "__main__":
    unittest.main()
