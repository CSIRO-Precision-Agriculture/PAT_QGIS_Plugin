# coding=utf-8
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 qgis_symbology -  Functions for applying symbology to raster and vector layers
           -------------------
        begin      : 2019-01-30
        git sha    : $Format:%H$
        copyright  : (c) 2019, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
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

import random

import numpy as np
import rasterio
from PyQt4.QtGui import QColor
from qgis.core import (QgsSimpleFillSymbolLayerV2, QgsSymbolV2,
                       QgsRendererCategoryV2, QgsCategorizedSymbolRendererV2,
                       QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer)


def random_colour(mix=(255, 255, 255)):
    """ Create a random RBG color """
    red = random.randrange(0, 256)
    green = random.randrange(0, 256)
    blue = random.randrange(0, 256)
    r, g, b = mix
    red = (red + r) / 2
    green = (green + g) / 2
    blue = (blue + b) / 2
    return red, green, blue


def raster_apply_unique_value_renderer(raster_layer, band_num=1, n_decimals=0):
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
    col_rmp_shd = QgsColorRampShader()

    # name a type for the ramp shader. In this case, we use an INTERPOLATED shader:
    col_rmp_shd.setColorRampType(QgsColorRampShader.EXACT)
    qri = QgsColorRampShader.ColorRampItem

    sym_classes = []
    for class_val in uniq_vals:
        # apply unique values renderer.
        r, g, b = random_colour()
        sym_classes.append(qri(class_val, QColor(r, g, b, 255), str(class_val)))

    # assign the color ramp to our shader:
    col_rmp_shd.setColorRampItemList(sym_classes)

    # create a generic raster shader object:
    raster_shader = QgsRasterShader()
    # tell the generic raster shader to use the color ramp:
    raster_shader.setRasterShaderFunction(col_rmp_shd)

    # create a raster renderer object with the shader, specifying band number 1
    ps = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(), 1, raster_shader)

    # assign the renderer to the raster layer:
    raster_layer.setRenderer(ps)

    # refresh
    raster_layer.triggerRepaint()


def vector_apply_unique_value_renderer(vector_layer, column):
    """Apply colours to each unique value for a vector layer column.

    source: https://gis.stackexchange.com/a/175114

    Args:
        vector_layer (QgsVectorLayer): A vector layer to apply unique symbology to.
        column (str): The column containing the unique values

    """

    categories = []
    for ea_value in vector_layer.dataProvider().uniqueValues(vector_layer.fieldNameIndex(column)):
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
        category = QgsRendererCategoryV2(ea_value, symbol, str(ea_value))

        # entry for the list of category items
        categories.append(category)

    # create renderer object
    renderer = QgsCategorizedSymbolRendererV2(column, categories)

    # assign the created renderer to the layer
    if renderer is not None:
        vector_layer.setRendererV2(renderer)

    # refresh
    vector_layer.triggerRepaint()
