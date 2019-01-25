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

import logging
import os
import random

import numpy as np
import rasterio
import re
from urlparse import urlparse

from PyQt4.QtCore import QVariant
from PyQt4.QtGui import QFileDialog, QDockWidget, QMessageBox, QColor

from qgis.utils import iface
from qgis.core import (QgsVectorLayer, QgsMapLayerRegistry, QgsRasterLayer,
                       QgsFeature, QgsField, QgsProject, QgsSimpleFillSymbolLayerV2, QgsSymbolV2,
                       QgsRendererCategoryV2, QgsCategorizedSymbolRendererV2,
                       QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer)

from pat_plugin import LOGGER_NAME

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


def saveAsDialog(dialog, caption, file_filter, defaultName=''):
    
    s,f = QFileDialog.getSaveFileNameAndFilter(
            dialog,
            caption,
            defaultName, 
            file_filter)
    
    if s == '' or s is None :
        return

    s = os.path.normpath(s)

    #Replace extension if it is not the same as the dialog. ie copied from another file
    filterExt = f.split('(')[-1].split(')')[0].replace('*','')
    sExt = os.path.splitext(s)[-1]
    if sExt == '':
        s = s + filterExt
    elif sExt != filterExt:
        s = s.replace(os.path.splitext(s)[-1],filterExt)
    
    return s


def file_in_use(filename, displayMsgBox=True):
    """ Check to see if a file is in use within QGIS.

    This is done by trying to open the file for writing then checking each layers source for the filename.

    Args:
        filename ():
        displayMsgBox ():
    """
    if not os.path.exists(filename): 
        return False
    
    try:
        # Try and open the file. If it is open it will throw a IOError: [Errno 13] Permission denied error
        open(filename, "a")
    except IOError:
        reply = QMessageBox.question(None, 'File in Use',
                                     '{} is currently in use.\nPlease close the file or use a different name'.format(
                                         os.path.basename(filename)), QMessageBox.Ok)
        return True

    # also check to see if it's loaded into QGIS
    foundLyrs = []
    layermap = QgsMapLayerRegistry.instance().mapLayers()
    for name, layer in layermap.iteritems():
        if layer.providerType() == 'delimitedtext':

            url = urlparse(layer.source())

            if os.path.normpath(url.path.strip('/')).upper() == filename.upper():
                foundLyrs += [layer.name()]
        else:
            if os.path.normpath(layer.source()) == os.path.normpath(filename):
                foundLyrs += [layer.name()]

    if displayMsgBox and len(foundLyrs) > 0:
        reply = QMessageBox.question(None, 'File in Use',
                                     'File <b><i>{}</i></b><br /> is currently in use in QGIS layer(s)<dd><b>{}</b></dd><br/>Please remove the file from QGIS or use a different name'.format(
                                         os.path.basename(filename), '<dd><b>'.join(foundLyrs)))

    return len(foundLyrs) > 0


def random_colour(mix=(255, 255, 255)):
    """ Create a random color """
    red = random.randrange(0, 256)
    green = random.randrange(0, 256)
    blue = random.randrange(0, 256)
    r, g, b = mix
    red = (red + r) / 2
    green = (green + g) / 2
    blue = (blue + b) / 2
    return red, green, blue


def raster_applyUniqueValueRenderer(raster_layer,band_num=1,n_decimals=0):
    """
    Apply a random colour to each each unique value for a raster band.

    In some case the unique values are floating, n_decimals allows these to be rounded for display

    Args:
        raster_layer (QgsRasterLayer): input raster layer
        band_num (int):    the band number used to determine unique values
        n_decimals (int):  number of decimals to round values to
    """

    # get unique values
    band = rasterio.open(raster_layer.source()).read(band_num, masked=True)
    uniq_vals = np.unique(band[band.mask == False])

    if n_decimals > 0:
        uniq_vals = np.around(list(uniq_vals), decimals=3)

    # instantiate the specialized ramp shader object
    colRmpShd = QgsColorRampShader()

    # name a type for the ramp shader. In this case, we use an INTERPOLATED shader:
    colRmpShd.setColorRampType(QgsColorRampShader.EXACT)
    qri = QgsColorRampShader.ColorRampItem

    sym_classes = []
    for class_val in uniq_vals:
        # apply unique values renderer.
        r, g, b = random_colour()
        sym_classes.append(qri(class_val, QColor(r, g, b, 255), str(class_val)))

    # assign the color ramp to our shader:
    colRmpShd.setColorRampItemList(sym_classes)

    # create a generic raster shader object:
    rastShd = QgsRasterShader()
    # tell the generic raster shader to use the color ramp:
    rastShd.setRasterShaderFunction(colRmpShd)

    # create a raster renderer object with the shader, specifying band number 1
    ps = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(), 1, rastShd)

    # assign the renderer to the raster layer:
    raster_layer.setRenderer(ps)

    # refresh
    raster_layer.triggerRepaint()


