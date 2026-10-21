"""Windows desktop startup chooses the compatibility path unless opted out."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows renderer policy")
class RenderingTests(unittest.TestCase):
    def configuration(self, *arguments):
        environment = os.environ.copy()
        environment["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-logging"
        code = (
            "import sys; sys.argv=" + repr(["run.py", *arguments]) + "; "
            "import run, json, os; "
            "print(json.dumps({'flags':os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS','').split(),'argv':sys.argv}))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", code], env=environment,
                                cwd=Path(__file__).resolve().parent.parent,
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_default_disables_gpu_and_preserves_existing_flags(self):
        result = self.configuration()
        self.assertIn("--disable-gpu", result["flags"])
        self.assertIn("--disable-logging", result["flags"])

    def test_rendering_switches_are_consumed_before_qt_starts(self):
        hardware = self.configuration("--hardware-rendering")
        self.assertNotIn("--disable-gpu", hardware["flags"])
        self.assertEqual(hardware["argv"], ["run.py"])
        software = self.configuration("--software-rendering")
        self.assertIn("--disable-gpu", software["flags"])
        self.assertEqual(software["argv"], ["run.py"])


if __name__ == "__main__":
    unittest.main()
