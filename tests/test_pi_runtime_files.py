from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = PROJECT_ROOT / 'scripts' / 'run.sh'
SERVICE_FILE = PROJECT_ROOT / 'services' / 'run_photo_display.service'


class PiRuntimeFileTests(unittest.TestCase):
    def test_run_script_uses_project_virtualenv(self) -> None:
        content = RUN_SCRIPT.read_text(encoding='utf-8')
        self.assertIn('source "${SCRIPT_DIR}/../venv/bin/activate"', content)
        self.assertIn('python "${SCRIPT_DIR}/run_photo_display.py"', content)

    def test_service_file_contains_expected_pi_runtime_settings(self) -> None:
        content = SERVICE_FILE.read_text(encoding='utf-8')
        self.assertIn('Environment="DISPLAY=:0"', content)
        self.assertIn('Environment="XAUTHORITY=/home/pi/.Xauthority"', content)
        self.assertIn('User=pi', content)
        self.assertIn('ExecStart=/home/pi/Digital-Photo-Frame/scripts/run.sh', content)
        self.assertIn('Restart=always', content)


if __name__ == '__main__':
    unittest.main()
