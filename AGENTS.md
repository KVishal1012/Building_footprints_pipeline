# Codex Instructions for Structures Repo

## Project Goal
This repo builds structure/building datasets using Python, OSMnx, Overture Maps, DuckDB, and geospatial processing.

## Environment
- macOS
- Python 3.12
- Virtual environment: .venv
- Main repo: Structures
- India-specific workflow lives in India/

## Coding Rules
- Write full working scripts, not fragments.
- Keep paths relative to the repo root.
- Use pathlib instead of hardcoded paths.
- Do not modify .venv, cache, data/output, or __pycache__.
- Do not overwrite raw data unless explicitly asked.
- Include logging and validation.

## Geospatial Rules
- Preserve CRS.
- Do not simplify geometry unless asked.
- Validate geometry before saving.
- Keep missing unit/occupancy fields as NULL/None.
- Do not derive occupant count unless explicitly asked.

## Performance
- Prefer DuckDB for large Overture processing.
- Use chunking where possible.
- Avoid loading all US-scale data into memory.
