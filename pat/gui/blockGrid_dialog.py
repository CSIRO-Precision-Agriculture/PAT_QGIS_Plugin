# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 BlockGridDialog - Create Tif and VESPER Grid file
           -------------------
        begin      : 2017-05-25
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

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT

from qgis.core import Qgis, QgsApplication
from qgis.PyQt import QtGui, uic, QtCore, QtWidgets

from qgis.PyQt.QtWidgets import QPushButton, QDialog, QApplication
from qgis.core import QgsMapLayer, QgsVectorFileWriter,  QgsMapLayerProxyModel
from qgis.gui import QgsMessageBar, QgisInterface

from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import (removeFileFromQGIS, addVectorFileToQGIS, addRasterFileToQGIS,
                                save_as_dialog, get_UTM_Coordinate_System, get_layer_source)
from util.qgis_symbology import RASTER_SYMBOLOGY, raster_apply_unique_value_renderer
from util.settings import read_setting, write_setting

from pyprecag import config, processing
from pyprecag.convert import numeric_pixelsize_to_string

from pat.util.qgis_common import save_layer_to_shapefile

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'blockGrid_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # Handle logging, no logging has been configured


class BlockGridDialog(QDialog, FORM_CLASS):
    """Convert a polygon boundary to a 0,1 raster and generate a VESPER compatible list of coordinates for kriging.
    """

    # The key used for saving settings for this dialog
    toolKey = 'BlockGridDialog'

    def __init__(self, iface: QgisInterface, parent=None):

        super().__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        # The qgis interface
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.outQgsCRS = None
        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)
        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtWidgets.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), QtWidgets.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        #self.setMapLayers()
        self.mcboTargetLayer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.mcboTargetLayer.setAllowEmptyLayer(False)
        self.mcboTargetLayer.setShowCrs(True)
        self.mcboTargetLayer.setLayer(None)    # set default to empty layer

        # GUI Runtime Customisation -----------------------------------------------

        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_blockGrid.svg'))
        # hide some objects on the form, delete later if no longer needed.
        self.chkDisplayResults.hide()
        self.lblNoDataVal.hide()
        self.spnNoDataVal.hide()

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

    def send_to_messagebar(self, message, title='', level=Qgis.Info, duration=5, exc_info=None,
                           core_QGIS=False, addToLog=False, showLogPanel=False):

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

    def setMapLayers(self):
        """ Run through all loaded layers to find ones which should be excluded. In this case exclude geographics."""

        exlayer_list = []

        for layer in self.iface.legendInterface().layers():
            # Only Load Vector layers
            if layer.type() != QgsMapLayer.VectorLayer:
                continue

            if layer.crs().isGeographic():
                exlayer_list.append(layer)

            if len(exlayer_list) > 0:
                self.mcboTargetLayer.setExceptedLayerList(exlayer_list)

            self.updateUseSelected()

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""
        if self.mcboTargetLayer.currentLayer() is None:
            return

        if self.mcboTargetLayer.count() == 0:
            return


        lyrTarget = self.mcboTargetLayer.currentLayer()

        if lyrTarget.selectedFeatureCount()  > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(lyrTarget.selectedFeatureCount()))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def on_mcboTargetLayer_layerChanged(self):
        if self.mcboTargetLayer.currentLayer() is None:
            return
        
        if self.mcboTargetLayer.currentLayer().crs().authid() == '':
            return 
        
        self.updateUseSelected()
        layer = self.mcboTargetLayer.currentLayer()
        if layer.crs().isGeographic():
            self.outQgsCRS = get_UTM_Coordinate_System(layer.extent().xMinimum(),
                                                   layer.extent().yMinimum(),
                                                   layer.crs().authid())
        else:
            self.outQgsCRS = layer.crs()

        if self.outQgsCRS:
            self.mCRSoutput.setCrs(self.outQgsCRS)

            self.lblTargetLayer.setStyleSheet('color:black')

    @QtCore.pyqtSlot(name='on_cmdSaveRasterFile_clicked')
    def on_cmdSaveRasterFile_clicked(self):

        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")

        pixel_size_str = numeric_pixelsize_to_string(self.dsbPixelSize.value())
        filename = '{}_BlockGrid_{}'.format(self.mcboTargetLayer.currentLayer().name(), pixel_size_str)
        filename = re.sub('[^A-Za-z0-9_-]+', '', filename)

        s = save_as_dialog(self, self.tr("Save As"),
                         self.tr("Tiff") + " (*.tif);;",
                         default_name=os.path.join(lastFolder, filename + '.tif'))

        if s == '' or s is None:
            return

        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))
        self.lneSaveRasterFile.setText(s)
        self.lneSaveRasterFile.setStyleSheet('color:black')

    @QtCore.pyqtSlot(int)
    def on_chkAutoCRS_stateChanged(self, state):
        if self.chkAutoCRS.isChecked():
            layer = self.mcboTargetLayer.currentLayer()
            self.outQgsCRS = get_UTM_Coordinate_System(self, layer.extent().xMinimum(),
                                                    layer.extent().yMinimum(),
                                                    int(layer.crs().authid().replace('EPSG:', '')))

            if self.outQgsCRS:
                self.mCRSoutput.setCrs(self.outQgsCRS)

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""

        self.cleanMessageBars(AllBars=True)

        try:
            errorList = []
            targetLayer = self.mcboTargetLayer.currentLayer()
            if targetLayer is None or self.mcboTargetLayer.currentLayer().name() == '':
                self.lblTargetLayer.setStyleSheet('color:red')
                errorList.append(self.tr('Target layer is not set'))
            else:
                self.lblTargetLayer.setStyleSheet('color:black')

            if not self.mCRSoutput.crs().isValid() or self.mCRSoutput.crs().isGeographic():

                errorList.append(self.tr('Output coordinate system is geographic. Please select a PROJECTED coordinate system'))
                self.lblOutCRSTitle.setStyleSheet('color:red')
            else:
                self.lblOutCRSTitle.setStyleSheet('color:black')

            if self.lneSaveRasterFile.text() == '':
                self.lneSaveRasterFile.setStyleSheet('color:red')
                errorList.append(self.tr("Please enter an output raster filename"))
            elif not os.path.exists(os.path.dirname(self.lneSaveRasterFile.text())):
                self.lneSaveRasterFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output folder does not exist."))
            else:
                self.lneSaveRasterFile.setStyleSheet('color:black')

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
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            if self.iface.mainWindow() :
                self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            # Add settings to log.
            settingsStr = 'Parameters:---------------------------------------'
            if self.chkUseSelected.isChecked():
                settingsStr += '\n    {:30}\t{} with {} selected features'.format('Layer:',
                                                                                  self.mcboTargetLayer.currentLayer().name(),
                                                                                  self.mcboTargetLayer.currentLayer().selectedFeatureCount())
            else:
                settingsStr += '\n    {:30}\t{}'.format('Layer:', self.mcboTargetLayer.currentLayer().name())

            settingsStr += '\n    {:30}\t{}'.format('Output Raster File:', self.lneSaveRasterFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Pixel Size:', self.dsbPixelSize.value())
            settingsStr += '\n    {:30}\t{}'.format('No Data Value:', self.spnNoDataVal.value())
            settingsStr += '\n    {:30}\t{}'.format('Snap To Extent:', self.chkSnapExtent.isChecked())
            settingsStr += '\n Derived Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Output Vesper File:',
                                                        os.path.splitext(self.lneSaveRasterFile.text())[0] + '_v.txt')
            settingsStr += '\n    {:30}\t{} - {}\n'.format('Output Projected Coordinate System:',
                                                              self.mCRSoutput.crs().authid(),
                                                              self.mCRSoutput.crs().description())

            LOGGER.info(settingsStr)

            lyrTarget = self.mcboTargetLayer.currentLayer()

            rasterFile = self.lneSaveRasterFile.text()
            removeFileFromQGIS(rasterFile)

            if self.chkUseSelected.isChecked():
                polyFile = os.path.join(TEMPDIR, '{}_selection.shp'.format(lyrTarget.name()))
                removeFileFromQGIS(polyFile)

                layer = save_layer_to_shapefile(lyrTarget, polyFile,onlySelected=True)

                LOGGER.info('{:<30} {:<15} {}'.format('Save layer/selection to file', polyFile, ''))
                if self.DISP_TEMP_LAYERS:
                    addVectorFileToQGIS(polyFile, group_layer_name='DEBUG', atTop=True)

            else:
                polyFile = get_layer_source(lyrTarget)

            processing.block_grid(in_shapefilename=polyFile,
                                  pixel_size=self.dsbPixelSize.value(),
                                  out_rasterfilename=rasterFile,
                                  out_vesperfilename=os.path.splitext(rasterFile)[0] + '_v.txt',
                                  nodata_val=self.spnNoDataVal.value(),
                                  snap=self.chkSnapExtent.isChecked(),
                                  out_epsg=int(self.mCRSoutput.crs().authid().replace("EPSG:",'')),
                                  overwrite=True)  # The saveAS dialog takes care of the overwrite issue.

            if self.chkDisplayResults.isChecked():
                raster_layer = addRasterFileToQGIS(rasterFile, atTop=False)
                raster_sym = RASTER_SYMBOLOGY['Block Grid']
                raster_apply_unique_value_renderer(raster_layer,1,
                                               color_ramp=raster_sym['colour_ramp'],
                                               invert=raster_sym['invert'])


            #QApplication.restoreOverrideCursor()
            QApplication.restoreOverrideCursor()
            if self.iface.mainWindow():
                self.iface.mainWindow().statusBar().clearMessage()

            return super(BlockGridDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QApplication.restoreOverrideCursor()
            if self.iface.mainWindow():
                self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.send_to_messagebar(str(err), level=Qgis.Critical, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=sys.exc_info())
            return False  # leave dialog open
