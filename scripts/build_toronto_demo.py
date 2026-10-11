"""Extract an immutable, provenance-preserving internal demo from a citywide pack."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from structures_pipeline.toronto import checksum

STATUS = "internal_only_not_for_customer_delivery"
MAX_FEATURES = 500


def read_selection(gpkg: Path, layer: str, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Use a spatial bbox prefilter followed by exact intersection, without clipping."""
    info = pyogrio.read_info(gpkg, layer=layer)
    if not info['crs']:
        raise ValueError(f"Unknown CRS: {layer}")
    area = boundary.to_crs(info['crs']).geometry.union_all()
    frame = gpd.read_file(gpkg, layer=layer, bbox=area.bounds)
    return frame.loc[frame.intersects(area)].sort_values('StructureID').reset_index(drop=True)


def validate_selection(frame: gpd.GeoDataFrame, lineage: pd.DataFrame, conflicts: pd.DataFrame, max_features: int = MAX_FEATURES) -> None:
    """Enforce usable geometry, conflict separation, and complete many-to-one lineage."""
    if not 0 < len(frame) <= max_features:
        raise ValueError(f"Selection has {len(frame)} features; require 1–{max_features}, without truncation.")
    if frame.crs is None or frame.crs.to_epsg() != 4326:
        raise ValueError('Expected EPSG:4326 citywide structures.')
    if (frame.geometry.isna().any() or frame.geometry.is_empty.any() or
            not frame.geometry.is_valid.all() or not frame.geom_type.isin(['Polygon', 'MultiPolygon']).all()):
        raise ValueError('Unusable selected geometry.')
    if frame.StructureID.isna().any() or not frame.StructureID.is_unique or not frame.OutputLayer.eq('structures').all():
        raise ValueError('Invalid main-layer identity or partition.')
    groups = set(conflicts.duplicate_group.dropna()) - {''}
    if set(frame.StructureID) & set(conflicts.StructureID) or set(frame.duplicate_group) & groups:
        raise ValueError('Conflict leaked into structures.')
    if not lineage.SourceRecordID.is_unique or not lineage.source_fid.is_unique:
        raise ValueError('Duplicate provenance identity.')
    counts = lineage.groupby('StructureID').size().reindex(frame.StructureID, fill_value=0)
    if (set(lineage.StructureID) != set(frame.StructureID) or
            not lineage.OutputLayer.eq('structures').all() or
            counts.tolist() != frame.source_record_count.tolist()):
        raise ValueError('Broken provenance counts or partition.')
    reps = frame.set_index('StructureID')
    if not lineage.representative_fid.eq(lineage.StructureID.map(reps.representative_fid)).all():
        raise ValueError('Broken representative provenance.')
    retained = lineage.loc[lineage.action.eq('retained_variant')].set_index('StructureID')
    if not retained.index.is_unique or set(retained.index) != set(reps.index):
        raise ValueError('Missing retained-variant provenance.')
    if not retained.SourceRecordID.reindex(reps.index).eq(reps.SourceRecordID).all():
        raise ValueError('Broken retained source identity.')


def verify_csv(path: Path, expected: pd.DataFrame) -> None:
    """Check CSV values, retaining empty strings and round-tripping IEEE floats."""
    actual = pd.read_csv(path, keep_default_na=False, float_precision='round_trip')
    for name in expected:
        if pd.api.types.is_numeric_dtype(expected[name]):
            actual[name] = pd.to_numeric(actual[name], errors='raise')
        elif pd.api.types.is_bool_dtype(expected[name]):
            actual[name] = actual[name].map({'True': True, 'False': False, True: True, False: False})
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)


