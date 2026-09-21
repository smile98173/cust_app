import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config.env_loader import load_app_environment


class EnvironmentLoaderTest(unittest.TestCase):
    def test_process_selection_takes_priority_over_project_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            (base_dir / ".env").write_text(
                "CUST_APP_ENV_FILE=project.env\nSELECTED_VALUE=project\n",
                encoding="utf-8",
            )
            selected_env = base_dir / "selected.env"
            selected_env.write_text("SELECTED_VALUE=external\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {"CUST_APP_ENV_FILE": str(selected_env)},
                clear=True,
            ):
                loaded_path = load_app_environment(base_dir)

                self.assertEqual(loaded_path, selected_env.resolve())
                self.assertEqual(os.environ["SELECTED_VALUE"], "external")

    def test_missing_selected_environment_fails_loudly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            missing_env = base_dir / "missing.env"

            with patch.dict(
                os.environ,
                {"CUST_APP_ENV_FILE": str(missing_env)},
                clear=True,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "CUST_APP_ENV_FILE does not exist",
                ):
                    load_app_environment(base_dir)


if __name__ == "__main__":
    unittest.main()
