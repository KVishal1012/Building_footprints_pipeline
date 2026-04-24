import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from pipeline_runtime import (
    dataclass_config_kwargs,
    load_json_object,
    parse_places,
)


@dataclass
class ExampleConfig:
    data_dir: Path = Path("data")
    country: str = "USA"


class PipelineRuntimeTests(unittest.TestCase):
    def test_parse_places_accepts_strings_and_objects(self):
        places = parse_places(["Houston, Texas", {"city": "Chennai", "state": "TN"}])

        self.assertEqual(
            places,
            [
                {"city": "Houston", "state": "Texas"},
                {"city": "Chennai", "state": "TN"},
            ],
        )

    def test_unknown_config_field_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown config field"):
            dataclass_config_kwargs(
                {"not_a_field": True},
                ExampleConfig,
                repo_root=Path.cwd(),
            )

    def test_path_inside_venv_raises(self):
        with self.assertRaisesRegex(ValueError, "must not point inside .venv"):
            dataclass_config_kwargs(
                {"data_dir": ".venv/data"},
                ExampleConfig,
                repo_root=Path.cwd(),
            )

    def test_load_json_object_requires_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("[]")

            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                load_json_object(path)


if __name__ == "__main__":
    unittest.main()
