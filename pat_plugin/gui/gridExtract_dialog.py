# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  GridExtractDialog -  Extract statistics from a list of rasters at set locations.
           -------------------
        begin      : 2018-06-12
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
import datetime
import logging
import os
import re
import sys
import time
import traceback

import numpy as np
from pat_plugin import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from pat_plugin.util.custom_logging import errorCatcher, openLogPanel
from pat_plugin.util.qgis_common import saveAsDialog, file_in_use
from pat_plugin.util.settings import read_setting, write_setting
from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QTableWidgetItem, QPushButton
from pyprecag import raster_ops, config, processing, describe
from qgis.core import QgsMapLayerRegistry, QgsMapLayer, QgsMessageLog, QgsVectorFileWriter, QgsUnitTypes
from qgis.gui import QgsMessageBar

from util.qgis_common import removeFileFromQGIS, copyLayerToMemory, addVectorFileToQGIS

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'gridextract_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class GridExtractDialog(QtGui.QDialog, FORM_CLASS):
    # The key used for saving settings for this dialog
    toolKey = 'GridExtractDialog'

    def __init__(self, iface, parent=None):

        super(GridExtractDialog, self).__init__(parent)

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

        if isinstance(self.layout(), QtGui.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # GUI Runtime Customisation -----------------------------------------------
        self.chkgrpStatistics.setExclusive(False)
        self.tabList.setColumnCount(2)
        self.tabList.setHorizontalHeaderItem(0, QTableWidgetItem("ID"))
        self.tabList.setHorizontalHeaderItem(1, QTableWidgetItem("0 Raster(s)"))
        self.tabList.horizontalHeader().setResizeMode(QtGui.QHeaderView.Stretch)
        self.tabList.hideColumn(0)  # don't need to display the unique layer ID
        self.pixel_size = 0
        self.lblPixelFilter.setText(
            'Only process rasters with one pixel size. Adding the first raster layer will set this pixel size')
        self.statsMapping = {'mean': np.nanmean,
                             'minimum': np.nanmin,
                             'maximum': np.nanmax,
                             'standard deviation': np.nanstd,
                             'coefficient of variation': raster_ops.nancv,
                             'pixel count': raster_ops.pixelcount,
                             }

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

        # self.cleanMessageBars(AllBars=False)
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
            # Only Load Raster layers with matching pixel size
            if layer.type() != QgsMapLayer.RasterLayer:
                continue

            if layer.crs().geographicFlag():
                ft = 'f'
            else:
                ft = 'g'

            lyrPixelSize = format(layer.rasterUnitsPerPixelX(), ft)
            if float(self.pixel_size) > 0 and lyrPixelSize != self.pixel_size:
                exlayer_list.append(layer)
                continue

            # if layer is already in the table list the exclude it from the pick list to avoid duplicates.
            for row in range(0, self.tabList.rowCount()):
                if layer.id() == self.tabList.item(row, 0).text():
                    exlayer_list.append(layer)
                    continue

        self.tabList.horizontalHeader().setStyleSheet('color:black')
        self.tabList.setHorizontalHeaderItem(1, QTableWidgetItem("{} Raster(s)".format(self.tabList.rowCount())))

        self.mcboRasterLayer.setExceptedLayerList(exlayer_list)
        if self.mcboRasterLayer.currentIndex() > 0:
            self.mcboRasterLayer.setCurrentIndex(self.mcboRasterLayer.currentIndex() - 1)
        else:
            self.mcboRasterLayer.setCurrentIndex(0)

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        if self.mcboPointsLayer.count() == 0:
            return

        lyrTarget = self.mcboPointsLayer.currentLayer()

        if len(lyrTarget.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(len(lyrTarget.selectedFeatures())))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def on_mcboPointsLayer_layerChanged(self):
        self.updateUseSelected()

    @QtCore.pyqtSlot(name='on_cmdAdd_clicked')
    def on_cmdAdd_clicked(self):
        if self.mcboRasterLayer.currentLayer() is None:
            self.cmdAdd.setStyleSheet('color:red')
            self.tabList.horizontalHeader().setStyleSheet('color:red')
            self.lblRasterLayer.setStyleSheet('color:red')
            self.send_to_messagebar('No raster layers to process. Please add a RASTER layer into QGIS',
                                    level=QgsMessageBar.WARNING, duration=5)
            return

        rowPosition = self.tabList.rowCount()
        self.tabList.insertRow(rowPosition)

        ## Save the id of the layer to a column used to get a layer object later on.
        ## adapted from https://gis.stackexchange.com/questions/165415/activating-layer-by-its-name-in-pyqgis
        self.tabList.setItem(rowPosition, 0, QtGui.QTableWidgetItem(self.mcboRasterLayer.currentLayer().id()))
        self.tabList.setItem(rowPosition, 1, QtGui.QTableWidgetItem(self.mcboRasterLayer.currentLayer().name()))

        if rowPosition == 0:
            # get the pixel units from the coordinate systems as a string  ie degrees, metres etc.
            # for QGIS 3  see the following functions 
            # .toAbbreviatedString()      https://www.qgis.org/api/classQgsUnitTypes.html#a7d09b9df11b6dcc2fe29928f5de296a4
            # and /or DistanceValue       https://www.qgis.org/api/structQgsUnitTypes_1_1DistanceValue.html

            pixel_units = QgsUnitTypes.encodeUnit(self.mcboRasterLayer.currentLayer().crs().mapUnits())

            # Adjust for Aust/UK spelling
            pixel_units = pixel_units.replace('meters', 'metres')

            if self.mcboRasterLayer.currentLayer().crs().geographicFlag():
                ft = 'f'  # this will convert 1.99348e-05 to 0.000020
            else:
                ft = 'g'  # this will convert 2.0 to 2 or 0.5, '0.5'

            self.pixel_size = format(self.mcboRasterLayer.currentLayer().rasterUnitsPerPixelX(), ft)
            self.lblPixelFilter.setText(
                'Only allow processing of rasters with a pixel size of {} {}'.format(self.pixel_size, pixel_units))

            if not self.mcboRasterLayer.currentLayer().crs().geographicFlag():
                for obj in [self.opt3x3, self.opt5x5, self.opt7x7, self.opt9x9]:
                    pixel_len = format(float(self.pixel_size) * float(obj.text()[0]), ft)
                    obj.setText('{0} ({1}x{1}{2})'.format(obj.text(), pixel_len, pixel_units[0]))

        # remove layer from picklist.
        self.setMapLayers()

        self.lblRasterLayer.setStyleSheet('color:black')
        self.cmdAdd.setStyleSheet('color:black')

        self.cmdAdd.setEnabled(len(self.mcboRasterLayer) > 0)
        self.cmdDel.setEnabled(self.tabList.rowCount() > 0)
        self.cmdDown.setEnabled(self.tabList.rowCount() > 1)
        self.cmdUp.setEnabled(self.tabList.rowCount() > 1)

    @QtCore.pyqtSlot(name='on_cmdDel_clicked')
    def on_cmdDel_clicked(self):
        self.tabList.removeRow(self.tabList.currentRow())

        if self.tabList.rowCount() == 0:
            # reset to show all pixel sizes.
            self.mcboRasterLayer.setExceptedLayerList([])
            self.pixel_size = 0
            self.lblPixelFilter.setText(
                'Only process rasters with one pixel size. Adding the first raster layer will set this pixel size')

            for obj in [self.opt3x3, self.opt5x5, self.opt7x7, self.opt9x9]:
                obj.setText('{0}'.format(obj.text()[:3]))

        self.setMapLayers()
        self.cmdAdd.setEnabled(len(self.mcboRasterLayer) > 0)
        self.cmdDel.setEnabled(self.tabList.rowCount() > 0)
        self.cmdDown.setEnabled(self.tabList.rowCount() > 1)
        self.cmdUp.setEnabled(self.tabList.rowCount() > 1)

    @QtCore.pyqtSlot(name='on_cmdDown_clicked')
    def on_cmdDown_clicked(self):
        row = self.tabList.currentRow()
        column = self.tabList.currentColumn()
        if row < self.tabList.rowCount() - 1:
            self.tabList.insertRow(row + 2)
            for i in range(self.tabList.columnCount()):
                self.tabList.setItem(row + 2, i, self.tabList.takeItem(row, i))
                self.tabList.setCurrentCell(row + 2, column)
            self.tabList.removeRow(row)

    @QtCore.pyqtSlot(name='on_cmdUp_clicked')
    def on_cmdUp_clicked(self):
        row = self.tabList.currentRow()
        column = self.tabList.currentColumn()
        if row > 0:
            self.tabList.insertRow(row - 1)
            for i in range(self.tabList.columnCount()):
                self.tabList.setItem(row - 1, i, self.tabList.takeItem(row + 1, i))
                self.tabList.setCurrentCell(row - 1, column)
            self.tabList.removeRow(row + 1)

    @QtCore.pyqtSlot(name='on_cmdSaveCSVFile_clicked')
    def on_cmdSaveCSVFile_clicked(self):
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        lyrTarget = self.mcboPointsLayer.currentLayer()
        filename = os.path.splitext(lyrTarget.name())[0] + '_pixelvals.csv'

        # replace more than one instance of underscore with a single one.
        # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
        filename = re.sub(r"_+", "_", filename)

        s = saveAsDialog(self, self.tr("Save As"),
                         self.tr("Comma Delimited") + " (*.csv);;",
                         defaultName=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lneSaveCSVFile.setText(s)

        if file_in_use(s):
            self.lneSaveCSVFile.setStyleSheet('color:red')
            self.lblSaveCSVFile.setStyleSheet('color:red')
        else:
            self.lblSaveCSVFile.setStyleSheet('color:black')
            self.lneSaveCSVFile.setStyleSheet('color:black')
            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []
            pointsLayer = self.mcboPointsLayer.currentLayer()
            if pointsLayer is None or self.mcboPointsLayer.currentText() == '':
                self.lblPointsLayer.setStyleSheet('color:red')
                errorList.append(self.tr('No points layers to process. Please load a POINTS layer into QGIS'))
            else:
                self.lblPointsLayer.setStyleSheet('color:black')

            if self.tabList.rowCount() > 0:
                self.cmdAdd.setStyleSheet('color:black')
                self.tabList.horizontalHeader().setStyleSheet('color:black')
                self.lblRasterLayer.setStyleSheet('color:black')

            elif self.mcboRasterLayer.currentLayer() is None or self.tabList.rowCount() == 0:
                self.cmdAdd.setStyleSheet('color:red')
                self.tabList.horizontalHeader().setStyleSheet('color:red')
                self.lblRasterLayer.setStyleSheet('color:red')

                if self.tabList.rowCount() == 0:
                    errorList.append(self.tr('Please add at least ONE raster to analyse'))
                else:
                    errorList.append(self.tr('No raster layers to process. Please add a RASTER layer into QGIS'))

            # check if any statistics are selected. All are children of the qframe
            chkbox_list = self.fraStatistics.findChildren(QtGui.QCheckBox)
            if any(x.isChecked() for x in chkbox_list):
                self.lblCalcStats.setStyleSheet('color:black')
            else:
                self.lblCalcStats.setStyleSheet('color:red')
                errorList.append(self.tr("Please check a statistic to calculate."))

            if self.lneSaveCSVFile.text() == '':
                self.lneSaveCSVFile.setStyleSheet('color:red')
                self.lblSaveCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Please enter an output csv filename"))
            elif not os.path.exists(os.path.dirname(self.lneSaveCSVFile.text())):
                self.lneSaveCSVFile.setStyleSheet('color:red')
                self.lblSaveCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output folder does not exist."))
            elif os.path.exists(self.lneSaveCSVFile.text()) and file_in_use(self.lneSaveCSVFile.text(), False):
                self.lneSaveCSVFile.setStyleSheet('color:red')
                self.lblSaveCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output file {} is open in QGIS or another application".format(
                    os.path.basename(self.lneSaveCSVFile.text()))))
            else:
                self.lneSaveCSVFile.setStyleSheet('color:black')
                self.lblSaveCSVFile.setStyleSheet('color:black')

            # if self.mcboPointsLayer.currentLayer().providerType() == 'delimitedtext':
            #     url = urlparse(self.mcboPointsLayer.currentLayer().source())
            #
            #     if os.path.normpath(url.path.strip('/')).upper() == os.path.normpath(self.lneSaveCSVFile.text()).upper():
            #         self.lneSaveCSVFile.setStyleSheet('color:red')
            #         errorList.append(self.tr("Output file in use as the input points layer"))

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

            registry = QgsMapLayerRegistry.instance()
            rasterSource = [registry.mapLayer(self.tabList.item(row, 0).text()).source() for row in
                            range(0, self.tabList.rowCount())]
            rasterLyrNames = [registry.mapLayer(self.tabList.item(row, 0).text()).name() for row in
                              range(0, self.tabList.rowCount())]
            selectedStats = [x.text() for x in self.chkgrpStatistics.buttons() if x.isChecked()]
            statsFunctions = [self.statsMapping[x.lower()] for x in selectedStats]

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            if self.chkUseSelected.isChecked():
                settingsStr += '\n    {:20}\t{} with {} selected features'.format('Layer:',
                                                                                  self.mcboPointsLayer.currentLayer().name(),
                                                                                  len(
                                                                                      self.mcboPointsLayer.currentLayer().selectedFeatures()))
            else:
                settingsStr += '\n    {:20}\t{}'.format('Layer:', self.mcboPointsLayer.currentLayer().name())

            if len(rasterSource) == 1:
                settingsStr += '\n    {:20}\t{}'.format('Rasters: ', rasterLyrNames[0])
            else:
                settingsStr += '\n    {:20}\t{}'.format('Rasters: ', len(rasterLyrNames))
                settingsStr += '\n\t\t' + '\n\t\t'.join(rasterLyrNames)

            settingsStr += '\n    {:20}\t{}'.format('Use Current Pixel Value: ', self.chkCurrentVal.isChecked())
            settingsStr += '\n    {:20}\t{}'.format('Neighbourhood Size: ',
                                                    self.btgrpSize.checkedButton().text().replace('\n', ''))
            settingsStr += '\n    {:20}\t{}'.format('Statistics: ', ', '.join(selectedStats))
            settingsStr += '\n    {:20}\t{}\n'.format('Output CSV File:', self.lneSaveCSVFile.text())

            LOGGER.info(settingsStr)

            layerPts = self.mcboPointsLayer.currentLayer()
            stepTime = time.time()
            if layerPts.providerType() == 'delimitedtext' or os.path.splitext(layerPts.source())[-1] == '.vrt' or \
                    self.chkUseSelected.isChecked():

                filePoints = os.path.join(TEMPDIR, "{}_GEpoints.shp".format(layerPts.name()))

                if self.chkUseSelected.isChecked():
                    filePoints = os.path.join(TEMPDIR, "{}_selected_GEpoints.shp".format(layerPts.name()))

                if os.path.exists(filePoints):
                    removeFileFromQGIS(filePoints)

                ptsMemLayer = copyLayerToMemory(layerPts, layerPts.name() + "_memory", bAddUFI=True,
                                                bOnlySelectedFeat=self.chkUseSelected.isChecked())

                _writer = QgsVectorFileWriter.writeAsVectorFormat(ptsMemLayer, filePoints, "utf-8", layerPts.crs(),
                                                                  "ESRI Shapefile")
                LOGGER.info('{:<30} {:<15} {}'.format('Save layer/selection to file',
                                                      datetime.timedelta(seconds=time.time() - stepTime), filePoints))
                stepTime = time.time()

                # reset field to match truncated field in the saved shapefile.
                del ptsMemLayer, _writer

                if self.DISP_TEMP_LAYERS:
                    addVectorFileToQGIS(filePoints, group_layer_name='DEBUG', atTop=True)

            else:
                filePoints = layerPts.source()

            ptsDesc = describe.VectorDescribe(filePoints)
            gdfPoints = ptsDesc.open_geo_dataframe()

            # assign a coordinate system if required based on the layer crs.
            if ptsDesc.crs.srs is None:
                ptsDesc.crs.getFromEPSG(layerPts.crs().authid())
                gdfPoints.crs = ptsDesc.crs.epsg

            sizeList = []
            if self.chkCurrentVal.isChecked():
                sizeList = [1]
            sizeList.append(int(self.btgrpSize.checkedButton().text()[0]))

            _ = processing.extract_pixel_statistics_for_points(gdfPoints, ptsDesc.crs, rasterSource,
                                                               function_list=statsFunctions, size_list=sizeList,
                                                               output_csvfile=self.lneSaveCSVFile.text())

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QtGui.qApp.restoreOverrideCursor()
            return super(GridExtractDialog, self).accept(*args, **kwargs)


        except Exception as err:
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)
            err_mess = str(err)
            exc_info = sys.exc_info()

            if isinstance(err, IOError) and err.filename == self.lneSaveCSVFile.text():
                err_mess = 'Output CSV File in Use - IOError {} '.format(err.strerror)
                exc_info = None

            self.send_to_messagebar(err_mess, level=QgsMessageBar.CRITICAL, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=exc_info)
            QtGui.qApp.restoreOverrideCursor()
            return False  # leave dialog open
