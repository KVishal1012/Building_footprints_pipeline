# Production-Style Runs

Run commands should be launched from the repo root.

## Root Structure Pipeline

```bash
.venv/bin/python scripts/run_root_pipeline.py --config configs/root_pipeline.example.json
```

## India Structure Pipeline

```bash
.venv/bin/python scripts/run_india_pipeline.py --config India/pipeline_config.example.json
```

## India Processing Pipeline

```bash
.venv/bin/python scripts/run_india_processing.py --config India/processing_pipeline_config.example.json
```

## Config Shape

- `logging.level`: Python logging level such as `INFO` or `DEBUG`.
- `places`: non-empty list of `"City, State"` strings or objects with `city` and `state`.
- `source_config`: India processing source JSON path.
- `config`: fields passed to the pipeline dataclass.

Relative paths in config files are resolved from the repo root. Config validation rejects unknown dataclass fields and paths that point inside `.venv`.

To validate a config without running the pipeline, add `--dry-run` to any command.
