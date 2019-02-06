# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  ResampleImageBandDialog - Extract statistics from a list of rasters at set locations.
           -------------------
        begin      : 2018-09-24
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

import logging
import os
import sys
import traceback

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import saveAsDialog, file_in_use, removeFileFromQGIS, \
    copyLayerToMemory, addVectorFileToQGIS, addRasterFileToQGIS
from util.settings import read_setting, write_setting

from pyprecag import config, crs
from pyprecag.processing import resample_bands_to_block

from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QPushButton

from qgis.core import (QgsMapLayer, QgsMessageLog, QgsVectorFileWriter, QgsCoordinateReferenceSystem)
from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'resampleImageToBlock_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class ResampleImageToBlockDialog(QtGui.QDialog, FORM_CLASS):
    """Extract statistics from a list of rasters at set locations."""
    toolKey = 'ResampleImageBandDialog'

    def __init__(self, iface, parent=None):

        super(ResampleImageToBlockDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsMessageLog.instance().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtGui.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), (QtGui.QFormLayout, QtGui.QGridLayout)):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        self.outQgsCRS = None

        self.exclude_map_layers()
        self.updateRaster()
        self.updateUseSelected()
        self.autoSetCoordinateSystem()

        # GUI Runtime Customisation -----------------------------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_resampleToBlock.svg'))
        self.chkAddToDisplay.setChecked(False)
        # self.chkAddToDisplay.hide()

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including those which haven't timed-out. Defaults to True
        """
        layout = self.validationLayout
        for i in reversed(range(layout.count())):
            # when it timed out the row becomes empty....
            if layout.itemAt(i).isEmpty():
                # .removeItem doesn't always work. so takeAt(pop) it instead
                item = layout.takeAt(i)
            elif AllBars:  # ie remove all
                item = layout.takeAt(i)
                # also have to remove any widgets associated with it.
                if item.widget() is not None:
                    item.widget().deleteLater()

    def send_to_messagebar(self, message, title='', level=QgsMessageBar.INFO, duration=5, exc_info=None,
                           core_QGIS=False, addToLog=False, showLogPanel=False):

        """ Add a message to the forms message bar.

        Args:
            message (str): Message to display
            title (str): Title of message. Will appear in bold. Defaults to ''
            level (QgsMessageBarLevel): The level of message to log. Defaults to QgsMessageBar.INFO
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

    def exclude_map_layers(self):
        """ Run through all loaded layers to find ones which should be excluded. In this case exclude services."""

        exVlayer_list = []
        exRlayer_list = []
        for layer in self.iface.legendInterface().layers():
            if layer.type() == QgsMapLayer.RasterLayer:
                if layer.providerType() != 'gdal':
                    exRlayer_list.append(layer)

            elif layer.type() == QgsMapLayer.VectorLayer:
                if layer.providerType() != 'ogr':
                    exVlayer_list.append(layer)

        self.mcboRasterLayer.setExceptedLayerList(exRlayer_list)
        if len(exRlayer_list) > 0:
            pass

        if len(exVlayer_list) > 0:
            self.mcboPolygonLayer.setExceptedLayerList(exVlayer_list)

    def updateRaster(self):
        if self.mcboRasterLayer.currentLayer() is None: return

        layer = self.mcboRasterLayer.currentLayer()
        provider = layer.dataProvider()

        if provider.srcHasNoDataValue(1):
            self.spnNoDataVal.setValue(provider.srcNoDataValue(1))
        elif len(provider.userNoDataValues(1)) > 0:
            self.spnNoDataVal.setValue(provider.userNoDataValues(1)[0].min())
        else:
            self.spnNoDataVal.setValue(0)

        # add a band list to the drop down box
        bandCount = self.mcboRasterLayer.currentLayer().bandCount()
        band_list = ['Band {}'.format(i) for i in range(1, bandCount + 1)]
        self.cboBand.clear()
        self.cboBand.addItems([u''] + sorted(band_list))

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        self.chkUseSelected.setChecked(False)

        if self.mcboPolygonLayer.count() == 0:
            return

        polygon_lyr = self.mcboPolygonLayer.currentLayer()
        self.mFieldComboBox.setLayer(polygon_lyr)
        if len(polygon_lyr.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(len(polygon_lyr.selectedFeatures())))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def autoSetCoordinateSystem(self):
        if self.mcboRasterLayer.count() == 0:
            return
        self.cleanMessageBars()
        raster_lyr = self.mcboRasterLayer.currentLayer()

        raster_utm_crs = crs.getProjectedCRSForXY(raster_lyr.extent().xMinimum(),
                                                  raster_lyr.extent().yMinimum(),
                                                  int(raster_lyr.crs().authid().replace('EPSG:', '')))
        self.outQgsCRS = None

        if raster_utm_crs is not None:
            raster_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(raster_utm_crs.epsg_number))
            self.outQgsCRS = raster_crs

        if self.outQgsCRS is not None:
            self.lblOutCRS.setText('{}  -  {}'.format(self.outQgsCRS.description(), self.outQgsCRS.authid()))
            self.lblOutCRSTitle.setStyleSheet('color:black')
            self.lblOutCRS.setStyleSheet('color:black')
        else:
            self.lblOutCRSTitle.setStyleSheet('color:red')
            self.lblOutCRS.setStyleSheet('color:red')
            self.lblOutCRS.setText('Unspecified')
            self.send_to_messagebar(
                'Auto detect coordinate system Failed. Check coordinate system of input raster layer',
                level=QgsMessageBar.CRITICAL, duration=5)
        return

    def on_mcboRasterLayer_layerChanged(self):
        self.updateRaster()
        self.autoSetCoordinateSystem()

    def on_mcboPolygonLayer_layerChanged(self):
        self.updateUseSelected()
        self.autoSetCoordinateSystem()

        # ToDo: QGIS 3 implement QgsMapLayerComboBox.allowEmptyLayer() instead of chkUsePoly checkbox
        self.chkUsePoly.setChecked(True)

    @QtCore.pyqtSlot(int)
    def on_chkUsePoly_stateChanged(self, state):
        if not state:
            # work around for not having a physical blank in the list. Fixed in qgis 3 
            self.mFieldComboBox.setField(u'')

        self.mFieldComboBox.setEnabled(state)
        self.lblGroupByField.setEnabled(state)

    def on_chkUseSelected_stateChanged(self, state):
        if self.chkUseSelected.isChecked():
            self.chkUsePoly.setChecked(True)

    @QtCore.pyqtSlot(name='on_cmdOutCRS_clicked')
    def on_cmdOutCRS_clicked(self):
        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage(self.tr('Select coordinate system'))
        if dlg.exec_():
            if dlg.selectedAuthId() != '':
                self.outQgsCRS = QgsCoordinateReferenceSystem(dlg.selectedAuthId())

                if self.outQgsCRS.geographicFlag():
                    self.outQgsCRS = None
                    self.send_to_messagebar(
                        unicode(self.tr("Geographic coordinate systems are not allowed. Resetting to default..")),
                        level=QgsMessageBar.WARNING, duration=5)
            else:
                self.outQgsCRS = None

            if self.outQgsCRS is None:
                self.autoSetCoordinateSystem()

            self.lblOutCRSTitle.setStyleSheet('color:black')
            self.lblOutCRS.setStyleSheet('color:black')
            self.lblOutCRS.setText(self.tr('{}  -  {}'.format(self.outQgsCRS.description(), self.outQgsCRS.authid())))

    @QtCore.pyqtSlot(name='on_cmdOutputFolder_clicked')
    def on_cmdOutputFolder_clicked(self):
        self.messageBar.clearWidgets()
        if self.lneOutputFolder.text() is None:
            outFolder = ''
        else:
            outFolder = self.lneOutputFolder.text()

        if outFolder == '':
            outFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
            if outFolder is None or not os.path.exists(outFolder):
                outFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        s = QtGui.QFileDialog.getExistingDirectory(self, self.tr(
            "Save output files to a folder. A sub-folder will be created from the image name"),
                                                   outFolder, QtGui.QFileDialog.ShowDirsOnly)

        self.cleanMessageBars(self)
        if s == '' or s is None:
            return

        s = os.path.normpath(s)

        self.lblOutputFolder.setStyleSheet('color:black')
        self.lneOutputFolder.setStyleSheet('color:black')
        self.lneOutputFolder.setText(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", s)

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.messageBar.clearWidgets()
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []

            if self.mcboRasterLayer.currentLayer() is None:
                self.lblRasterLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input image layer required."))
            else:
                self.lblRasterLayer.setStyleSheet('color:black')

            if self.cboBand.currentText() == '':
                self.lblBand.setStyleSheet('color:red')
                errorList.append(self.tr("Input band selection required."))
            else:
                self.lblBand.setStyleSheet('color:black')

            if self.dsbPixelSize.value() <= 0:
                self.lblPixelSize.setStyleSheet('color:red')
                errorList.append(self.tr("Pixel size must be greater than 0."))
            else:
                self.lblPixelSize.setStyleSheet('color:black')

            if self.outQgsCRS is None:
                self.lblOutCRSTitle.setStyleSheet('color:red')
                self.lblOutCRS.setStyleSheet('color:red')
                errorList.append(self.tr("Select output projected coordinate system"))
            else:
                if self.outQgsCRS.geographicFlag():
                    self.lblOutCRSTitle.setStyleSheet('color:red')
                    self.lblOutCRS.setStyleSheet('color:red')
                    errorList.append(self.tr("Output projected coordinate system (not geographic) required"))
                else:
                    self.lblOutCRSTitle.setStyleSheet('color:black')
                    self.lblOutCRS.setStyleSheet('color:black')

            if self.lneOutputFolder.text() == '':
                self.lblOutputFolder.setStyleSheet('color:red')
                errorList.append(self.tr("Select output data folder"))
            elif not os.path.exists(self.lneOutputFolder.text()):
                self.lneOutputFolder.setStyleSheet('color:red')
                self.lblOutputFolder.setStyleSheet('color:red')
                errorList.append(self.tr("Output data folder does not exist"))
            else:
                self.lblOutputFolder.setStyleSheet('color:black')
                self.lneOutputFolder.setStyleSheet('color:black')

            if len(errorList) > 0:
                raise ValueError(errorList)

        except ValueError as e:
            self.cleanMessageBars(True)
            if len(errorList) > 0:
                for i, ea in enumerate(errorList):
                    self.send_to_messagebar(unicode(ea), level=QgsMessageBar.WARNING, duration=(i + 1) * 5)
                return False

        return True

    def accept(self, *args, **kwargs):
        try:

            if not self.validate():
                return False

            # disable form via a frame, this will still allow interaction with the message bar
            self.fraMain.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)

            # Change cursor to Wait cursor
            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait.. QGIS will be locked... See log panel for progress.",
                                    level=QgsMessageBar.WARNING,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:20}\t{}'.format('Image layer:', self.mcboRasterLayer.currentLayer().name())
            settingsStr += '\n    {:20}\t{}'.format('Image Band:', self.cboBand.currentText())
            settingsStr += '\n    {:20}\t{}'.format('Image nodata value:', self.spnNoDataVal.value())

            if self.chkUsePoly.isChecked():
                if self.chkUseSelected.isChecked():
                    settingsStr += '\n    {:20}\t{} with {} selected features'.format('Layer:',
                                                                                      self.mcboPolygonLayer.currentLayer().name(),
                                                                                      len(
                                                                                          self.mcboPolygonLayer.currentLayer().selectedFeatures()))
                else:
                    settingsStr += '\n    {:20}\t{}'.format('Boundary layer:',
                                                            self.mcboPolygonLayer.currentLayer().name())

                if self.mFieldComboBox.currentField():
                    settingsStr += '\n    {:20}\t{}'.format('Block ID field:', self.mFieldComboBox.currentField())

            settingsStr += '\n    {:20}\t{}'.format('Resample pixel size: ', self.dsbPixelSize.value())

            settingsStr += '\n    {:30}\t{}'.format('Output Coordinate System:', self.lblOutCRS.text())
            settingsStr += '\n    {:30}\t{}\n'.format('Output Folder:', self.lneOutputFolder.text())

            LOGGER.info(settingsStr)

            lyrRaster = self.mcboRasterLayer.currentLayer()

            if self.chkUsePoly.isChecked():
                lyrBoundary = self.mcboPolygonLayer.currentLayer()

                if self.chkUseSelected.isChecked():
                    savePlyName = lyrBoundary.name() + '_poly.shp'
                    filePoly = os.path.join(TEMPDIR, savePlyName)
                    if os.path.exists(filePoly):  removeFileFromQGIS(filePoly)

                    QgsVectorFileWriter.writeAsVectorFormat(lyrBoundary, filePoly, "utf-8", lyrBoundary.crs(),
                                                            "ESRI Shapefile", onlySelected=True)

                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoly, layer_name=os.path.splitext(os.path.basename(filePoly))[0]
                                            , group_layer_name='DEBUG', atTop=True)
                else:
                    filePoly = lyrBoundary.source()

            band_num = [int(self.cboBand.currentText().replace('Band ', ''))]
            files = resample_bands_to_block(lyrRaster.source(),
                                            self.dsbPixelSize.value(),
                                            self.lneOutputFolder.text(),
                                            band_nums=band_num,
                                            image_epsg=int(lyrRaster.crs().authid().replace('EPSG:', '')),
                                            image_nodata=self.spnNoDataVal.value(),
                                            polygon_shapefile=filePoly if self.chkUsePoly.isChecked() else None,
                                            groupby=self.mFieldComboBox.currentField() if self.mFieldComboBox.currentField() else None,
                                            out_epsg=int(self.outQgsCRS.authid().replace('EPSG:', '')))

            if self.chkAddToDisplay.isChecked():
                for ea_file in files:
                    removeFileFromQGIS(ea_file)
                    addRasterFileToQGIS(ea_file, group_layer_name=os.path.basename(os.path.dirname(ea_file)),
                                        atTop=False)

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QtGui.qApp.restoreOverrideCursor()
            return super(ResampleImageToBlockDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