def field_dictionary(frame: gpd.GeoDataFrame) -> str:
    """Document every exported field without assigning unverified source semantics."""
    source = {'MAX_HEIGHT', 'AVG_HEIGHT', 'HEIGHT_MSL', 'SURF_ELEV', 'HEIGHT_SRC', 'BLDG_SRC', 'LONGITUDE', 'LATITUDE'}
    definitions = {
        'MIN_HEIGHT': 'Project normalization: raw zero becomes null; nonzero preserved. Units/meaning unverified.',
        'MIN_HEIGHT_RAW': 'Original MIN_HEIGHT; zero retained. Units/meaning unverified.',
        'MinHeightStatus': 'zero_assumed_missing, source_missing, or source_value_unverified.',
        'MinHeightMethod': 'zero_to_null_provisional_project_rule; not a publisher definition.',
        'StructureID': 'Parent snapshot variant ID; not a persistent real-world building ID.',
        'SourceRecordID': 'Source bundle SHA-256 plus original representative OGR FID.',
        'representative_fid': 'Lowest original OGR FID among identical records; not authority ranking.',
        'source_record_count': 'Number of original source records mapped to this retained variant.',
        'duplicate_group': 'Parent exact XY duplicate group; empty means no group.',
        'DuplicateStatus': 'Parent duplicate-audit classification; conflicting groups excluded.',
        'GeometryStatus': 'Parent valid_source or repaired_make_valid processing result.',
        'ZRemoved': 'Whether source Z coordinates were removed for the parent 2D footprint.',
        'City': 'Project context: Toronto; not independent boundary certification.',
        'State': 'Project context: Ontario.', 'Country': 'Project context: Canada.',
        'FootprintSource': 'Parent source namespace.',
        'FootprintAreaMethod': 'Area of complete prepared footprint calculated in EPSG:26917.',
        'FootprintArea_m2': 'Derived complete-footprint area in square metres, preserved from parent.',
        'IdentityStatus': 'snapshot_record_not_verified_building.',
        'OutputLayer': 'Parent partition; always structures in this demo.',
        'PostRepairCoincidentXY': 'Parent post-repair exact XY coincidence flag; no additional collapse.',
        'geometry': 'Unclipped prepared parent Polygon/MultiPolygon, 2D EPSG:4326.',
    }
    lines = ['# Field dictionary', '', 'Height units and semantics are unverified. Heights are excluded from the base paid offer.', '',
             '| Field | Storage type | Origin / interpretation |', '| --- | --- | --- |']
    for name in frame:
        meaning = ('Unchanged source attribute; publisher definition unverified.' if name in source else definitions.get(name))
        if meaning is None:
            raise ValueError(f'Undocumented field: {name}')
        lines.append(f'| {name} | {frame[name].dtype} | {meaning} |')
    lines += ['', '## Provenance table', '',
              '`source_fid`: every original OGR FID; `representative_fid`: retained representative; '
              '`SourceRecordID`: original snapshot identity; `StructureID`: retained variant join key; '
              '`action`: retained_variant or exact_repeat_collapsed; `OutputLayer` and `GeometryStatus`: parent processing results.', '',
              'The study_area layer preserves the supplied demonstration boundary and attributes; it is not an official administrative boundary.']
    return '\n'.join(lines) + '\n'


