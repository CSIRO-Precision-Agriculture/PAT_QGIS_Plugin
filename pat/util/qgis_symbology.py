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
from builtins import range
from builtins import str
from builtins import zip
from collections import OrderedDict

from qgis.PyQt.QtGui import QColor

from qgis.core import (QgsCategorizedSymbolRenderer, QgsColorRampShader, QgsPalettedRasterRenderer, QgsRandomColorRamp,
                       QgsRasterBandStats, QgsRendererCategory, QgsSimpleFillSymbolLayer,
                       QgsSingleBandPseudoColorRenderer, QgsStyle, QgsSymbol)

RASTER_SYMBOLOGY = OrderedDict([('Yield', {'type': "Equal Interval",
                                           'num_classes':7,
                                           'colour_ramp': 'Yield 7 Colours',
                                           'invert':False}),
                                ('Image Indices (ie PCD, NDVI)', {'type': 'Quantile',
                                                             'num_classes':5,
                                                             'colour_ramp': 'Imagery 5 Colours',
                                                             'invert':False}),
                                ('Zones', {'type': 'unique',
                                           'colour_ramp': '',
                                           'invert':False}),
                                ('Block Grid', {'type': 'unique',
                                                'colour_ramp': '',
                                                'invert':False}),
                                ('Persistor - Target Probability', {'type': 'unique',
                                                                   'colour_ramp': 'RdYlGn',
                                                                   'invert':False}),
                                ('Persistor - All Years', {'type': 'unique',
                                                          'colour_ramp': 'Viridis',
                                                          'invert':True})])


def random_colour():
    """ Create a random RBG color
    """
    color = "#"+''.join([random.choice('0123456789ABCDEF') for j in range(6)])
    return QColor(color).getRgb()


def color_distance(c1,c2):
    return sum([abs(x[0]-x[1]) for x in zip(c1,c2)])


def generate_new_color(existing_colors):
    max_distance = None
    best_color = None
    for i in range(0,100):
        color = random_colour()
        if not existing_colors:
            return color
        best_distance = min([color_distance(color,c) for c in existing_colors])
        if not max_distance or best_distance > max_distance:
            max_distance = best_distance
            best_color = color
    return best_color


def random_colours(number_of_colours=1):
    """Create a list of random rgb colours ensuring they are not too similar to each other.
     adapted from  https://gist.github.com/adewes/5884820#file-generate_random_color-py
    """
    colours=[]
    for i in range(0,number_of_colours):
        colours.append(generate_new_color(colours))

    return colours


def raster_apply_classified_renderer(raster_layer, rend_type, num_classes, color_ramp,
                                     invert=False, band_num=1, n_decimals=1):
    """
    Applies quantile or equal intervals render to a raster layer. It also allows for the rounding of the values and
    legend labels.

    Args:
        raster_layer (QgsRasterLayer): The rasterlayer to apply classes to
        rend_type (str): The type of renderer to apply ('quantile' or 'equal interval')
        num_classes (int): The number of classes to create
        color_ramp (str): The colour ramp used to display the data
        band_num(int): The band number to use in the renderer
        invert (bool): invert the colour ramp
        n_decimals (int): the number of decimal places to round the values and labels


    Returns:

    """
    # use an existing color ramp
    qgsStyles = QgsStyle().defaultStyle()

    # check to see if the colour ramp is installed
    if color_ramp != '' and color_ramp not in qgsStyles.colorRampNames():
        raise ValueError('PAT symbology does not exist. See user manual for install instructions')

    ramp = qgsStyles.colorRamp(color_ramp)

    # get band statistics
    cbStats = raster_layer.dataProvider().bandStatistics(band_num, QgsRasterBandStats.All, raster_layer.extent(), 0)

    # create the renderer
    renderer = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(), band_num)

    # set the max and min heights we found earlier
    renderer.setClassificationMin(cbStats.minimumValue)
    renderer.setClassificationMax(cbStats.maximumValue)

    if rend_type.lower() == 'quantile':
        renderer.createShader(ramp, QgsColorRampShader.Discrete, QgsColorRampShader.Quantile,
                              num_classes)

    elif rend_type.lower() == 'equal interval':
        renderer.createShader(ramp, QgsColorRampShader.Discrete, QgsColorRampShader.EqualInterval,
                              num_classes)

    renderer.shader().rasterShaderFunction().setLabelPrecision(n_decimals)

    # Round values off to the nearest decimal place and construct the label
    # get the newly created values and classes
    color_shader = renderer.shader().rasterShaderFunction()

    # iterate the values rounding and creating a range label.
    new_lst = []
    for i, (value, color) in enumerate(color_shader.legendSymbologyItems(), start=1):
        value = float('{:.{dp}}g}'.format(float(value), dp=n_decimals))
        if i == 1:
            label = "<= {}".format(value)
        elif i == len(color_shader.legendSymbologyItems()):
            label = "> {}".format(last)
        else:
            label = "{} - {}".format(last, value)
        last = value

        new_lst.append(QgsColorRampShader.ColorRampItem(value, color, label))

    # apply back to the shader then the layer
    color_shader.setColorRampItemList(new_lst)

    raster_layer.setRenderer(renderer)
    raster_layer.triggerRepaint()

def raster_apply_unique_value_renderer(raster_layer, band_num=1, n_decimals=0,
                                       color_ramp='', invert=False):
    """
    Apply a random colour to each each unique value for a raster band.

    In some case the unique values are floating, n_decimals allows these to be rounded for display

    Args:
        raster_layer (QgsRasterLayer): input raster layer
        band_num (int):    the band number used to determine unique values
        n_decimals (int):  number of decimals to round values to
        invert (bool) : Invert the color ramp before applying - Not implemented
    """
    qgsStyles = QgsStyle().defaultStyle()
    # check to see if the colour ramp is installed
    if color_ramp != '' and color_ramp not in qgsStyles.colorRampNames():
        raise ValueError('PAT symbology does not exist. See user manual for install instructions')

    if color_ramp=='':
        ramp=QgsRandomColorRamp()
    else:
        # get an existing color ramp
        ramp = qgsStyles.colorRamp(color_ramp)

    # generate a list of unique values and their colours.
    uniq_classes = QgsPalettedRasterRenderer.classDataFromRaster(raster_layer.dataProvider(), band_num,ramp )

    # Create the renderer
    renderer = QgsPalettedRasterRenderer(raster_layer.dataProvider(), band_num, uniq_classes)

    # assign the renderer to the raster layer:
    raster_layer.setRenderer(renderer)

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
    uniq_vals = vector_layer.dataProvider().uniqueValues(vector_layer.fields().lookupField(column))
    randcolors = random_colours(len(uniq_vals))

    for i, ea_value in enumerate(sorted(uniq_vals)):
        # initialize the default symbol for this geometry type
        symbol = QgsSymbol.defaultSymbol(vector_layer.geometryType())

        # configure a symbol layer
        layer_style = {'color': '{}, {}, {}'.format(*randcolors[i]),
                       'outline': '#000000'}

        symbol_layer = QgsSimpleFillSymbolLayer.create(layer_style)

        # replace default symbol layer with the configured one
        if symbol_layer is not None:
            symbol.changeSymbolLayer(0, symbol_layer)

        # create renderer object
        category = QgsRendererCategory(ea_value, symbol, str(ea_value))

        # entry for the list of category items
        categories.append(category)

    # create renderer object
    renderer = QgsCategorizedSymbolRenderer(column, categories)

    # assign the created renderer to the layer
    if renderer is not None:
        vector_layer.setRenderer(renderer)

    # refresh
    vector_layer.triggerRepaint()
