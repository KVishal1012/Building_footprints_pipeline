"""Verify and render an existing citywide package using QGIS's native Python.

Run with the Python interpreter shipped with QGIS and QT_QPA_PLATFORM=offscreen.
Creates a standalone review project and diagnostic render sheets, without
modifying an open desktop project or the checksummed GeoPackage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from qgis.core import (QgsApplication, Qgis, QgsVectorLayer, QgsProject, QgsFillSymbol,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsRectangle,
                       QgsReferencedRectangle, QgsMapSettings, QgsMapRendererParallelJob)
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont


def render_map(layers: list, extent: QgsRectangle, size: QSize, crs, project) -> QImage:
    """Render layers with native QGIS, preserving consistent metric display CRS."""
    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(crs)
    settings.setTransformContext(project.transformContext())
    settings.setExtent(extent)
    settings.setOutputSize(size)
    settings.setBackgroundColor(QColor('white'))
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    if job.errors():
        raise RuntimeError(str(job.errors()))
    return job.renderedImage()


def write_sheet(path: Path, features: list, layers: list, project, title: str,
                variant_info: dict | None = None) -> None:
    """Create labelled diagnostic panels; no external basemap or height inference."""
    columns, width, height, header = 4, 420, 350, 85
    count = len(features)
    image = QImage(columns*width, header + ((count+columns-1)//columns)*height, QImage.Format_ARGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setFont(QFont('Arial', 15))
    painter.drawText(15, 25, title)
    painter.setFont(QFont('Arial', 10))
    painter.drawText(15, 45, 'Toronto 2025 massing | EPSG:26917 display | INTERNAL QA | north up | each panel independently zoomed')
    painter.drawText(15, 65, 'Blue: repaired; orange dashed: original. Purple: coincident unresolved variants. Heights: raw source units unverified.')
    crs = QgsCoordinateReferenceSystem('EPSG:26917')
    transform = QgsCoordinateTransform(layers[0].crs(), crs, project)
    try:
        for index, feature in enumerate(features):
            extent = transform.transformBoundingBox(feature.geometry().boundingBox())
            extent.scale(1.6)
            x, y = (index % columns)*width, header + (index//columns)*height
            predicate = ('"duplicate_group" = \'' + str(feature["duplicate_group"]) + "'"
                         if variant_info else f'"representative_fid" = {int(feature["representative_fid"])}')
            for layer in layers:
                assert layer.setSubsetString(predicate)
            panel = render_map(layers, extent, QSize(width-10, height-85), crs, project)
            for layer in layers:
                layer.setSubsetString("")
            painter.drawImage(x+5, y+65, panel)
            fid = int(feature['representative_fid'])
            painter.setPen(QColor('black'))
            painter.drawText(x+8, y+17, f'Source FID {fid} | extent width {extent.width():.1f} m')
            if variant_info:
                variants = variant_info[feature['duplicate_group']]
                painter.drawText(x+8, y+34, 'FIDs: '+', '.join(str(int(f['representative_fid'])) for f in variants))
                painter.drawText(x+8, y+51, 'AVG_HEIGHT: '+', '.join(str(f['AVG_HEIGHT']) for f in variants))
            else:
                painter.drawText(x+8, y+34, 'make_valid: native QGIS geometry check passed')
    finally:
        painter.end()
    if not image.save(str(path)):
        raise RuntimeError(f'Could not save {path}')


def verify_in_qgis(output: Path) -> dict:
    """Load all layers, verify small review layers, save project and diagnostic sheets."""
    gpkg = output/'toronto_citywide_internal.gpkg'
    original_hash = hashlib.file_digest(gpkg.open('rb'), 'sha256').hexdigest()
    report = json.loads((output/'quality_report.json').read_text(encoding='utf-8'))
    project = QgsProject()
    project.setCrs(QgsCoordinateReferenceSystem('EPSG:26917'))
    expected = {**report['partition_counts'], 'geometry_before': report['geometry_cases'],
                'geometry_after': report['repaired'], 'source_provenance': report['provenance_rows']}
    loaded = {}
    for name, count in expected.items():
        options = QgsVectorLayer.LayerOptions()
        options.forceReadOnly = True
        layer = QgsVectorLayer(str(gpkg)+'|layername='+name, name, 'ogr', options)
        assert layer.isValid(), name
        assert layer.featureCount() == count, (name, layer.featureCount())
        if name != 'source_provenance':
            assert layer.crs().authid() == 'EPSG:4326', (name, layer.crs().authid())
            style = {'color':'180,185,195,110', 'outline_color':'90,95,100,180', 'outline_width':'0.12'}
            if name == 'conflict_review':
                style = {'color':'170,90,185,110', 'outline_color':'110,40,140,255', 'outline_width':'0.5'}
            elif name == 'geometry_before':
                style = {'style':'no', 'outline_color':'230,145,35,255', 'outline_width':'1', 'outline_style':'dash'}
            elif name == 'geometry_after':
                style = {'color':'40,130,210,65', 'outline_color':'20,100,190,255', 'outline_width':'0.45'}
            if layer.renderer():
                layer.renderer().setSymbol(QgsFillSymbol.createSimple(style))
        project.addMapLayer(layer)
        project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(name in {'structures','conflict_review','geometry_before','geometry_after'})
        loaded[name] = layer
    repaired = sorted(loaded['geometry_after'].getFeatures(), key=lambda f:int(f['representative_fid']))
    originals = list(loaded['geometry_before'].getFeatures())
    conflicts = sorted(loaded['conflict_review'].getFeatures(), key=lambda f:int(f['representative_fid']))
    assert all(f.geometry().isGeosValid() for f in repaired)
    assert all(f.geometry().isGeosValid() for f in conflicts)
    variants = {}
    for feature in conflicts:
        variants.setdefault(feature['duplicate_group'], []).append(feature)
    assert len(variants) == report['conflict_groups']
    write_sheet(output/'qgis_repairs.png', repaired, [loaded['geometry_after'], loaded['geometry_before']], project,
                'All repaired geometries: before / after')
    group_features = [fs[0] for fs in variants.values()]
    write_sheet(output/'qgis_conflicts.png', group_features, [loaded['conflict_review']], project,
                'All unresolved footprint groups: variants preserved', variants)
    extent = QgsCoordinateTransform(loaded['structures'].crs(), project.crs(), project).transformBoundingBox(loaded['structures'].extent())
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, project.crs()))
    project_path = output/'toronto_citywide_review.qgz'
    assert project.write(str(project_path))
    reopened = QgsProject()
    assert reopened.read(str(project_path))
    assert len(reopened.mapLayers()) == len(loaded)
    assert all(l.isValid() and l.featureCount() == expected[l.name()] for l in reopened.mapLayers().values())
    evidence = {'recorded_at':datetime.now(timezone.utc).isoformat(), 'qgis_version': Qgis.QGIS_VERSION,
        'method':'QGIS native provider, geometry engine and renderer via installed QGIS Python (offscreen)',
        'layer_counts':{name: layer.featureCount() for name,layer in loaded.items()},
        'repaired_valid':len(repaired), 'before_invalid':sum(not f.geometry().isGeosValid() for f in originals),
        'conflict_variants_valid':len(conflicts), 'conflict_groups':len(variants),
        'rendered_repair_panels':len(repaired), 'rendered_conflict_panels':len(group_features),
        'standalone_project_reopened':True, 'visual_inspection':'pending',
        'desktop_ui':'Connection timed out; existing desktop project left intact.',
        'commercial_status':'internal_only_not_for_customer_delivery'}
    assert hashlib.file_digest(gpkg.open('rb'), 'sha256').hexdigest() == original_hash, 'QGIS altered the GeoPackage'
    evidence['geopackage_sha256'] = original_hash
    evidence['read_only_provider'] = True
    (output/'qgis_verification.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    application = QgsApplication([],False)
    application.initQgis()
    print(json.dumps(verify_in_qgis(args.output_dir.resolve()),indent=2))
