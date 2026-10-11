"""Component mode retains lineage, excludes conflicts and gates qualified snapshots."""
import json
import sqlite3
import geopandas as gpd
import pandas as pd
import pytest
from tests.test_toronto_demo import inputs
from scripts.build_toronto_demo import build_demo, read_selection
from scripts.toronto_components import FIELDS
from structures_pipeline.toronto import checksum


@pytest.fixture
def qualified(inputs):
    parent,boundary,out=inputs
    manifest=json.loads((parent/'manifest.json').read_text())
    evidence=parent/'evidence.txt'; evidence.write_text('Fixture publisher confirmation')
    q=dict(commercial_use_review='approved',contextual_use_review='approved',identity_review='building_components_no_master_id',source_bundle_sha256=manifest['source_bundle_sha256'],parent_geopackage_sha256=manifest['files']['toronto_citywide_internal.gpkg'],reviewed_by='test',reviewed_at='2026-10-09',source_url='https://example.test/source',license_url='https://example.test/license',attribution='test',limitations=['context only'],excluded_conflict_groups=1,excluded_conflict_variants=2,evidence=[dict(path='evidence.txt',sha256=checksum(evidence))])
    path=parent/'qualification.json';path.write_text(json.dumps(q))
    return parent,boundary,out,path


def test_component_export(qualified):
    parent,boundary,out,q=qualified
    before=checksum(parent/'toronto_citywide_internal.gpkg')
    report=build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)
    assert report['component_count']==1 and report['provenance_rows']==2
    assert report['intersecting_source_records']==4 and report['local_conflict_variants_excluded']==2
    assert report['boundary_crossings']==1
    result=gpd.read_file(out/'toronto_components.gpkg',layer='components')
    original=read_selection(parent/'toronto_citywide_internal.gpkg','structures',gpd.read_file(boundary))
    pd.testing.assert_frame_equal(result[FIELDS],original[FIELDS])
    assert not any('height' in c.lower() or 'elev' in c.lower() for c in result)
    assert result.RecordType.eq('building_component').all()
    with sqlite3.connect(out/'toronto_components.gpkg') as db, sqlite3.connect(parent/'toronto_citywide_internal.gpkg') as src:
        pd.testing.assert_frame_equal(pd.read_sql('select * from source_provenance order by source_fid',db),pd.read_sql("select * from source_provenance where OutputLayer='structures' order by source_fid",src))
    assert checksum(parent/'toronto_citywide_internal.gpkg')==before
    with pytest.raises(FileExistsError):build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)


@pytest.mark.parametrize('key,value',[('commercial_use_review','pending'),('identity_review','one_record_per_building'),('source_bundle_sha256','wrong'),('parent_geopackage_sha256','wrong'),('excluded_conflict_groups',37)])
def test_qualification_rejection(qualified,key,value):
    parent,boundary,out,q=qualified;data=json.loads(q.read_text());data[key]=value;q.write_text(json.dumps(data))
    with pytest.raises(ValueError):build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)
    assert not out.exists()


def test_evidence_changed(qualified):
    parent,boundary,out,q=qualified;(parent/'evidence.txt').write_text('changed')
    with pytest.raises(ValueError,match='evidence checksum'):build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)


def test_source_limit_includes_repeats_and_exclusions(qualified,monkeypatch):
    parent,boundary,out,q=qualified
    original=read_selection
    def selection(*args):
        frame=original(*args)
        if args[1]=='conflict_review':frame['source_record_count']=2500
        return frame
    monkeypatch.setattr('scripts.build_toronto_demo.read_selection',selection)
    with pytest.raises(ValueError,match='5000 intersecting original'):build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)


def test_area_limit(qualified):
    from shapely.geometry import box
    parent,boundary,out,q=qualified;boundary.unlink()
    gpd.GeoDataFrame(geometry=[box(630000,4835000,633000,4838000)],crs=26917).to_file(boundary)
    with pytest.raises(ValueError,match='5 km²'):build_demo(parent,boundary,out,delivery_mode='components',qualification_file=q)
