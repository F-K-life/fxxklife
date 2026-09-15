import json
import tempfile
import unittest
from pathlib import Path

from app import create_app


ROOT = Path(__file__).parent


class ModelScopeDeploymentTests(unittest.TestCase):
    def test_docker_deployment_uses_modelscope_service_port(self):
        config = json.loads((ROOT / "ms_deploy.json").read_text(encoding="utf-8"))

        self.assertEqual(config["sdk_type"], "docker")
        self.assertEqual(config["resource_configuration"], "platform/2v-cpu-16g-mem")
        self.assertEqual(config["port"], 7860)

        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("EXPOSE 7860", dockerfile)
        self.assertIn("0.0.0.0:7860", dockerfile)
        self.assertIn("app:create_app()", dockerfile)
        self.assertIn("MODELSCOPE_STUDIO=1", dockerfile)

        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("gunicorn", requirements)

    def test_modelscope_responses_allow_only_modelscope_to_embed(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({
                "TESTING": True,
                "DATABASE": str(Path(directory) / "modelscope.db"),
                "SECRET_KEY": "modelscope-test-secret",
                "MODELSCOPE_STUDIO": True,
            })

            response = app.test_client().get("/login")

            self.assertNotIn("X-Frame-Options", response.headers)
            self.assertEqual(
                response.headers["Content-Security-Policy"],
                "frame-ancestors 'self' https://www.modelscope.cn",
            )

    def test_regular_responses_still_deny_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({
                "TESTING": True,
                "DATABASE": str(Path(directory) / "regular.db"),
                "SECRET_KEY": "regular-test-secret",
                "MODELSCOPE_STUDIO": False,
            })

            response = app.test_client().get("/login")

            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertNotIn("Content-Security-Policy", response.headers)


if __name__ == "__main__":
    unittest.main()
