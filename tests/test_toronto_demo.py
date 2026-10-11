"""Exercise demo exclusion, lineage, spatial selection, and publication contracts."""
import json
import sqlite3

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from scripts.build_toronto_citywide import build_citywide
from scripts.build_toronto_internal_sample import FIELDS
from scripts.build_toronto_demo import build_demo, validate_selection, read_selection
from structures_pipeline.toronto import checksum


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    a=box(630000,4835000,630010,4835010)
    b=box(630020,4835000,630030,4835010)
    frame=gpd.GeoDataFrame(geometry=[a,a,b,b],crs=26917).to_crs(3857)
    for field in FIELDS:
        frame[field]='Site Plan' if field.endswith('SRC') else 5.0
    frame['MIN_HEIGHT']=0.0
    frame.loc[3,'AVG_HEIGHT']=8.0
    source=tmp_path/'source.shp';frame.to_file(source)
    parent=tmp_path/'parent';build_citywide(source,parent)
    boundary=tmp_path/'area.gpkg'
    gpd.GeoDataFrame(geometry=[box(630005,4834995,630035,4835015)],crs=26917).to_file(boundary)
    monkeypatch.setattr('scripts.build_toronto_demo.subprocess.run',lambda *a,**k:None)
    return parent,boundary,tmp_path/'demo'


def test_complete_intersection_conflict_exclusion_and_lineage(inputs):
    parent,boundary,out=inputs
    report=build_demo(parent,boundary,out)
    assert report['features']==1 and report['provenance_rows']==2
    assert report['boundary_crossings']==1
    assert report['parent_conflict_groups_excluded']==1
    assert report['local_conflict_variants_excluded']==2
    main=gpd.read_file(out/'toronto_demo.gpkg',layer='structures')
    original=read_selection(parent/'toronto_citywide_internal.gpkg','structures',gpd.read_file(boundary))
    pd.testing.assert_frame_equal(main,original)
    assert main.MIN_HEIGHT.isna().all() and main.MIN_HEIGHT_RAW.eq(0).all()
    assert main.AVG_HEIGHT.eq(5).all()
    with sqlite3.connect(out/'toronto_demo.gpkg') as db:
        assert db.execute('select count(*) from source_provenance').fetchone()[0]==2
    manifest=json.loads((out/'manifest.json').read_text())
    assert manifest['status']=='internal_only_not_for_customer_delivery'
    assert all(checksum(out/name)==value for name,value in manifest['files'].items())
    with pytest.raises(FileExistsError):build_demo(parent,boundary,out)
    again=out.with_name('again');build_demo(parent,boundary,again)
    pd.testing.assert_frame_equal(main,gpd.read_file(again/'toronto_demo.gpkg',layer='structures'))


def test_checksum_mismatch(inputs):
    parent,boundary,out=inputs
    manifest=parent/'manifest.json';data=json.loads(manifest.read_text())
    data['files']['toronto_citywide_internal.gpkg']='wrong';manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='checksum'):build_demo(parent,boundary,out)
    assert not out.exists()


@pytest.mark.parametrize('case',['empty','invalid','unknown_crs'])
def test_invalid_boundary_or_empty_selection(inputs,case):
    parent,boundary,out=inputs
    if case=='empty':
        geo=box(631000,4835000,631010,4835010)
    elif case=='invalid':
        geo=Polygon([(630000,4835000),(630010,4835010),(630000,4835010),(630010,4835000),(630000,4835000)])
    else:
        geo=box(630000,4835000,630010,4835010)
    boundary.unlink()
    gpd.GeoDataFrame(geometry=[geo],crs=None if case=='unknown_crs' else 26917).to_file(boundary)
    with pytest.raises(ValueError):build_demo(parent,boundary,out)
    assert not out.exists()


@pytest.mark.parametrize('case',['missing_lineage','wrong_rep','conflict_id','conflict_group','limit'])
def test_selection_contract(inputs,case):
    parent,boundary,_=inputs;path=parent/'toronto_citywide_internal.gpkg'
    frame=read_selection(path,'structures',gpd.read_file(boundary))
    with sqlite3.connect(path) as db:
        lineage=pd.read_sql_query("select * from source_provenance where OutputLayer='structures'",db)
        conflicts=pd.read_sql_query('select StructureID,duplicate_group from conflict_review',db)
    if case=='missing_lineage':lineage=lineage.iloc[:1]
    elif case=='wrong_rep':lineage.loc[0,'representative_fid']=999
    elif case=='conflict_id':conflicts.loc[0,'StructureID']=frame.iloc[0].StructureID
    elif case=='conflict_group':frame.loc[0,'duplicate_group']=conflicts.iloc[0].duplicate_group
    else:frame=pd.concat([frame]*501,ignore_index=True)
    with pytest.raises(ValueError):validate_selection(frame,lineage,conflicts)


def test_renderer_failure_does_not_publish(inputs,monkeypatch):
    parent,boundary,out=inputs
    def fail(*args,**kwargs):raise RuntimeError('renderer unavailable')
    monkeypatch.setattr('scripts.build_toronto_demo.subprocess.run',fail)
    with pytest.raises(RuntimeError):build_demo(parent,boundary,out)
    assert not out.exists() and not list(out.parent.glob('.demo-*'))
