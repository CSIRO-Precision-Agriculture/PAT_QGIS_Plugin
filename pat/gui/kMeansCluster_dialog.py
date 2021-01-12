# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  KMeansClusterDialog -  Extract statistics from a list of rasters at set locations.
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
from builtins import str
from builtins import range
import datetime
import logging
import os
import re
import sys
import time
import traceback

import rasterio
from pyprecag.convert import numeric_pixelsize_to_string
from pyprecag import processing, crs as pyprecag_crs
from pyprecag import raster_ops, config, processing, describe

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import (save_as_dialog, file_in_use, removeFileFromQGIS, addRasterFileToQGIS, addVectorFileToQGIS,
                               build_layer_table, get_pixel_size)
from util.qgis_symbology import raster_apply_unique_value_renderer, RASTER_SYMBOLOGY
from util.settings import read_setting, write_setting

from qgis.PyQt import QtGui, uic, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QTableWidgetItem, QPushButton, QDialog, QApplication

from qgis.core import QgsProject, QgsMapLayer, QgsMessageLog, QgsUnitTypes, QgsApplication, Qgis, QgsMapLayerProxyModel
from qgis.gui import QgsMessageBar
FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'kMeansCluster_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class KMeansClusterDialog(QDialog, FORM_CLASS):
    # The key used for saving settings for this dialog
    toolKey = 'KMeansClusterDialog'

    def __init__(self, iface, parent=None):

        super(KMeansClusterDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()
        self.layers_df = None
        self.pixel_size = ['0', '', '']

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

        # GUI Runtime Customisation -----------------------------------------------
        self.mcboRasterLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.mcboRasterLayer.setExcludedProviders(['wms'])
        # self.setMapLayers()

        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_kMeansCluster.svg'))

        self.tabList.setColumnCount(2)
        self.tabList.setHorizontalHeaderItem(0, QTableWidgetItem("ID"))
        self.tabList.setHorizontalHeaderItem(1, QTableWidgetItem("0 Raster(s)"))

        self.tabList.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.tabList.hideColumn(0)  # don't need to display the unique layer ID

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
        """ Run through all loaded layers to find ones which should be excluded. """
        if self.mcboRasterLayer.count() == 0:
            return

        if self.tabList.rowCount() == 0:
            # reset to show all pixel sizes.
            self.mcboRasterLayer.setExceptedLayerList([])
            self.pixel_size = ['0','m','']
        else:
            if self.layers_df is None:
                self.layers_df = build_layer_table()

            self.mcboRasterLayer.setExceptedLayerList([])
            used_layers = [self.tabList.item(row, 0).text() for row in range(0, self.tabList.rowCount())]
            df_used = self.layers_df[self.layers_df['layer_id'].isin(used_layers)]

            df_sub = self.layers_df[(self.layers_df['provider'] == 'gdal') & (self.layers_df['layer_type'] == 'RasterLayer')]

            # Find layers that don't overlap, have a different pixel size or have already been added (via list of layer id's).
            df_sub = df_sub[((df_sub['layer_id'].isin(used_layers)) | (df_sub['pixel_size'] != self.pixel_size[0])) |
                            (~df_sub.intersects(df_used.unary_union))]

            if len(df_sub['layer'].tolist()) > 0:
                self.mcboRasterLayer.setExceptedLayerList(df_sub['layer'].tolist())

            # withdrawn coordinate system check as correctly definied in QGIS 2 as GDA94 / MGA zone 54
            # get interpreted in QGIS 3 as CRS: BOUNDCRS[SOURCECRS[PROJCRS["GDA94 / MGA zone 54",BASEGEOGCRS["GDA94",DATUM["Geocentric Datum of Australia 1994",ELLIPSOID["GRS 1980"
        
        self.tabList.horizontalHeader().setStyleSheet('color:black')
        if self.tabList.rowCount()==0:
            self.tabList.setHorizontalHeaderItem(1, QTableWidgetItem("{} Raster(s)".format(self.tabList.rowCount())))
        else:
            self.tabList.setHorizontalHeaderItem(1, QTableWidgetItem(
                "{} Raster(s) with {}{} pixels".format(self.tabList.rowCount(), *self.pixel_size[:2])))

        if self.mcboRasterLayer.currentIndex() > 0:
            self.mcboRasterLayer.setCurrentIndex(self.mcboRasterLayer.currentIndex() - 1)
        else:
            self.mcboRasterLayer.setCurrentIndex(0)

    @QtCore.pyqtSlot(name='on_cmdAdd_clicked')
    def on_cmdAdd_clicked(self):
        if self.mcboRasterLayer.currentLayer() is None:
            self.cmdAdd.setStyleSheet('color:red')
            self.tabList.horizontalHeader().setStyleSheet('color:red')
            self.lblRasterLayer.setStyleSheet('color:red')
            self.send_to_messagebar('No raster layers to process. Please add a RASTER layer into QGIS',
                                    level=Qgis.Warning, duration=5)
            return

        rowPosition = self.tabList.rowCount()
        self.tabList.insertRow(rowPosition)

        ## Save the id of the layer to a column used to get a layer object later on.
        self.tabList.setItem(rowPosition, 0, QtWidgets.QTableWidgetItem(self.mcboRasterLayer.currentLayer().id()))
        self.tabList.setItem(rowPosition, 1, QtWidgets.QTableWidgetItem(self.mcboRasterLayer.currentLayer().name()))

        if rowPosition == 0:
            self.pixel_size = get_pixel_size(self.mcboRasterLayer.currentLayer())

        # remove layer from pick list.
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
        self.setMapLayers()

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

    @QtCore.pyqtSlot(name='on_cmdSaveFile_clicked')
    def on_cmdSaveFile_clicked(self):
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        # get first layer in the list
        str_pixel_size = numeric_pixelsize_to_string(float(self.pixel_size[0]))
        filename = 'k-means_{}clusters_{}rasters_{}'.format(self.spnClusters.value(), self.tabList.rowCount(),  str_pixel_size)

        # replace more than one instance of underscore with a single one.
        # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
        filename = re.sub(r"_+", "_", filename)

        s = save_as_dialog(self, self.tr("Save As"),
                         self.tr("Tiff") + " (*.tif);;",
                         default_name=os.path.join(lastFolder, filename + '.tif'))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lneSaveFile.setText(s)

        if file_in_use(s):
            self.lneSaveFile.setStyleSheet('color:red')
            self.lblSaveFile.setStyleSheet('color:red')
        else:
            self.lblSaveFile.setStyleSheet('color:black')
            self.lneSaveFile.setStyleSheet('color:black')
            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []

            if self.tabList.rowCount() > 0:
                self.cmdAdd.setStyleSheet('color:black')
                self.tabList.horizontalHeader().setStyleSheet('color:black')
                self.lblRasterLayer.setStyleSheet('color:black')

            elif self.mcboRasterLayer.currentLayer() is None or self.tabList.rowCount() == 0:
                self.cmdAdd.setStyleSheet('color:red')
                self.tabList.horizontalHeader().setStyleSheet('color:red')
                self.lblRasterLayer.setStyleSheet('color:red')

                if self.tabList.rowCount() < 2:
                    errorList.append(self.tr('Please add at least TWO raster to analyse'))
                else:
                    errorList.append(self.tr('No raster layers to process. Please add a RASTER layer into QGIS'))

            if self.lneSaveFile.text() == '':
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Please enter an output filename"))
            elif not os.path.exists(os.path.dirname(self.lneSaveFile.text())):
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output folder does not exist."))
            elif os.path.exists(self.lneSaveFile.text()) and file_in_use(self.lneSaveFile.text(), False):
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output file {} is open in QGIS or another application".format(
                    os.path.basename(self.lneSaveFile.text()))))
            else:
                self.lneSaveFile.setStyleSheet('color:black')
                self.lblSaveFile.setStyleSheet('color:black')

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
        try:
            if not self.validate():
                return False

            # disable form via a frame, this will still allow interaction with the message bar
            self.fraMain.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)

            # Change cursor to Wait cursor
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait.. QGIS will be locked... See log panel for progress.",
                                    level=Qgis.Warning,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            registry = QgsProject.instance()
            rasterSource = [registry.mapLayer(self.tabList.item(row, 0).text()).source() for row in
                            range(0, self.tabList.rowCount())]

            rasterLyrNames = [registry.mapLayer(self.tabList.item(row, 0).text()).name() for row in
                              range(0, self.tabList.rowCount())]

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'

            if len(rasterSource) == 1:
                settingsStr += '\n    {:20}\t{}'.format('Rasters: ', rasterLyrNames[0])
            else:
                settingsStr += '\n    {:20}\t{}'.format('Rasters: ', len(rasterLyrNames))
                settingsStr += '\n\t\t' + '\n\t\t'.join(rasterLyrNames)

            settingsStr += '\n    {:20}\t{}'.format('Number of Clusters ', self.spnClusters.value())
            settingsStr += '\n    {:20}\t{}\n'.format('Output TIFF File:', self.lneSaveFile.text())

            LOGGER.info(settingsStr)
            _ = processing.kmeans_clustering(rasterSource, self.lneSaveFile.text(), self.spnClusters.value())
            csv_file = self.lneSaveFile.text().replace('.tif', '_statistics.csv')
            vect_layer = addVectorFileToQGIS(csv_file, os.path.basename(csv_file), atTop=True)

            raster_sym = RASTER_SYMBOLOGY['Zones']
            raster_layer = addRasterFileToQGIS(self.lneSaveFile.text(), atTop=False)
            raster_apply_unique_value_renderer(raster_layer,1,
                                               color_ramp=raster_sym['colour_ramp'],
                                               invert=raster_sym['invert'])
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QApplication.restoreOverrideCursor()

            return super(KMeansClusterDialog, self).accept(*args, **kwargs)

        except Exception as err:
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)
            err_mess = str(err)
            exc_info = sys.exc_info()

            if isinstance(err, IOError) and err.filename == self.lneSaveFile.text():
                err_mess = 'Output File in Use - IOError {} '.format(err.strerror)
                exc_info = None

            self.send_to_messagebar(err_mess, level=Qgis.Critical, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=exc_info)
            QApplication.restoreOverrideCursor()
            return False  # leave dialog open
