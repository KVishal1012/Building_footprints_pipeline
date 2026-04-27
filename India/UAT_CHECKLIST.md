# India Pipeline UAT Checklist

UAT target: Chennai, Tamil Nadu.

Run date: 2026-04-24.

## 1. Environment And Config Readiness

- [x] Confirmed repo is on branch `test`.
- [x] Confirmed `.venv/bin/python` exists and core dependencies import.
- [x] Confirmed India structure dry-run passes.
- [x] Confirmed India processing dry-run passes.
- [x] Confirmed unknown config fields fail fast with a clear validation error.
- [x] Confirmed paths pointing inside `.venv` are rejected.

## 2. India Structure Pipeline UAT

- [x] Ran India structure pipeline for Chennai using `India/pipeline_config.example.json`.
- [x] Confirmed expected city and master output files were created.
- [x] Confirmed output row count is greater than zero: `744,748`.
- [x] Confirmed CRS exists: `EPSG:4326`.
- [x] Confirmed every row has non-null `StructureID`.
- [x] Confirmed `StructureID` values are unique.
- [x] Confirmed geometries are non-null, non-empty, valid polygons or multipolygons.
- [x] Confirmed final columns exactly match the approved India structure schema.
- [x] Confirmed India defaults are respected: `Country = India`, `State = Tamil Nadu`, `use_nsi = false`, `use_census = false`.
- [x] Confirmed optional NSI, census, and parcel fields remain null when sources are disabled or not configured.
- [x] Confirmed metadata sidecars include run timestamp, row counts, city/state/country where applicable, bounds, source counts, and config snapshot.

## 3. India Processing Pipeline UAT

- [x] Confirmed `India/data/output/structures_master.parquet` exists before processing run.
- [x] Created controlled UAT processing sources without overwriting existing raw files.
- [x] Ran India processing pipeline using `India/processing_pipeline_config.example.json`.
- [x] Confirmed processing output files and metadata sidecars were created.
- [x] Confirmed processing layer rows use the approved processing schema.
- [x] Confirmed processing links use the approved link schema.
- [x] Confirmed linked rows reference valid `StructureID` values from `structures_master.parquet`.
- [x] Confirmed polygon layers use `area_intersection` matching.
- [x] Confirmed point layers use `point_within_structure` matching.
- [x] Confirmed `MatchArea_m2`, `StructureCoverage`, and `LayerCoverage` are populated for polygon matches.
- [x] Confirmed processing metadata includes row counts, layer type counts, output columns, and config snapshot.

## 4. Negative And Failure-Mode UAT

- [x] Missing required processing source in strict mode fails clearly.
- [x] Malformed processing source config fails before producing valid outputs.
- [x] Duplicate `StructureID` validation fails.
- [x] Empty structure output with `fail_on_empty_output = true` fails.
- [x] Invalid geometries in controlled input are repaired or rejected according to pipeline rules.
- [x] No existing raw data files were overwritten during UAT.

## 5. Regression Checks

- [x] Compile checks passed for India structure and processing scripts.
- [x] India unit tests passed: `10` tests.
- [x] Runtime tests passed: `4` tests.
- [x] Confirmed generated data and bytecode artifacts are not intended for commit.

## UAT Finding Fixed

Processing UAT exposed a mixed-geometry bug: point processing layers were dropped when processed in the same batch as polygon layers. `India/processing_pipeline.py` now splits point and non-point layers internally so mixed batches produce both `point_within_structure` and `area_intersection` links.

## Acceptance Status

- [x] India structure pipeline produces non-empty, valid GeoParquet outputs for Chennai.
- [x] India processing pipeline links processing layers back to structures.
- [x] Metadata sidecars are present and match the run.
- [x] Strict-mode failures are clear and intentional.
- [x] Existing unit/runtime tests pass.
- [x] Generated UAT raw/output artifacts should remain uncommitted.
