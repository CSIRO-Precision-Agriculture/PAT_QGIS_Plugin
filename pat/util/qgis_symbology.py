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

from builtins import zip
from builtins import str
from builtins import range
import random
from collections import OrderedDict
import numpy as np
import rasterio
from qgis.PyQt.QtGui import QColor
import matplotlib as mpl
import matplotlib.colors as colors
from numpy import ma
from qgis.core import QgsSimpleFillSymbolLayer, QgsSymbol, QgsStyle,QgsRendererCategory, QgsCategorizedSymbolRenderer, QgsRaster, QgsRasterShader, QgsColorRampShader,QgsSingleBandPseudoColorRenderer,QgsRasterShader, QgsColorRampShader,QgsContrastEnhancement

from scipy import stats

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
    for i in range(0,10):
        colours.append(generate_new_color(colours))

    return colours


def raster_apply_classified_renderer(raster_layer, rend_type, num_classes, color_ramp,
                                     invert=False, band_num=1):

    # get an existing color ramp
    qgsStyles = QgsStyle().defaultStyle()

    # check to see if the colour ramp is installed
    if color_ramp != '' and color_ramp not in qgsStyles.colorRampNames():
        raise ValueError('PAT symbology does not exist. See user manual for install instructions')

    ramp = qgsStyles.colorRamp(color_ramp)

    rmp_colors = [ramp.color1().name()]   # the first
    rmp_colors += [ea.color.name() for ea in  ramp.stops()]

    # check that the last colors not already there
    if rmp_colors[-1] != ramp.color2().name():
        rmp_colors += [ramp.color2().name()]
    if invert:
        rmp_colors = list(reversed(rmp_colors))

    # convert to qcolor
    rmp_colors = [QColor(col) for col in rmp_colors]

    band = rasterio.open(raster_layer.source()).read(band_num, masked=True)

    classes = []
    if rend_type.lower() == 'quantile':
        classes = np.interp(np.linspace(0, ma.count(band), num_classes + 1),
                            np.arange( ma.count(band)), np.sort(ma.compressed(band)))

    elif rend_type.lower() == 'equal interval':
        classes, bin_width = np.linspace(np.nanmin(band), np.nanmax(band), num_classes + 1,
                                         endpoint=True, retstep=True)

    classes = [float('{:.3g}'.format(ea)) for ea in classes]

    del band

    #Apply raster layer enhancement/stretch
    stretch = QgsContrastEnhancement.StretchToMinimumMaximum
    limits = QgsRaster.ContrastEnhancementMinMax
    raster_layer.setContrastEnhancement(stretch, limits)

    # Create the symbology
    color_ramp_shd = QgsColorRampShader()
    color_ramp_shd.setColorRampType(QgsColorRampShader.DISCRETE)
    qri = QgsColorRampShader.ColorRampItem

    sym_classes = []
    low_class = 0

    for class_color, up_class in zip(rmp_colors, classes[1:]):
        if low_class == 0:
            sym_classes.append(qri(up_class, class_color, '<= {} '.format(up_class)))
        elif up_class == classes[-1]:
            sym_classes.append(qri(float("inf"),class_color, '> {} '.format(low_class)))
        else:
            sym_classes.append(qri(up_class, class_color, '{} - {} '.format(low_class,up_class)))

        low_class = up_class

    color_ramp_shd.setColorRampItemList(sym_classes)

    #Apply symbology to layer
    raster_shader = QgsRasterShader()
    raster_shader.setRasterShaderFunction(color_ramp_shd)
    pseudo_renderer = QgsSingleBandPseudoColorRenderer(raster_layer.dataProvider(),
                                                       1, raster_shader)
    raster_layer.setRenderer(pseudo_renderer)
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
    """
    qgsStyles = QgsStyle().defaultStyle()
    # check to see if the colour ramp is installed
    if color_ramp != '' and color_ramp not in qgsStyles.colorRampNames():
        raise ValueError('PAT symbology does not exist. See user manual for install instructions')

    # get unique values
    band = rasterio.open(raster_layer.source()).read(band_num, masked=True)
    uniq_vals = np.unique(band[band.mask == False])

    if n_decimals > 0:
        uniq_vals = np.around(list(uniq_vals), decimals=3)

    if color_ramp == '':
        rmp_colors = [QColor(*colour) for colour in random_colours(len(uniq_vals))]
        #rmp_colors = random_colours(len(uniq_vals))

    else:
        # get an existing color ramp
        ramp = qgsStyles.colorRamp(color_ramp)

        rmp_colors = [ramp.color1().name()]   # the first
        rmp_colors += [ea.color.name() for ea in  ramp.stops()]

        # check that the last colors not already there
        if rmp_colors[-1] != ramp.color2().name():
            rmp_colors += [ramp.color2().name()]

        if invert:
            rmp_colors = list(reversed(rmp_colors))

        #use this to create a matplotlib color ramp
        cmSeg = colors.LinearSegmentedColormap.from_list('myramp', rmp_colors, N=256)

        # get the colors distributed evenly across the ramp
        rmp_colors = [QColor(*cmSeg(idx,bytes=True)) for idx in np.linspace(0, 1, len(uniq_vals))]


    # instantiate the specialized ramp shader object
    col_rmp_shd = QgsColorRampShader()

    # name a type for the ramp shader. In this case, we use an INTERPOLATED shader:
    col_rmp_shd.setColorRampType(QgsColorRampShader.Exact)
    qri = QgsColorRampShader.ColorRampItem

    sym_classes = []
    for class_val, class_color in zip(uniq_vals, rmp_colors):
        sym_classes.append(qri(class_val, class_color, str(class_val)))

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
    uniq_vals = vector_layer.dataProvider().uniqueValues(vector_layer.fields().lookupField(column))
    randcolors = random_colours(len(uniq_vals))

    for i, ea_value in enumerate(uniq_vals):
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