def vector_applyUniqueValueRenderer(vector_layer, column):
    """Apply colours to each unique value for a vector layer column.

    source: https://gis.stackexchange.com/a/175114

    Args:
        vector_layer (QgsVectorLayer): A vector layer to apply unique symbology to.
        column (str): The column containing the unique values

    """

    categories = []
    for eaVal in vector_layer.dataProvider().uniqueValues(vector_layer.fieldNameIndex(column)):
        # initialize the default symbol for this geometry type
        symbol = QgsSymbolV2.defaultSymbol(vector_layer.geometryType())

        # configure a symbol layer
        layer_style = {'color': '{}, {}, {}'.format(*random_colour()),
                       'outline': '#000000'}

        symbol_layer = QgsSimpleFillSymbolLayerV2.create(layer_style)

        # replace default symbol layer with the configured one
        if symbol_layer is not None:
            symbol.changeSymbolLayer(0, symbol_layer)

        # create renderer object
        category = QgsRendererCategoryV2(eaVal, symbol, str(eaVal))

        # entry for the list of category items
        categories.append(category)

    # create renderer object
    renderer = QgsCategorizedSymbolRendererV2(column, categories)

    # assign the created renderer to the layer
    if renderer is not None:
        vector_layer.setRendererV2(renderer)

    # refresh
    vector_layer.triggerRepaint()


def addVectorFileToQGIS(filename, layer_name='', group_layer_name='', atTop=True):
    """ Load a file as a vector layer into qgis

    Args:
        filename (str): the file to load
        layer_name (str): The name to apply to the vector layer
        group_layer_name (str):  Add the layer to a group. Use path separators to create multiple groups
        atTop (bool): Load to top of the table of contents. if false it will load above the active layer.
    Return:
         Vector Layer: The layer which has been loaded into QGIS
    """

    removeFileFromQGIS(filename)
    if layer_name == '':
        layer_name = os.path.splitext(os.path.basename(filename))[0]

    vector_layer = QgsVectorLayer(filename, layer_name, "ogr")

    addLayerToQGIS(vector_layer, group_layer_name=group_layer_name, atTop=atTop)

    return vector_layer


def addRasterFileToQGIS(filename, layer_name='', group_layer_name='', atTop=True):
    """ Load a file as a vector layer into qgis

    Args:
        filename (str): the file to load
        layer_name (str): The name to apply to the raster layer
        group_layer_name (str):  Add the layer to a group. Use path separators to create multiple groups
        atTop (bool): Load to top of the table of contents. if false it will load above the active layer.

    Returns:
        Raster Layer: The layer which has been loaded into QGIS
    """

    removeFileFromQGIS(filename)
    if layer_name == '':
        layer_name = os.path.splitext(os.path.basename(filename))[0]

    raster_layer = QgsRasterLayer(filename, layer_name)

    addLayerToQGIS(raster_layer, group_layer_name=group_layer_name, atTop=atTop)

    return raster_layer


def addLayerToQGIS(layer, group_layer_name="", atTop=True):
    """Add a layer to QGIS.

    source: https://gis.stackexchange.com/questions/93404/programmatically-change-layer-position-in-the-table-of-contents-qgis
            http://www.lutraconsulting.co.uk/blog/2014/07/06/qgis-layer-tree-api-part-1/
            http://www.lutraconsulting.co.uk/blog/2014/07/25/qgis-layer-tree-api-part-2/

    Args:
        layer (QGSLayer): The layer to add
        group_layer_name (str): Add to a group layer. path separators can be used for nested group layers
        atTop (str):

    """

    QgsMapLayerRegistry.instance().addMapLayer(layer, addToLegend=False)
    root = QgsProject.instance().layerTreeRoot()

    if group_layer_name != "":
        group_layer = root.findGroup(group_layer_name)
        if group_layer is None:
            if atTop:
                group_layer = root.insertGroup(0, group_layer_name)
            else:
                group_layer = root.addGroup(group_layer_name)

        node_layer = group_layer.addLayer(layer)
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

    RemoveLayers = []

    # Loop through layers in reverse so the count/indexing of layers persists if one is removed.
    layermap = QgsMapLayerRegistry.instance().mapLayers()
    for name, layer in layermap.iteritems():
        if layer.source() == filename:
            RemoveLayers.append(layer.id())

    if len(RemoveLayers) > 0:
        QgsMapLayerRegistry.instance().removeMapLayers(RemoveLayers)


