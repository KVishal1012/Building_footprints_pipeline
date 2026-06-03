from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)


# Ensure the repository root is importable when the script is run from scripts/.
def add_repo_root_to_path() -> Path:
    """Ensure the repository root is importable when the script is run from scripts/."""
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


# Load the local SQL Server input module that contains run settings.
def load_input_module(module_name: str = "sql_server_inputs"):
    """Load the local SQL Server input module that contains run settings."""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        raise RuntimeError(
            "Missing sql_server_inputs.py. Copy sql_server_inputs.example.py to "
            "sql_server_inputs.py and fill in your server, database, baseline, "
            "buffer, output table, and target city inputs."
        ) from exc


# Run the SQL Server table-only pipeline from the local input module.
def main() -> None:
    """Run the SQL Server table-only pipeline from the local input module."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    add_repo_root_to_path()
    from structures_pipeline.sql_server import run_sql_server_pipeline_from_inputs

    input_module = load_input_module()
    result = run_sql_server_pipeline_from_inputs(input_module)
    dataframe = result.get("dataframe")
    if dataframe is not None:
        preview_rows = int(getattr(input_module, "DATAFRAME_PREVIEW_ROWS", 10))
        print(dataframe.head(preview_rows).to_string(index=False))
    if result.get("sql_export"):
        LOGGER.info("Exported SQL Server table: %s", result["sql_export"])


if __name__ == "__main__":
    main()
