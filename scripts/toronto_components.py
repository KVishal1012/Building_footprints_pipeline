"""Qualification and explicit field contract for contextual component candidates."""
import json
from pathlib import Path
from structures_pipeline.toronto import checksum

FIELDS = ['StructureID', 'SourceRecordID', 'representative_fid', 'source_record_count',
          'duplicate_group', 'DuplicateStatus', 'GeometryStatus', 'ZRemoved',
          'BLDG_SRC', 'FootprintSource', 'FootprintArea_m2', 'FootprintAreaMethod',
          'PostRepairCoincidentXY', 'geometry']


def validate_qualification(path, parent):
    if path is None:
        raise ValueError('Component mode requires source qualification.')
    q = json.loads(Path(path).read_text())
    expected = {'commercial_use_review': 'approved',
                'contextual_use_review': 'approved',
                'identity_review': 'building_components_no_master_id',
                'source_bundle_sha256': parent['source_bundle_sha256'],
                'parent_geopackage_sha256': parent['files']['toronto_citywide_internal.gpkg']}
    for key, value in expected.items():
        if q.get(key) != value:
            raise ValueError(f'Unqualified component source: {key}')
    for key in ['reviewed_by', 'reviewed_at', 'source_url', 'license_url', 'attribution', 'limitations', 'evidence']:
        if not q.get(key):
            raise ValueError(f'Missing qualification: {key}')
    for item in q['evidence']:
        if checksum(Path(path).parent / item['path']) != item['sha256']:
            raise ValueError('Qualification evidence checksum mismatch.')
    for key in ['excluded_conflict_groups', 'excluded_conflict_variants']:
        if not isinstance(q.get(key), int) or q[key] < 0:
            raise ValueError(f'Missing conflict inventory: {key}')
    return q


def project_components(frame):
    result = frame[FIELDS].copy()
    result['RecordType'] = 'building_component'
    result['IdentityStatus'] = 'component_snapshot_no_master_id'
    return result


def component_dictionary(frame):
    meanings = {
        'StructureID': 'Unchanged parent snapshot component variant ID; not persistent across releases or a whole-building ID.',
        'SourceRecordID': 'Unchanged representative source-bundle hash plus original OGR FID.',
        'representative_fid': 'Lowest original OGR FID in collapsed exact repeats; no authority ranking.',
        'source_record_count': 'Original source rows represented by this component variant.',
        'duplicate_group': 'Parent exact XY duplicate group, empty when absent; conflicts excluded.',
        'DuplicateStatus': 'Parent duplicate-audit classification.',
        'GeometryStatus': 'Parent valid_source or repaired_make_valid result.',
        'ZRemoved': 'Parent removal of Z coordinates for 2D delivery.',
        'BLDG_SRC': 'Unchanged source mapping-origin category, described in README_Metadata.xlsx.',
        'FootprintSource': 'Parent source namespace.',
        'FootprintArea_m2': 'Derived complete component footprint area in square metres, EPSG:26917; not floor area or whole-building area.',
        'FootprintAreaMethod': 'Parent area method preserved.',
        'PostRepairCoincidentXY': 'Parent post-repair exact XY coincidence flag.',
        'geometry': 'Complete prepared component geometry preserved byte-for-byte from parent, EPSG:4326.',
        'RecordType': 'Publisher-confirmed building_component.',
        'IdentityStatus': 'Snapshot component identity; no master whole-building ID exists in this release.'}
    rows = ['# Building-component field dictionary', '', '| Field | Meaning |', '| --- | --- |']
    rows += [f'| {name} | {meanings[name]} |' for name in frame]
    rows += ['', 'All height and elevation fields are omitted. Components can overlap; summed component areas do not establish unique built area or floor area.', '',
             '## Original-record provenance', '',
             'source_fid and SourceRecordID identify every original row; representative_fid and StructureID link to the retained variant. action records retained_variant or exact_repeat_collapsed. GeometryStatus and OutputLayer preserve parent processing values; OutputLayer=structures refers to the parent, while the delivered layer is components.', '',
             'study_area contains only the supplied boundary geometry, transformed to EPSG:4326. No customer boundary attributes are copied.']
    return '\n'.join(rows)+'\n'


def handover():
    return '''# Toronto building-component GIS preparation — customer candidate

Open toronto_components.qgz in QGIS. The components layer contains complete intersecting 2D footprints and calculated component areas. Join CSV and source_provenance using StructureID. IDs are snapshot-specific; a component is not a whole building. Multiple original rows can map to one retained component.

All unresolved coincident-footprint conflicts remain excluded; excluded_records.csv lists intersecting variants. The QA report gives global and local exclusions, original-source counts, boundary crossings, and repairs. No height fields are delivered. Components may overlap, and area sums are not whole-building or floor areas. Source observation dates are unknown; the metadata's 2015 LiDAR reference applies to the LiDAR height source only.

Contains information licensed under the Open Government Licence – Toronto.
https://open.toronto.ca/open-data-licence/
Source: https://open.toronto.ca/dataset/3d-massing/

Commercial use and component identity are supported by the publisher response supplied by the user on 2026-10-08. No City endorsement, surveyed accuracy, completeness, or legal/regulatory suitability is asserted. See source_qualification.json for the evidence record and limitations.

Status: candidate_pending_buyer_acceptance. Before customer delivery, agree the buyer's contextual use, input permissions, boundary, limits, fields, price, timing and acceptance criteria. Review the actual buyer-area package in the agreed GIS. This demonstration does not establish willingness to pay or buyer suitability.
'''
