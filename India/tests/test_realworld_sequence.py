import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class RealworldSequenceTests(unittest.TestCase):
    def test_multicity_release_config_passes_dry_run(self):
        """Validate the strict Chennai and Bengaluru release template without data writes."""
        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_india_realworld_sequence.py",
                "--config",
                "India/realworld_sequence_multicity_config.example.json",
                "--verification-config",
                "India/production_verification.release.json",
                "--dry-run",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Validated sequence config for 2 place(s)", result.stderr)


if __name__ == "__main__":
    unittest.main()
