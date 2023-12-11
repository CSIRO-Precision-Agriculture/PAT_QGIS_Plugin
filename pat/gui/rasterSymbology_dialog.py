# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 RasterSymbologyDialog - Rescale or normalise a single band from an image
           -------------------
        begin      : 2018-04-09
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the associated CSIRO Open Source Software       *
 *   License Agreement (GPLv3) provided with this plugin.                  *
 *                                                                         *
 ***************************************************************************/
"""

from builtins import str
from builtins import range
import logging
import os
import re
import sys
import traceback
from collections import OrderedDict

from qgis.PyQt import QtGui, uic, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QPushButton, QApplication, QDialog, QDialogButtonBox

from qgis.core import QgsMessageLog, QgsStyle, QgsMapLayer, QgsApplication, QgsMapLayerProxyModel, Qgis
from qgis.gui import QgsMessageBar

import rasterio
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import removeFileFromQGIS, addRasterFileToQGIS, save_as_dialog
from util.settings import read_setting, write_setting
import util.qgis_symbology as rs

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'rasterSymbology_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())


class RasterSymbologyDialog(QDialog, FORM_CLASS):
    """Dialog for Rescaling or normalising a single band from an image"""

    toolKey = 'RasterSymbologyDialog'

    def __init__(self, iface, parent=None):

        super(RasterSymbologyDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        # Add apply action
        self.button_box.button(QDialogButtonBox.Apply).clicked.connect(self.accept)

        # The qgis interface
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui --------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtWidgets.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), QtWidgets.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # GUI Customisation -----------------------------------------------
        self.mcboTargetLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.mcboTargetLayer.setExcludedProviders(['wms'])

        # self.setMapLayers()
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_rasterSymbology.svg'))
        self.cboType.addItems(list(rs.RASTER_SYMBOLOGY))
        
        rlayer = next(lyr for lyr in self.iface.layerTreeView().selectedLayers() if lyr.type() == QgsMapLayer.RasterLayer)
        self.mcboTargetLayer.setLayer(rlayer)

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including those which haven't timed-out. Defaults to True
        """
        layout = self.validationLayout
        for i in reversed(list(range(layout.count()))):
            # when it timed out the row becomes empty....
            if layout.itemAt(i).isEmpty():
                # .removeItem doesn't always work. so takeAt(pop) it instead
                item = layout.takeAt(i)
            elif AllBars:  # ie remove all
                item = layout.takeAt(i)
                # also have to remove any widgets associated with it.
                if item.widget() is not None:
                    item.widget().deleteLater()

    def send_to_messagebar(self, message, title='', level=Qgis.Info, duration=5,
                           exc_info=None, core_QGIS=False, addToLog=False, showLogPanel=False):

        """ Add a message to the forms message bar.

        Args:
            message (str): Message to display
            title (str): Title of message. Will appear in bold. Defaults to ''
            level (QgsMessageBarLevel): The level of message to log. Defaults to Qgis.Info
            duration (int): Number of seconds to display message for. 0 is no timeout. Defaults to 5
            core_QGIS (bool): Add to QGIS interface rather than the dialog
            addToLog (bool): Also add message to Log. Defaults to False
            showLogPanel (bool): Display the log panel
            exc_info () : Information to be used as a traceback if required

        """

        if core_QGIS:
            newMessageBar = self.iface.messageBar()
        else:
            newMessageBar = QgsMessageBar(self)

        widget = newMessageBar.createMessage(title, message)

        if showLogPanel:
            button = QPushButton(widget)
            button.setText('View')
            button.setContentsMargins(0, 0, 0, 0)
            button.setFixedWidth(35)
            button.pressed.connect(openLogPanel)
            widget.layout().addWidget(button)

        newMessageBar.pushWidget(widget, level, duration=duration)

        if not core_QGIS:
            rowCount = self.validationLayout.count()
            self.validationLayout.insertRow(rowCount + 1, newMessageBar)

        if addToLog:
            if level == 1:  # 'WARNING':
                LOGGER.warning(message)
            elif level == 2:  # 'CRITICAL':
                # Add a traceback to log only for bailouts only
                if exc_info is not None:
                    exc_type, exc_value, exc_traceback = sys.exc_info()
                    mess = str(traceback.format_exc())
                    message = message + '\n' + mess

                LOGGER.critical(message)
            else:  # INFO = 0
                LOGGER.info(message)

    # def setMapLayers(self):
    #     """ Run through all loaded layers to find ones which should be excluded. In this case exclude geographics."""
    #
    #     exlayer_list = []
    #
    #     for layer in self.iface.legendInterface().layers():
    #         # Only Load Raster layers with matching pixel size
    #         if layer.type() != QgsMapLayer.RasterLayer:
    #             continue
    #         if layer.bandCount() > 1:
    #             exlayer_list.append(layer)
    #             continue
    #
    #     self.mcboTargetLayer.setExceptedLayerList(exlayer_list)

    def on_mcboTargetLayer_layerChanged(self):
        pass

    @QtCore.pyqtSlot(int)
    def on_cboType_currentIndexChanged(self, index):
        pass

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            errorList = []
            rast_sym = rs.RASTER_SYMBOLOGY[self.cboType.currentText()]
            # check to see if the colour ramp is installed
            qgs_styles = QgsStyle().defaultStyle()

            if rast_sym['colour_ramp'] != '' and rast_sym['colour_ramp'] not in qgs_styles.colorRampNames():
                errorList = ['PAT symbology does not exist. See user manual for install instructions']

            if len(errorList) > 0:
                raise ValueError(errorList)

        except ValueError as e:
            self.cleanMessageBars(True)
            if len(errorList) > 0:
                for i, ea in enumerate(errorList):
                    self.send_to_messagebar(str(ea), level=Qgis.Warning, duration=(i + 1) * 5)
                return False

        return True

    def accept(self, *args, **kwargs):
        if not self.validate():
            return False
        try:
            rast_sym = rs.RASTER_SYMBOLOGY[self.cboType.currentText()]
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            if rast_sym['type'] == 'unique':
                rs.raster_apply_unique_value_renderer(self.mcboTargetLayer.currentLayer(), 1,
                                                      color_ramp=rast_sym['colour_ramp'],
                                                      invert=rast_sym['invert'])
            else:

                rs.raster_apply_classified_renderer(self.mcboTargetLayer.currentLayer(),
                                                    rend_type=rast_sym['type'],
                                                    num_classes=rast_sym['num_classes'],
                                                    color_ramp=rast_sym['colour_ramp'])

            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            return False # leave dialog open

        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.iface.mainWindow().statusBar().clearMessage()

            self.send_to_messagebar(str(err), level=Qgis.Critical,
                                    duration=0, addToLog=True, exc_info=sys.exc_info())
            return False  # leave dialog open
