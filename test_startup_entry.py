import tempfile
import unittest
from pathlib import Path

from app import create_app


class StartupEntryTests(unittest.TestCase):
    def test_previous_process_session_cannot_skip_login_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "startup-entry.db")
            shared = {
                "TESTING": True,
                "DATABASE": database,
                "SECRET_KEY": "shared-test-secret",
            }
            first_app = create_app({**shared, "STARTUP_NONCE": "first-process"})
            first_client = first_app.test_client()

            first_client.get("/login")
            with first_client.session_transaction() as saved:
                csrf_token = saved["csrf_token"]
            response = first_client.post(
                "/demo", data={"csrf_token": csrf_token}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(first_client.get("/chat").status_code, 200)

            session_cookie = first_client.get_cookie("session")
            self.assertIsNotNone(session_cookie)

            restarted_app = create_app(
                {**shared, "STARTUP_NONCE": "second-process"}
            )
            restarted_client = restarted_app.test_client()
            restarted_client.set_cookie("session", session_cookie.value)

            response = restarted_client.get("/chat")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/login")
            with restarted_client.session_transaction() as saved:
                self.assertNotIn("user_id", saved)


if __name__ == "__main__":
    unittest.main()