def build_demo(citywide: Path, study_area: Path, output: Path, qgis_python: Path | None = None, *, delivery_mode: str = "internal_demo", qualification_file: Path | None = None) -> dict:
    """Validate inputs, extract complete records, verify artifacts, and publish atomically."""
    if output.exists():
        raise FileExistsError(output)
    if delivery_mode not in {'internal_demo', 'components'}:
        raise ValueError('Unknown delivery mode.')
    components = delivery_mode == 'components'
    limit = 5000 if components else MAX_FEATURES
    status = 'candidate_pending_buyer_acceptance' if components else STATUS
    parent = json.loads((citywide / 'manifest.json').read_text(encoding='utf-8'))
    gpkg = citywide / 'toronto_citywide_internal.gpkg'
    expected_hash = parent['files'][gpkg.name]
    if checksum(gpkg) != expected_hash:
        raise ValueError('Parent checksum mismatch.')
    qualification = None
    if components:
        from scripts.toronto_components import validate_qualification
        qualification = validate_qualification(qualification_file, parent)
    boundary_hash = checksum(study_area)
    if len(pyogrio.list_layers(study_area)) != 1:
        raise ValueError('Supply a single-layer study boundary.')
    boundary = gpd.read_file(study_area)
    if (boundary.empty or boundary.crs is None or boundary.geometry.isna().any() or
            boundary.geometry.is_empty.any() or not boundary.geometry.is_valid.all() or
            not boundary.geom_type.isin(['Polygon', 'MultiPolygon']).all()):
        raise ValueError('Invalid boundary or unknown CRS.')
    if components and boundary.to_crs(26917).geometry.union_all().area > 5_000_000:
        raise ValueError('Study area exceeds 5 km².')
    selected = read_selection(gpkg, 'structures', boundary)
    if not 0 < len(selected) <= limit:
        raise ValueError(f'Selection has {len(selected)} features; require 1–{limit}, without truncation.')
    with sqlite3.connect(gpkg.resolve().as_uri() + '?mode=ro', uri=True) as db:
        conflicts = pd.read_sql_query('SELECT StructureID, duplicate_group FROM conflict_review', db)
        placeholders = ','.join('?' for _ in selected.StructureID)
        lineage = pd.read_sql_query(f'SELECT * FROM source_provenance WHERE StructureID IN ({placeholders}) ORDER BY source_fid', db, params=selected.StructureID.tolist())
        leaked = db.execute('SELECT count(*) FROM structures s JOIN conflict_review c ON s.StructureID=c.StructureID OR (s.duplicate_group=c.duplicate_group AND c.duplicate_group<>\'\')').fetchone()[0]
        if leaked:
            raise ValueError('Parent main layer contains conflicts.')
    validate_selection(selected, lineage, conflicts, limit)
    excluded_full = read_selection(gpkg, 'conflict_review', boundary)
    excluded = excluded_full[['StructureID', 'duplicate_group']].copy()
    intersecting_source_records = len(lineage) + int(excluded_full.source_record_count.sum())
    if components:
        if intersecting_source_records > 5000:
            raise ValueError('More than 5000 intersecting original source records before exclusions.')
        with sqlite3.connect(gpkg.resolve().as_uri() + '?mode=ro', uri=True) as db:
            if db.execute('SELECT count(*) FROM geometry_quarantine').fetchone()[0]:
                raise ValueError('Parent has quarantined geometry; resolve spatial scope before component export.')
        if len(conflicts) != qualification['excluded_conflict_variants'] or conflicts.duplicate_group.nunique() != qualification['excluded_conflict_groups']:
            raise ValueError('Conflict inventory differs from qualified snapshot.')
    excluded['reason'] = 'unresolved_conflict_excluded'
    area = boundary.to_crs(selected.crs).geometry.union_all()
    crossings = selected.loc[~selected.geometry.covered_by(area), 'StructureID'].tolist()
    repairs = selected.loc[selected.GeometryStatus.eq('repaired_make_valid'), 'StructureID'].tolist()
    if components:
        from scripts.toronto_components import project_components, component_dictionary, handover
        selected = project_components(selected)
        # Preserve parent provenance verbatim, including its historical OutputLayer value.
        boundary = gpd.GeoDataFrame(geometry=boundary.geometry, crs=boundary.crs).reset_index(drop=True)
    layer_name = 'components' if components else 'structures'
    file_stem = 'toronto_components' if components else 'toronto_demo'
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.demo-', dir=output.parent))
    try:
        target = stage / f'{file_stem}.gpkg'
        selected.to_file(target, layer=layer_name, index=False, promote_to_multi=False, geometry_type='Unknown')
        boundary.to_crs(4326).to_file(target, layer='study_area', index=False)
        with sqlite3.connect(target) as db:
            lineage.to_sql('source_provenance', db, index=False, if_exists='fail')
            db.execute("INSERT INTO gpkg_contents(table_name,data_type,identifier) VALUES ('source_provenance','attributes','source_provenance')")
            db.execute('CREATE UNIQUE INDEX provenance_source_id ON source_provenance(SourceRecordID)')
            db.execute('CREATE INDEX provenance_structure_id ON source_provenance(StructureID)')
        attributes = pd.DataFrame(selected.drop(columns='geometry'))
        attributes.to_csv(stage / 'attributes.csv', index=False)
        lineage.to_csv(stage / 'source_provenance.csv', index=False)
        excluded.to_csv(stage / 'excluded_records.csv', index=False)
        restored = gpd.read_file(target, layer=layer_name)
        pd.testing.assert_frame_equal(restored.drop(columns='geometry'), attributes, check_dtype=False, check_exact=True)
        if restored.crs != selected.crs or not (restored.geometry.to_wkb() == selected.geometry.to_wkb()).all():
            raise ValueError('Geometry/CRS roundtrip mismatch.')
        restored_boundary = gpd.read_file(target, layer='study_area')
        pd.testing.assert_frame_equal(restored_boundary, boundary.to_crs(4326), check_dtype=False)
        with sqlite3.connect(target) as db:
            pd.testing.assert_frame_equal(pd.read_sql_query('SELECT * FROM source_provenance ORDER BY source_fid', db), lineage, check_dtype=False)
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('GeoPackage integrity failure.')
        verify_csv(stage / 'attributes.csv', attributes)
        verify_csv(stage / 'source_provenance.csv', lineage)
        report = {'status': status, 'delivery_mode': delivery_mode, 'intersecting_source_records': intersecting_source_records, 'features': len(selected), 'provenance_rows': len(lineage),
                  'collapsed_original_repeats': len(lineage)-len(selected), 'boundary_crossings': len(crossings),
                  'boundary_crossing_ids': crossings, 'included_repairs': repairs,
                  'parent_conflict_groups_excluded': int(conflicts.duplicate_group.nunique()),
                  'parent_conflict_variants_excluded': len(conflicts), 'local_conflict_variants_excluded': len(excluded),
                  'local_conflict_groups_excluded': int(excluded.duplicate_group.nunique()),
                  'input_candidates_in_area': len(selected)+len(excluded), 'accounting_reconciled': True,
                  'roundtrip_verified': True, 'parent_checksum_unchanged': True}
        (stage / 'quality_report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        (stage / 'field_dictionary.md').write_text(component_dictionary(selected) if components else field_dictionary(selected), encoding='utf-8')
        (stage / 'HANDOVER.md').write_text(
            '# Toronto internal demonstration\n\nNOT FOR CUSTOMER DELIVERY.\n\n'
            'Open toronto_demo.qgz in QGIS. structures contains complete intersecting footprints; '
            'study_area is the demonstration boundary. Join attributes.csv by StructureID. '
            'source_provenance is one-to-many: several original records may map to one retained variant.\n\n'
            'All citywide conflicting variants remain excluded. excluded_records.csv lists any within this area. '
            'Heights are source context only, with unverified units/semantics; MIN_HEIGHT zero is provisionally null '
            'while MIN_HEIGHT_RAW preserves the original. No other height is normalized. '
            'Snapshot records are not verified individual buildings. Source observation date is unknown.\n\n'
            'Source: https://open.toronto.ca/dataset/3d-massing/\n\n'
            'Contains information licensed under the Open Government Licence – Toronto. '
            'https://open.toronto.ca/open-data-licence/ — selected-resource applicability remains under review.\n\n'
            'Pending: commercial-use, intended-use suitability, and building-identity reviews. '
            'No survey accuracy, coverage completeness, legal suitability, or City endorsement is asserted. '
            'See qgis_review.json for native rendering checks; human/model visual findings are recorded separately.\n', encoding='utf-8')
        if components:
            for item in qualification['evidence']:
                evidence_source = qualification_file.parent / item['path']
                evidence_target = stage / ('source_evidence_' + evidence_source.name)
                shutil.copyfile(evidence_source, evidence_target)
                item['path'] = evidence_target.name
            (stage / 'HANDOVER.md').write_text(handover(), encoding='utf-8')
            (stage / 'source_qualification.json').write_text(json.dumps(qualification, indent=2)+'\n', encoding='utf-8')
            report['component_count'] = len(selected)
            (stage / 'quality_report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        interpreter = qgis_python or Path(os.environ.get('QGIS_PYTHON', '/Applications/QGIS.app/Contents/MacOS/python'))
        subprocess.run([str(interpreter), str(Path(__file__).with_name('qgis_review_toronto_demo.py')), '--output-dir', str(stage.resolve())],
                       check=True, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
        if checksum(gpkg) != expected_hash or checksum(study_area) != boundary_hash:
            raise ValueError('Inputs changed during demo build.')
        manifest = {'schema_version': 'toronto-components-1' if components else 'toronto-demo-1', 'status': status, 'delivery_mode': delivery_mode,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'source_as_of': parent['source_as_of'],
                    'parent_manifest_sha256': checksum(citywide/'manifest.json'), 'parent_geopackage_sha256': expected_hash,
                    'source_bundle_sha256': parent['source_bundle_sha256'], 'study_area_sha256': boundary_hash,
                    'source_url': parent['source_url'], 'selection': 'complete footprints intersecting supplied boundary; structures only',
                    'pending': ['buyer_specific_suitability', 'input_permissions', 'scope_agreement', 'visual_review'] if components else ['commercial_use_review', 'suitability_review', 'building_identity_review'],
                    'files': {p.name: checksum(p) for p in sorted(stage.iterdir()) if p.is_file()}}
        if components:
            manifest['qualification_sha256'] = checksum(qualification_file)
            manifest['selection'] = 'complete building components intersecting boundary; all conflicts excluded'
            manifest['height_fields'] = 'omitted'
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage)
        raise
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--citywide-dir', type=Path, required=True)
    parser.add_argument('--study-area', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_demo(args.citywide_dir, args.study_area, args.output_dir), indent=2))