def getGeometryTypeAsString(intGeomType):
    """ Get a string representing the integer geometry type which can be used in creating URI strings or memory layers.

        QGis.WkbType is a sip wrapped enum class which doesn't have a reverse mapping function like it would if
        it were a native python enum.

    Args:
        intGeomType (int):integer representing the geometry type (layer.dataprovider.geometryType(), or layer.wkbType())

    Returns: string representing Geometry type

    """
    geomTypeStr = {0: 'Unknown', 1: 'Point', 2: 'LineString', 3: 'Polygon', 4: 'MultiPoint', 5: 'MultiLineString',
                   6: 'MultiPolygon', 7: 'GeometryCollection', 8: 'CircularString', 9: 'CompoundCurve',
                   10: 'CurvePolygon', 11: 'MultiCurve', 12: 'MultiSurface', 100: 'NoGeometry', 1001: 'PointZ',
                   1002: 'LineStringZ', 1003: 'PolygonZ', 1004: 'MultiPointZ', 1005: 'MultiLineStringZ',
                   1006: 'MultiPolygonZ', 1007: 'GeometryCollectionZ', 1008: 'CircularStringZ', 1009: 'CompoundCurveZ',
                   1010: 'CurvePolygonZ', 1011: 'MultiCurveZ', 1012: 'MultiSurfaceZ', 2001: 'PointM',
                   2002: 'LineStringM',
                   2003: 'PolygonM', 2004: 'MultiPointM', 2005: 'MultiLineStringM', 2006: 'MultiPolygonM',
                   2007: 'GeometryCollectionM', 2008: 'CircularStringM', 2009: 'CompoundCurveM', 2010: 'CurvePolygonM',
                   2011: 'MultiCurveM', 2012: 'MultiSurfaceM', 3001: 'PointZM', 3002: 'LineStringZM', 3003: 'PolygonZM',
                   3004: 'MultiPointZM', 3005: 'MultiLineStringZM', 3006: 'MultiPolygonZM',
                   3007: 'GeometryCollectionZM',
                   3008: 'CircularStringZM', 3009: 'CompoundCurveZM', 3010: 'CurvePolygonZM', 3011: 'MultiCurveZM',
                   3012: 'MultiSurfaceZM'}
    # , 0x80000001: 'Point25D', : 'LineString25D', : 'Polygon25D', : 'MultiPoint25D', : 'MultiLineString25D', : 'MultiPolygon25D'}
    return geomTypeStr[intGeomType]


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
    memLayer = QgsVectorLayer("{}?crs={}&index=yes".format(getGeometryTypeAsString(layer.wkbType()),
                                                           layer.crs().authid()), layer_name, "memory")
    if not memLayer.isValid():
        raise Exception('Could not create memory Layer called {} from layer {}'.format(layer_name, layer.name()))

    memDataProv = memLayer.dataProvider()

    # Add the fields
    bCalcUFI = False
    attr = []

    if layer.fieldNameIndex("FID") == -1 and bAddUFI:
        bCalcUFI = True
        attr = [QgsField('FID', QVariant.Int)]

    invalidFields = []
    for eaFld in layer.dataProvider().fields():
        oldName = eaFld.name()
        newName = re.sub('[^A-Za-z0-9_-]+', '', oldName)[:10]

        if oldName != newName:
            invalidFields.append('   ' + oldName + '   to   ' + newName)
            eaFld.setName(newName)  # update the name
        attr.append(eaFld)

    if len(invalidFields) > 0:
        LOGGER.warning('{} fieldnames are not ESRI Compatible. Renaming...'.format(len(invalidFields)))

        for i, ea in enumerate(invalidFields):
            LOGGER.warning(ea)

    # Copy all existing fields
    memDataProv.addAttributes(attr)

    # tell the vector layer to fetch changes from the provider
    memLayer.updateFields()

    # start editing and copy all features and attributes
    memLayer.startEditing()
    selFeatIds = []
    if bOnlySelectedFeat and len(layer.selectedFeatures()) > 0:
        # Get a list of selected features.....
        selFeatIds = [f.id() for f in layer.selectedFeatures()]

    features = layer.getFeatures()
    feat = QgsFeature()

    id = 0
    for f in features:
        # Check the list of features against the selected list.
        # This will maintain the order of features when saved to shapefile.
        if bOnlySelectedFeat and len(selFeatIds) > 0:
            # Skip features which aren't in the selection
            if not f.id() in selFeatIds:
                continue

        feat.setGeometry(f.geometry())
        f_attr = []

        if bCalcUFI: f_attr += [id]

        # The order of fields hasn't changed so just add attributes.
        f_attr += f.attributes()
        feat.setAttributes(f_attr)
        memLayer.addFeatures([feat])
        id += 1

    memLayer.updateExtents()
    memLayer.commitChanges()

    return memLayer


def open_close_python_console():
    """ Open and close the python console
    This is a workaround for getting gui message bar to appear
    """
    try:
        bPythonConsoleOpen = False
        pythonConsolePanel = iface.mainWindow().findChild(QDockWidget, 'PythonConsole')
        bPythonConsoleOpen = pythonConsolePanel.isVisible()
        if not pythonConsolePanel.isVisible():
            iface.actionShowPythonDialog().trigger()
    except:
        # the above will bail if sitting on RecentProjects empty view.
        iface.actionShowPythonDialog().trigger()

    if not bPythonConsoleOpen:
        iface.actionShowPythonDialog().trigger()
