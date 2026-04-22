# India Future Modeling Plan

The active `structure_pipeline.py` is structure-only. It should produce reliable structure polygons and source-derived structure attributes before model layers or planning agents are added.

Authoritative planning context is tracked in `source_registry.json`. Use NRSC/ISRO as the core satellite-derived planning source, Survey of India as the statutory base-map anchor, and IUDX plus municipal GIS for operational and implementation layers.

Deep-learning and planning work now belongs in `processing_pipeline.py`, not in the structure pipeline. The processing pipeline standardizes exported model layers and writes a separate structure-to-processing link table. Those layers join back to the structure output through `StructureID`, parcel identifiers, or spatial relationships.

Use `processing_sources.example.json` as the source-spec template. Raw model outputs should be stored under `data/processing/raw/`, and normalized outputs are written under `data/processing/output/`.

## Chennai-First Future Tracks

### 1. SegFormer / U-Net Segmentation

Use this later for land-cover masks, built-up area, water, roads, vegetation, informal settlement extent, and building-footprint masks.

Expected output columns:

- `class` or `label`
- `score` or `confidence`
- optional `model` or `model_id`
- polygon geometry, WKT, or point coordinates

Keep these outputs in the processing layer table. Do not add them to the structure pipeline schema.

### 2. Change Detection

Use this later for new construction, demolition, urban expansion, wetland loss, floodplain encroachment, shoreline change, and impervious-surface growth.

Expected output columns:

- `change_type` or `label`
- `confidence` or `score`
- optional `before_date` / `after_date`
- polygon geometry, WKT, or point coordinates

Keep temporal model output in the processing layer table keyed by run ID, date range, and spatial relationship to structures.

### 3. ConvLSTM / ST-Transformer Flood Prediction

Use this later for rainfall-driven flood risk, forecast depth, forecast probability, and scenario planning. For Chennai, prioritize Adyar, Cooum, Buckingham Canal, Pallikaranai marsh, low-lying coastal zones, and historically waterlogged corridors.

Expected output columns:

- `risk` or `flood_risk`
- `depth_m`
- `probability`
- `horizon_hr`
- optional `scenario`, `timestamp`, `model`
- polygon geometry, WKT, or point coordinates

Keep forecast output in processing layers so multiple horizons and rainfall events can coexist without changing the structure schema.

### 4. Urban Planning Layers

Use this later for suitability, transit-oriented growth, redevelopment priority, density pressure, green-cover deficit, heat exposure, and drainage intervention priority.

Expected output columns:

- `planning_label`, `suitability`, `growth_class`, or `label`
- `score` or `suitability_score`
- optional `horizon`, `model`
- polygon geometry, WKT, or point coordinates

Keep planning recommendations in processing layers or separate agent-owned outputs with clear provenance, assumptions, and date stamps.

## Practical Order For Chennai

1. Build the base structure layer with Overture, Microsoft, and OSM.
2. Add parcel layers where a reliable municipal or cadastral source is available.
3. Validate schema stability, geometry validity, source counts, and duplicate IDs.
4. Build separate model layer generators for built-up/water/green cover.
5. Build separate temporal-change layers across pre-monsoon/post-monsoon or multi-year image pairs.
6. Build separate flood polygons or grid cells for scenario analysis.
7. Build separate planning suitability layers that combine hazard, growth, transit, land use, and parcel/context data.
8. Use `StructureID` as the join key for downstream dashboards, maps, and scenario analysis.
