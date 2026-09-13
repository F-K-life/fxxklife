import os
import unittest
import urllib.error
from unittest.mock import patch

import modeling


class ProviderDiagnosticsTests(unittest.TestCase):
    def test_generate_logs_http_status_without_sensitive_details(self):
        api_key = "sk-sensitive-test-value"
        error = urllib.error.HTTPError(
            "https://provider.example/v1/chat/completions",
            403,
            "response contained sensitive upstream details",
            {},
            None,
        )

        with patch.dict(
            os.environ,
            {
                "AI_BASE_URL": "https://provider.example/v1",
                "AI_MODEL": "test-model",
                "AI_API_KEY": api_key,
            },
        ), patch("modeling.urllib.request.urlopen", side_effect=error):
            with self.assertLogs("self_echo.modeling", level="WARNING") as captured:
                result = modeling._generate(
                    "system prompt",
                    {"private": "user content"},
                    {"reply_text": "fallback"},
                    lambda value: value,
                )

        output = "\n".join(captured.output)
        self.assertEqual(result["model"]["mode"], "local")
        self.assertIn("category=http_403", output)
        self.assertNotIn(api_key, output)
        self.assertNotIn("sensitive upstream details", output)
        self.assertNotIn("user content", output)


if __name__ == "__main__":
    unittest.main()
