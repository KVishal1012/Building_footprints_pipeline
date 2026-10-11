"""Create a portable, read-only QGIS demo project and offscreen review evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsFillSymbol,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsRectangle,
                       QgsReferencedRectangle, Qgis)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QImage, QPainter, QColor, QFont
from qgis_verify_toronto_citywide import render_map


def review(output: Path) -> dict:
    """Render an overview and distributed/detail samples without changing data bytes."""
    qa = json.loads((output/'quality_report.json').read_text(encoding='utf-8'))
    components = qa.get('delivery_mode') == 'components'
    stem = 'toronto_components' if components else 'toronto_demo'
    main_name = 'components' if components else 'structures'
    gpkg = output/f'{stem}.gpkg'
    before = hashlib.file_digest(gpkg.open('rb'), 'sha256').hexdigest()
    qa = json.loads((output/'quality_report.json').read_text(encoding='utf-8'))
    project = QgsProject()
    crs = QgsCoordinateReferenceSystem('EPSG:26917')
    project.setCrs(crs)
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    layers = {}
    for name in [main_name, 'study_area', 'source_provenance']:
        options = QgsVectorLayer.LayerOptions()
        options.forceReadOnly = True
        layer = QgsVectorLayer(str(gpkg)+'|layername='+name, name, 'ogr', options)
        assert layer.isValid(), name
        project.addMapLayer(layer)
        layers[name] = layer
    main, boundary = layers[main_name], layers['study_area']
    main.renderer().setSymbol(QgsFillSymbol.createSimple({'color':'190,205,219,255','outline_color':'45,70,95,255','outline_width':'0.2'}))
    boundary.renderer().setSymbol(QgsFillSymbol.createSimple({'style':'no','outline_color':'190,100,15,255','outline_width':'0.7','outline_style':'dash'}))
    features = sorted(main.getFeatures(), key=lambda f:str(f['StructureID']))
    assert len(features) == qa['features']
    assert all(f.geometry().isGeosValid() for f in features)
    transform = QgsCoordinateTransform(main.crs(), crs, project)
    extent = transform.transformBoundingBox(main.extent())
    extent.scale(1.12)
    project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, crs))
    project_path = output/f'{stem}.qgz'
    assert project.write(str(project_path))
    reopened = QgsProject()
    assert reopened.read(str(project_path))
    assert all(l.isValid() for l in reopened.mapLayers().values())
    # Greedy farthest-centroid sampling spreads 20 checks across this actual area.
    points = [transform.transform(f.geometry().centroid().asPoint()) for f in features]
    chosen = [min(range(len(features)), key=lambda i:(points[i].x(),points[i].y()))]
    while len(chosen) < min(20, len(features)):
        candidates = set(range(len(features)))-set(chosen)
        chosen.append(max(sorted(candidates), key=lambda i:min((points[i].x()-points[j].x())**2+(points[i].y()-points[j].y())**2 for j in chosen)))
    distributed = [str(features[i]['StructureID']) for i in chosen]
    required = set(qa['boundary_crossing_ids']+qa['included_repairs'])
    review_features = [features[i] for i in chosen]
    review_features += [f for f in features if str(f['StructureID']) in required-set(distributed)]
    overview = QImage(1400,1150,QImage.Format_ARGB32)
    overview.fill(QColor('white'))
    painter = QPainter(overview)
    painter.setPen(QColor('#183040')); painter.setFont(QFont('Arial',18))
    painter.drawText(25,35,'Toronto building components — CUSTOMER CANDIDATE' if components else 'Toronto footprint preparation — INTERNAL DEMONSTRATION')
    painter.setFont(QFont('Arial',11))
    painter.drawText(25,62,f"{len(features)} footprints/components | blue-grey: source geometry | orange dashed: study boundary | north up")
    painter.drawText(25,85,'City of Toronto 2025 massing release; observation date unknown | EPSG:26917 display')
    map_image = render_map([boundary, main],extent,QSize(1360,940),crs,project)
    painter.drawImage(20,100,map_image)
    # Renderer expands to image aspect ratio; use identical map aspect for a metric scale.
    actual_width = max(extent.width(), extent.height()*1360/940)
    pixels = 50/actual_width*1360
    painter.drawLine(30,1070,int(30+pixels),1070)
    painter.drawText(30,1095,'50 m')
    painter.drawText(260,1075,'Complete intersecting footprints; all conflicting variants excluded.')
    painter.drawText(260,1097,'No height interpretation or surveyed accuracy asserted. Not for customer delivery.')
    painter.drawText(25,1130,'Contains information licensed under the Open Government Licence – Toronto.' if components else 'Contains information licensed under the Open Government Licence – Toronto; applicability review pending.')
    painter.end(); assert overview.save(str(output/'preview.png'))
    for offset in range(0,len(review_features),20):
        batch = review_features[offset:offset+20]
        sheet = QImage(1600,100+340*((len(batch)+3)//4),QImage.Format_ARGB32)
        sheet.fill(QColor('white')); painter = QPainter(sheet)
        painter.setFont(QFont('Arial',13)); painter.drawText(15,25,'INTERNAL QA — selected footprint isolated, study boundary dashed orange')
        painter.setFont(QFont('Arial',10)); painter.drawText(15,48,'EPSG:26917 | north up | independent zoom per panel | FIDs are snapshot records, not building identities')
        for index,f in enumerate(batch):
            x,y=(index%4)*400,80+(index//4)*340
            fid=int(f['representative_fid'])
            assert main.setSubsetString(f'"representative_fid" = {fid}')
            box=transform.transformBoundingBox(f.geometry().boundingBox());box.scale(1.6)
            panel=render_map([boundary,main],box,QSize(390,260),crs,project)
            painter.drawText(x+8,y+18,f'FID {fid} | area {float(f["FootprintArea_m2"]):.1f} m²')
            painter.drawText(x+8,y+38,str(f['GeometryStatus']) if components else f'MIN raw: {f["MIN_HEIGHT_RAW"]} | {f["GeometryStatus"]}')
            painter.drawImage(x+5,y+55,panel)
        main.setSubsetString('');painter.end()
        assert sheet.save(str(output/f'qa_details_{offset//20+1}.png'))
    assert hashlib.file_digest(gpkg.open('rb'),'sha256').hexdigest()==before
    result={'qgis_version':Qgis.QGIS_VERSION,'method':'native QGIS offscreen renderer; no desktop interaction',
            'project_reopened':True,'read_only':True,'geopackage_unchanged':True,
            'distributed_sample_ids':distributed,'boundary_crossings_rendered':qa['boundary_crossing_ids'],
            'repairs_rendered':qa['included_repairs'],'detail_panels':len(review_features),
            'all_selected_geometries_valid':True,'visual_inspection':'pending; record supplemental findings after inspection'}
    (output/'qgis_review.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    app=QgsApplication([],False);app.initQgis()
    print(json.dumps(review(args.output_dir.resolve()),indent=2))
