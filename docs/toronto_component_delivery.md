# Toronto building-component delivery

The explicit `components` mode prepares a **customer candidate**, with source qualification enforced. The legacy `buildings` mode retains its whole-building identity requirement; it is unsuitable for this component dataset.

```sh
python3 scripts/run_toronto_pilot.py --delivery-mode components \
  --citywide-dir data/output/toronto/citywide-internal-003 \
  --source-manifest data/local/toronto_source_review/2026-10-08/component_qualification.json \
  --study-area data/output/toronto/internal-sample-001/study_area.gpkg \
  --output-dir data/output/toronto/component-candidate-001
```

Existing output paths are refused. Use a new directory for subsequent runs. The builder checks the qualified parent checksum, evidence checksums, source identity and conflict inventory. It preserves complete intersecting geometry, snapshot IDs, source mapping category and original-row provenance. Areas are full **component footprint areas**, calculated in EPSG:26917 and stored as `FootprintArea_m2` for compatibility. Component count does not equal building count; overlapping areas must not be summed as floor area or unique ground coverage.

Limits: 5 km² and 5,000 intersecting original source records, including repeats and excluded conflicts, without truncation. A parent with quarantined geometry is rejected until its spatial scope can be resolved; the qualified parent has none. All 37 conflict groups / 74 variants remain excluded. Height/elevation fields are omitted via an explicit field allowlist. Historical citywide and internal demo artifacts are unchanged.

The package includes components/study_area/source_provenance layers, CSVs, field dictionary, source qualification/evidence, QA, exclusions, checksummed manifest, handover, portable QGIS project and labelled preview. Provenance `OutputLayer=structures` is intentionally the original parent partition. Only boundary geometry is copied.

Status remains `candidate_pending_buyer_acceptance`; building a candidate does not authorize delivery or establish buyer suitability. Native QGIS review uses offscreen rendering, and visual findings/test results are recorded in a supplemental validation file. No GUI performance certification is implied.
