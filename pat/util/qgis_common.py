# coding=utf-8
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 qgis_common -  Makes common qgis functions available to all forms, modules and algorithms
           -------------------
        begin      : 2017-05-25
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au PAT@csiro.au
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the associated CSIRO Open Source Software       *
 *   License Agreement (GPLv3) provided with this plugin.                  *
 *                                                                         *
 ***************************************************************************/
"""
import six
from future import standard_library
standard_library.install_aliases()
import logging
import os
import re
from urllib.parse import urlparse

import pandas as pd
import geopandas as gpd
from shapely import wkt
import rasterio
import numpy as np

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QFileDialog, QDockWidget, QMessageBox

from qgis.utils import iface
from qgis.core import (QgsProject, QgsProviderRegistry, QgsMapLayer, QgsVectorLayer, QgsRasterLayer,
                       QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsUnitTypes,
                       QgsFeature, QgsField)

from pat import LOGGER_NAME

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

from pyprecag import crs

dataTypes = {0:'Unk',1:'Byte',2:'UInt16',3:'Int16',4:'UInt32',5:'Int32',
            6:'Float32', 7:'Float64' , 8:'CInt16', 9:'CInt32' , 10:'CFloat32',
            11:'CFloat64'}

layerTypes= {0:'VectorLayer',  1:'RasterLayer',2:'PluginLayer',3:'MeshLayer',4:"VectorTileLayer"}     


def get_UTM_Coordinate_System(x, y, epsg):
    """ Determine a utm coordinate system either from coordinates"""
    if epsg == '':
        return QgsCoordinateReferenceSystem()
    
    if isinstance(epsg, six.string_types):
        epsg = int(epsg.upper().replace('EPSG:', ''))

    utm_crs = crs.getProjectedCRSForXY(x, y, epsg)

    if utm_crs is not None:
        out_crs = QgsCoordinateReferenceSystem().fromEpsgId(utm_crs.epsg_number)

    if out_crs is not None:
        return out_crs
    else:
        # self.send_to_messagebar(
        #     'Auto detect coordinate system Failed. Check coordinate system of input raster layer',
        #     level=Qgis.Critical, duration=5)
        return


def check_for_overlap(rect1, rect2, crs1='', crs2=''):
    """ Check for overlap between two rectangles.
        Input rect format is a shapely polygon object
          'POLYGON((288050 6212792, 288875 6212792, 288875 6212902, 288050, 288050))'"""
    import shapely.wkt
    if isinstance(rect1,str):
        rect1 = wkt.loads(rect1)
    
    if isinstance(rect2,str):
        rect2 = wkt.loads(rect2)
    
    if crs1 != '':
        gdf1 = gpd.GeoDataFrame({'geometry': [rect1]}, crs=crs1)
    else:
        gdf1 = gpd.GeoDataFrame({'geometry': [rect1]})

    if crs2 != '':
        gdf2 = gpd.GeoDataFrame({'geometry': [rect2]}, crs=crs2)
    else:
        gdf2 = gpd.GeoDataFrame({'geometry': [rect2]})

    return gdf1.intersects(gdf2)[0]


def get_pixel_size(layer):
    """Get the pixel size and pixel size and units from raster layer.
    """

    if layer is None or layer.type() != QgsMapLayer.RasterLayer:
        return None, None, None

    if layer.crs().isGeographic():
        ft = 'f'  # this will convert 1.99348e-05 to 0.000020
    else:
        ft = 'g'  # this will convert 2.0 to 2 or 0.5, '0.5'

    pixel_units = QgsUnitTypes.toAbbreviatedString(layer.crs().mapUnits())
    
    # Adjust for Aust/UK spelling
    #pixel_units = pixel_units.replace('meters', 'metres')
    pixel_size = format(layer.rasterUnitsPerPixelX(), ft)

    #Convert to float or int
    #pixel_size = int(float(pixel_size)) if int(float(pixel_size)) == float(pixel_size) else float(pixel_size)

    return pixel_size, pixel_units, ft


def build_layer_table(layer_list=None,only_raster_boundingbox=True):
    """Build a table of layer properties.
    Can be used in conjunction with selecting layers to exclude from mapcomboboxes

    Layer_list: default  None
                if None then it will build the table from all layers in the QGIS project
                otherwise it will use the list.
    
    only_raster_boundingbox: default False 
                    create a bounding box from the raster data 
                   ie removing nodata from polygon. 
                   This will slow it down if large numbers of rasters are present.
    """

    dest_crs = QgsProject.instance().crs()

    gdf_layers = gpd.GeoDataFrame(columns=['layer', 'layer_name', 'layer_id', 'layer_type', 'source','format',
                                           'epsg', 'crs_name', 'is_projected', 'extent', 'provider','geometry'],
                                           geometry='geometry', crs=dest_crs.authid())  # pd.DataFrame()


    if layer_list is None or len(layer_list) == 0:
        layermap = QgsProject.instance().mapLayers().values()

    else:
        layermap = layer_list

    new_rows = []

    for layer in layermap:
        if layer.type() not in [QgsMapLayer.VectorLayer, QgsMapLayer.RasterLayer]:
            continue

        if layer.providerType() not in ['ogr','gdal','delimitedtext']:
            continue
        
        if layer.type() == QgsMapLayer.VectorLayer:
            format = layer.dataProvider().storageType()
        else:
            format=None
            
        if layer.crs().isValid() and layer.crs().authid() == '':
            # Try and convert older style coordinates systems
            # were correctly definied in QGIS 2 as GDA94 / MGA zone 54 
            # but get interpreted in QGIS 3 as  Unknown CRS: BOUNDCRS[SOURCECRS[PROJCRS["GDA94 / MGA zone 54",.....
            
            layer_crs = QgsCoordinateReferenceSystem()
            if not layer_crs.createFromProj(layer.crs().toWkt()):
                #print('Could not match a coordinate system for {}'.format(layer.id()))
                layer_crs = layer.crs()
                
                # could apply to the layer, but what if it's wrong....
                #layer.setCrs(layer_crs)
            
        else: 
            layer_crs = layer.crs()
        
        # project the bounding box extents to be the same as the qgis project.
        if layer_crs.authid() != dest_crs.authid():
            transform = QgsCoordinateTransform(layer_crs, dest_crs, QgsProject.instance())
            prj_ext  = transform.transformBoundingBox(layer.extent())
        else:
            prj_ext  = layer.extent()

        row_dict = {'layer': layer,
                    'layer_name': layer.name(),
                    'layer_id': layer.id(),
                    'layer_type': layerTypes[ layer.type()],
                    'format': format,
                    'source': get_layer_source(layer),
                    'epsg': layer_crs.authid(),
                    'crs_name': layer_crs.description(),
                    'is_projected': not layer_crs.isGeographic(),
                    'provider': layer.providerType(),
                    'geometry': wkt.loads(prj_ext.asWktPolygon())}

            # 'extent': prj_ext.asWktPolygon(),

        if layer.type() == QgsMapLayer.RasterLayer:
            pixel_size = get_pixel_size(layer)
            if not only_raster_boundingbox:
                with rasterio.open(get_layer_source(layer)) as src:
                    msk = src.dataset_mask()  # 0 = nodata 255=valid
                    rast_shapes = rasterio.features.shapes(np.ma.masked_equal(np.where(msk > 0, 1, 0), 0),
                                                           transform=src.transform)
                try:
                    results = ({'properties': {'raster_val': v}, 'geometry': s} for i, (s, v) in enumerate(rast_shapes))
    
                    geoms = list(results)
                    gpd_rPoly = gpd.GeoDataFrame.from_features(geoms, crs=layer.crs().authid())
                    dest_crs.authid().replace('epgs:', '')
                    gpd_rPoly.to_crs(dest_crs.authid().replace('epgs:', ''), inplace=True)
                    row_dict.update({'geometry': gpd_rPoly.unary_union})
    
                    del gpd_rPoly, results, msk,rast_shapes
                except:
                    pass

            row_dict.update({'bandcount': layer.bandCount(),
                        'datatype':dataTypes[layer.dataProvider().dataType(1)],
                        'pixel_size': pixel_size[0],
                        'pixel_text': '{} {}'.format(*pixel_size),
                        })

        new_rows.append(row_dict)

#    gdf_layers = gpd.GeoDataFrame(new_rows, geometry='extent')

    if len(new_rows) == 0:
        return gdf_layers

    # for pandas 0.23.4 add sort=False to prevent row and column orders to change.
    try:
        gdf_layers = gdf_layers.append(new_rows, ignore_index=True, sort=False)
    except:
        gdf_layers = gdf_layers.append(new_rows, ignore_index=True)

    #df_layers.set_geometry('geometry')
    return gdf_layers


def get_layer_source(layer):
    """
    layer.source() sometimes returns  'C:/data/Temp/My_points_wgs84.shp|layername=My_points_wgs84' 
    so this will break this down and return only the path.
    """
    
    result = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.dataProvider().dataSourceUri())

    if not 'path' in result.keys():
        return ''

    if len(result) == 0 or result['path'] == '':
        return layer.source()
    else:
        return result['path'] 


def save_as_dialog(dialog, caption, file_filter, default_name=''):
    s, f = QFileDialog.getSaveFileName(
        dialog,
        caption,
        default_name,
        file_filter)

    if s == '' or s is None:
        return

    s = os.path.normpath(s)

    # Replace extension if it is not the same as the dialog. ie copied from another file
    filter_ext = f.split('(')[-1].split(')')[0].replace('*', '')
    s_ext = os.path.splitext(s)[-1]
    if s_ext == '':
        s = s + filter_ext
    elif s_ext != filter_ext:
        s = s.replace(os.path.splitext(s)[-1], filter_ext)

    return s


def file_in_use(filename, display_msgbox=True):
    """ Check to see if a file is in use within QGIS.

    Trying to open the file for writing then checking each layers source for the filename.

    Args:
        filename ():
        display_msgbox ():
    """
    if not os.path.exists(filename):
        return False

    try:
        # Try and open the file. If in use creates IOError: [Errno 13] Permission denied error
        with open(filename, "a") as f:
            pass
        
    except IOError:
        reply = QMessageBox.question(None, 'File in Use',
                                     '{} is currently in use.\nPlease close the file or use a'
                                     ' different name'.format(os.path.basename(filename)),
                                     QMessageBox.Ok)
        return True

    # also check to see if it's loaded into QGIS
    found_lyrs = []
    layermap = QgsProject.instance().mapLayers()
    for name, layer in layermap.items():
        if layer.providerType() == 'delimitedtext':

            url = urlparse(layer.source())

            if os.path.normpath(url.path.strip('/')).upper() == filename.upper():
                found_lyrs += [layer.name()]
        else:
            if os.path.normpath(get_layer_source(layer)) == os.path.normpath(filename):
                found_lyrs += [layer.name()]

    if display_msgbox and len(found_lyrs) > 0:
        message = 'File <b><i>{}</i></b><br /> is currently in use in QGIS layer(s)<dd>' \
                  '<b>{}</b></dd><br/>Please remove the file from QGIS or use a ' \
                  'different name'.format(os.path.basename(filename), '<dd><b>'.join(found_lyrs))

        reply = QMessageBox.question(None, 'File in Use', message, QMessageBox.Ok)

    return len(found_lyrs) > 0


def addVectorFileToQGIS(filename, layer_name='', group_layer_name='', atTop=True, visible=True):
    """ Load a file as a vector layer into qgis

    Args:
        filename (str): the file to load
        layer_name (str): The name to apply to the vector layer
        group_layer_name (str):  Add the layer to a group. Use path separators to create
              multiple groups
        atTop (bool): Load to top of the table of contents. if false it will load above
              the active layer.
    Return:
         Vector Layer: The layer which has been loaded into QGIS
    """

    removeFileFromQGIS(filename)
    if layer_name == '':
        layer_name = os.path.splitext(os.path.basename(filename))[0]

    vector_layer = QgsVectorLayer(filename, layer_name, "ogr")

    addLayerToQGIS(vector_layer, group_layer_name=group_layer_name, atTop=atTop)
    QgsProject.instance().layerTreeRoot().findLayer(vector_layer.id()).setItemVisibilityChecked(visible)
    return vector_layer


def addRasterFileToQGIS(filename, layer_name='', group_layer_name='', atTop=True, visible=True):
    """ Load a file as a vector layer into qgis

    Args:
        filename (str): the file to load
        layer_name (str): The name to apply to the raster layer
        group_layer_name (str):  Add the layer to a group. Use path separators to create
                multiple groups
        atTop (bool): Load to top of the table of contents. if false it will load above the
                active layer.

    Returns:
        Raster Layer: The layer which has been loaded into QGIS
    """

    removeFileFromQGIS(filename)
    if layer_name == '':
        layer_name = os.path.splitext(os.path.basename(filename))[0]

    raster_layer = QgsRasterLayer(filename, layer_name)

    addLayerToQGIS(raster_layer, group_layer_name=group_layer_name, atTop=atTop)
    QgsProject.instance().layerTreeRoot().findLayer(raster_layer.id()).setItemVisibilityChecked(visible)
    return raster_layer


def addLayerToQGIS(layer, group_layer_name="", atTop=True):
    """Add a layer to QGIS.

    source: https://gis.stackexchange.com/a/126983
            http://www.lutraconsulting.co.uk/blog/2014/07/06/qgis-layer-tree-api-part-1/
            http://www.lutraconsulting.co.uk/blog/2014/07/25/qgis-layer-tree-api-part-2/

    Args:
        layer (QGSLayer): The layer to add
        group_layer_name (str): Add to a group layer. path separators can be used for nested
                     group layers
        atTop (str):

    """

    QgsProject.instance().addMapLayer(layer, addToLegend=False)
    root = QgsProject.instance().layerTreeRoot()

    # create group layers first:

    if group_layer_name != "":

        if os.path.sep in group_layer_name:
            grplist = group_layer_name.split(os.path.sep)
        else:
            grplist = [group_layer_name]
        current_grp = root
        for ea_grp in grplist:
            group_layer = current_grp.findGroup(ea_grp)
            if group_layer is None:
                if atTop:
                    group_layer = current_grp.insertGroup(0, ea_grp)
                else:
                    group_layer = current_grp.addGroup(ea_grp)
            current_grp = group_layer

        node_layer = current_grp.addLayer(layer)

    else:
        if atTop:
            root.insertLayer(0, layer)
        else:
            root.addLayer(layer)


def removeFileFromQGIS(filename):
    """ Check to see if a layer in QGIS exists for a set filename and remove it
    This is required to remove a file lock prior to editing/deleting.

    Args:
        filename (str): The filename for data to remove from qgis.
    """

    remove_layers = []

    # Loop through layers in reverse so the count/indexing of layers persists if one is removed.
    layermap = QgsProject.instance().mapLayers()
    for name, layer in layermap.items():
        if get_layer_source(layer) == filename:
            remove_layers.append(layer.id())

    if len(remove_layers) > 0:
        QgsProject.instance().removeMapLayers(remove_layers)


def getGeometryTypeAsString(intGeomType):
    """ Get a string representing the integer geometry type which can be used in creating URI
    strings or memory layers.

        QGis.WkbType is a sip wrapped enum class which doesn't have a reverse mapping function
        like it would if it were a native python enum.

    Args:
        intGeomType (int):integer representing the geometry type (layer.dataprovider.geometryType(),
                    or layer.wkbType())

    Returns: string representing Geometry type

    """
    geom_type_str = {0: 'Unknown', 1: 'Point', 2: 'LineString', 3: 'Polygon', 4: 'MultiPoint',
                   5: 'MultiLineString', 6: 'MultiPolygon', 7: 'GeometryCollection',
                   8: 'CircularString', 9: 'CompoundCurve', 10: 'CurvePolygon', 11: 'MultiCurve',
                   12: 'MultiSurface', 100: 'NoGeometry', 1001: 'PointZ', 1002: 'LineStringZ',
                   1003: 'PolygonZ', 1004: 'MultiPointZ', 1005: 'MultiLineStringZ',
                   1006: 'MultiPolygonZ', 1007: 'GeometryCollectionZ', 1008: 'CircularStringZ',
                   1009: 'CompoundCurveZ', 1010: 'CurvePolygonZ', 1011: 'MultiCurveZ',
                   1012: 'MultiSurfaceZ', 2001: 'PointM', 2002: 'LineStringM', 2003: 'PolygonM',
                   2004: 'MultiPointM', 2005: 'MultiLineStringM', 2006: 'MultiPolygonM',
                   2007: 'GeometryCollectionM', 2008: 'CircularStringM', 2009: 'CompoundCurveM',
                   2010: 'CurvePolygonM', 2011: 'MultiCurveM', 2012: 'MultiSurfaceM',
                   3001: 'PointZM', 3002: 'LineStringZM', 3003: 'PolygonZM', 3004: 'MultiPointZM',
                   3005: 'MultiLineStringZM', 3006: 'MultiPolygonZM', 3007: 'GeometryCollectionZM',
                   3008: 'CircularStringZM', 3009: 'CompoundCurveZM', 3010: 'CurvePolygonZM',
                   3011: 'MultiCurveZM', 3012: 'MultiSurfaceZM'}
    # , 0x80000001: 'Point25D', : 'LineString25D', : 'Polygon25D', : 'MultiPoint25D',
    # : 'MultiLineString25D', : 'MultiPolygon25D'}
    return geom_type_str[intGeomType]


def copyLayerToMemory(layer, layer_name, bOnlySelectedFeat=False, bAddUFI=True):
    """ Make a copy of an existing layer as a Memory layer

    Args:
        layer (): The layer to copy to memory
        layer_name (): The name for the memory layer
        bOnlySelectedFeat (): Only copy selected features
        bAddUFI (): Add a unique identifier to the memory layer

    Returns:
        Qgis Memory layer

    """

    # Create an in memory layer and add UFI
    mem_layer = QgsVectorLayer("{}?crs={}&index=yes".format(getGeometryTypeAsString(layer.wkbType()),
                                                           layer.crs().authid()), layer_name,
                              "memory")
    if not mem_layer.isValid():
        raise Exception('Could not create memory Layer called {}'
                        ' from layer {}'.format(layer_name, layer.name()))

    mem_data_prov = mem_layer.dataProvider()

    # Add the fields
    b_calc_ufi = False
    attr = []

    if layer.fields().lookupField("FID") == -1 and bAddUFI:
        b_calc_ufi = True
        attr = [QgsField('FID', QVariant.Int)]

    invalid_fields = []
    for eaFld in layer.dataProvider().fields():
        old_name = eaFld.name()
        new_name = re.sub('[^A-Za-z0-9_-]+', '', old_name)[:10]

        if old_name != new_name:
            invalid_fields.append('   ' + old_name + '   to   ' + new_name)
            eaFld.setName(new_name)  # update the name
        attr.append(eaFld)

    if len(invalid_fields) > 0:
        LOGGER.warning('{} fieldnames are not ESRI Compatible. Renaming...'.format(len(invalid_fields)))

        for i, ea in enumerate(invalid_fields):
            LOGGER.warning(ea)

    # Copy all existing fields
    mem_data_prov.addAttributes(attr)

    # tell the vector layer to fetch changes from the provider
    mem_layer.updateFields()

    # start editing and copy all features and attributes
    mem_layer.startEditing()
    sel_feat_ids = []
    if bOnlySelectedFeat and layer.selectedFeatureCount() > 0:
        # Get a list of selected features.....
        sel_feat_ids = [f.id() for f in layer.selectedFeatures()]

    features = layer.getFeatures()
    feat = QgsFeature()

    id = 0
    for f in features:
        # Check the list of features against the selected list.
        # This will maintain the order of features when saved to shapefile.
        if bOnlySelectedFeat and len(sel_feat_ids) > 0:
            # Skip features which aren't in the selection
            if not f.id() in sel_feat_ids:
                continue

        feat.setGeometry(f.geometry())
        f_attr = []

        if b_calc_ufi:
            f_attr += [id]

        # The order of fields hasn't changed so just add attributes.
        f_attr += f.attributes()
        feat.setAttributes(f_attr)
        mem_layer.addFeatures([feat])
        id += 1

    mem_layer.updateExtents()
    mem_layer.commitChanges()

    return mem_layer


def open_close_python_console():
    """ Open and close the python console
    This is a workaround for getting gui message bar to appear
    """
    try:
        b_python_console_open = False
        python_console_panel = iface.mainWindow().findChild(QDockWidget, 'PythonConsole')
        b_python_console_open = python_console_panel.isVisible()
        if not python_console_panel.isVisible():
            iface.actionShowPythonDialog().trigger()
    except:
        # the above will bail if sitting on RecentProjects empty view.
        iface.actionShowPythonDialog().trigger()

    if not b_python_console_open:
        iface.actionShowPythonDialog().trigger()
