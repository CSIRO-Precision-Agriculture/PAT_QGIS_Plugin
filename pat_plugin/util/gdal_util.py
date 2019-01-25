# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools QGIS Plugin

 gdal_util

                              -------------------
        begin                : 2017-05-25
        git sha              : $Format:%H$
        copyright            : (C) 2017 by CSIRO
        email                : CSIRO
 ***************************************************************************/

 Source: Spreadsheet Layers QGIS Plugin on 21/08/2017
     https://github.com/camptocamp/QGIS-SpreadSheetLayers/blob/master/util/gdal_util.py

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os
import tempfile

from osgeo import ogr


def testGdal():
    # Inspired from gdal test ogr_vrt_34
    # https://github.com/OSGeo/gdal/commit/82074ed5bd67d2efbfbcea50c5416856d9c5826d
    path = os.path.join(tempfile.gettempdir(), 'gdal_test.csv')
    f = open(path, 'wb')
    f.write('x,y\n'.encode('ascii'))
    f.write('2,49\n'.encode('ascii'))
    f.close()

    vrt_xml = """
<OGRVRTDataSource>
    <OGRVRTLayer name="gdal_test">
        <SrcDataSource relativeToVRT="0">"""+path+"""</SrcDataSource>
        <SrcSql dialect="sqlite">SELECT * FROM gdal_test</SrcSql>
        <GeometryField encoding="PointFromColumns" x="x" y="y"/>
        <Field name="x" type="Real"/>
        <Field name="y" type="Real"/>
    </OGRVRTLayer>
</OGRVRTDataSource>"""

    ds = ogr.Open( vrt_xml )

    lyr = ds.GetLayer(0)
    lyr.SetIgnoredFields(['x', 'y'])
    f = lyr.GetNextFeature()
    result = True
    if f is None:
        result = False
    elif f.GetGeometryRef().ExportToWkt() != 'POINT (2 49)':
        result = False

    f = None
    lyr = None
    ds = None
    os.unlink(path)

    return result

GDAL_COMPAT = testGdal()
