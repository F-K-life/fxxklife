import json
import unittest
from pathlib import Path


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

        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("gunicorn", requirements)


if __name__ == "__main__":
    unittest.main()
