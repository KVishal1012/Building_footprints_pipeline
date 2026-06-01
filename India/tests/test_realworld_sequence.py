import json
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

    def test_production_config_defers_parcels(self):
        """Keep the current release runnable while retaining a later parcel source spec."""
        production_config = json.loads(
            (REPO_ROOT / "India/realworld_sequence_multicity.production.json").read_text()
        )
        deferred_sources = json.loads(
            (REPO_ROOT / "India/deferred_parcel_sources.example.json").read_text()
        )

        self.assertFalse(production_config["full_source_overrides"]["use_parcels"])
        self.assertNotIn("parcel_source", production_config["places"][0])
        self.assertIn(
            "chennai_tamil_nadu_india",
            deferred_sources["parcel_sources"],
        )


if __name__ == "__main__":
    unittest.main()
