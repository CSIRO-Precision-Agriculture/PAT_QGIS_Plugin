# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  tTestAnalysis - Run a t-test analysis for strip trials
           -------------------
        begin      : 2019-05-20
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
import sys
import traceback

import geopandas as gpd
import pandas as pd
from shapely import wkt
import rasterio
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel

from util.qgis_common import (save_as_dialog, file_in_use, removeFileFromQGIS, get_layer_source,
                              copyLayerToMemory, addVectorFileToQGIS, addRasterFileToQGIS, check_for_overlap,
                              build_layer_table, get_pixel_size)

from util.settings import read_setting, write_setting

from pyprecag import config, crs, describe
from pyprecag.processing import ttest_analysis

from qgis.PyQt import QtGui, uic, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QPushButton, QDialog, QFileDialog, QApplication

from qgis.core import (QgsMapLayer, QgsMessageLog, QgsVectorFileWriter,
                       QgsCoordinateReferenceSystem, QgsUnitTypes, QgsApplication, QgsMapLayerProxyModel, Qgis,
                       QgsCoordinateTransform, QgsProject)

from qgis.gui import QgsMessageBar

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__),
                                            'tTestAnalysis_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())


class tTestAnalysisDialog(QDialog, FORM_CLASS):
    """Extract statistics from a list of rasters at set locations."""
    toolKey = 'tTestAnalysisDialog'

    def __init__(self, iface, parent=None):

        super(tTestAnalysisDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtWidgets.QFormLayout(self)  # new layout to gui

        self.raster_filter_message = self.lblLayerFilter.text()
        self.pixel_size = ['0', 'm', '']
        self.layer_table = build_layer_table()

        if isinstance(self.layout(), (QtWidgets.QFormLayout, QtWidgets.QGridLayout)):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            # for use with Vertical/horizontal layout box
            self.layout().insertWidget(0, self.messageBar)

        for cbo in [self.mcboRasterLayer, self.mcboCtrlRasterLayer, self.mcboZoneRasterLyr]:
            cbo.setFilters(QgsMapLayerProxyModel.RasterLayer)
            cbo.setExcludedProviders(['wms'])
            cbo.setAllowEmptyLayer(True)
            cbo.setCurrentIndex(0)

        self.mcboPointsLayer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.mcboPointsLayer.setExcludedProviders(['wms'])
        self.mcboPointsLayer.setAllowEmptyLayer(True)
        self.mcboPointsLayer.setCurrentIndex(0)

        self.setMapLayers()
        self.updateUseSelected()

        # GUI Runtime Customisation -----------------------------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_t-test.svg'))

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including those which haven't timed-out. Default - True
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
            """check out C:\data\GIS_Tools\Reference_Code\QGIS_Reference_Plugins\QGIS-master\python\plugins\db_manager\db_tree.py
            to try and hyperlink"""

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
        """ Run through all loaded layers to find ones which should be excluded.
            In this case exclude services."""

        if len(self.layer_table) == 0:
            return

        cbo_list = [self.mcboRasterLayer, self.mcboCtrlRasterLayer, self.mcboZoneRasterLyr]

        if self.mcboPointsLayer.currentLayer() is None:
            for cbo in cbo_list:
                cbo.setExceptedLayerList([])
            return

        df_pts = self.layer_table[self.layer_table['layer_id'] == self.mcboPointsLayer.currentLayer().id()]

        used_layers = [cbo.currentLayer().id() for cbo in cbo_list if cbo.currentLayer() is not None]

        df_rastlyrs = self.layer_table[
            (self.layer_table['provider'] == 'gdal') & (self.layer_table['layer_type'] == 'RasterLayer')]

        if self.chkUseSelected.isChecked():
            layer = self.mcboPointsLayer.currentLayer()

            transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem(df_pts['epsg'].values[0]),
                                               QgsProject.instance().crs(),
                                               QgsProject.instance())

            prj_ext = transform.transformBoundingBox(layer.boundingBoxOfSelected())
            df_pts['geometry'] = wkt.loads(prj_ext.asWktPolygon())

            # recreate the geodataframe or unary_union wont work
            df_pts = gpd.GeoDataFrame(df_pts, geometry='geometry', crs=df_pts.crs)

        if self.pixel_size[0] == '0':
            # Find layers that overlap.
            if len(df_pts) > 0:
                df_keep = df_rastlyrs[df_rastlyrs.intersects(df_pts.union_all())]

        else:
            # Find layers that overlap and have the same pixel size.
            if len(df_pts) > 0:
                df_keep = df_rastlyrs[
                    (df_rastlyrs['pixel_size'] == self.pixel_size[0]) & (df_rastlyrs.intersects(df_pts.union_all()))]

        # process for each raster layer cbo
        for cbo in cbo_list:
            df_cbo = df_keep.copy()

            if cbo.currentLayer() is None:
                loop_used_layers = used_layers
            else:
                loop_used_layers = [ea for ea in used_layers if cbo.currentLayer().id() != ea]

            # add it back the current one.
            df_cbo = df_cbo[~df_cbo['layer_id'].isin(loop_used_layers)]

            # find those we don't want to keep; 
            df_remove = pd.concat([df_rastlyrs, df_cbo]).drop_duplicates(keep=False)

            cbo.setExceptedLayerList(df_remove['layer'].tolist())

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        self.chkUseSelected.setChecked(False)

        if self.mcboPointsLayer.count() == 0 or self.mcboPointsLayer.currentLayer() is None:
            return

        point_lyr = self.mcboPointsLayer.currentLayer()
        if point_lyr.selectedFeatureCount() > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(point_lyr.selectedFeatureCount()))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def on_mcboRasterLayer_layerChanged(self):
        if self.mcboRasterLayer.currentLayer() is None:
            self.pixel_size = ['0', 'm', '']
            self.lblLayerFilter.setText(self.raster_filter_message)
            return

        else:
            self.pixel_size = get_pixel_size(self.mcboRasterLayer.currentLayer())
            self.lblLayerFilter.setText('Raster lists below have been <b>filtered</b> to only show rasters with <br/>'
                                        + '- a pixelsize of <b>{} {}</b><br/>'.format(self.pixel_size[0],
                                                                                      self.pixel_size[1])
                                        + '- and <b>overlaps</b> with the points layer')

        self.mcboCtrlRasterLayer.setEnabled(self.mcboCtrlRasterLayer.count() > 1)
        self.mcboZoneRasterLyr.setEnabled(self.mcboCtrlRasterLayer.count() > 1)

        self.setMapLayers()

    def on_chkUseSelected_stateChanged(self, state):
        self.setMapLayers()

    def on_mcboCtrlRasterLayer_layerChanged(self):
        self.setMapLayers()

    def on_mcboZoneRasterLyr_layerChanged(self):
        self.setMapLayers()

    def on_mcboPointsLayer_layerChanged(self):
        self.updateUseSelected()
        self.setMapLayers()

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

        s = QFileDialog.getExistingDirectory(self, self.tr(
            "Save output files to a folder. A sub-folder will be created from the image name"),
                                             outFolder, QFileDialog.ShowDirsOnly)

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

            if self.mcboPointsLayer.currentLayer() is None:
                self.lblPointsLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input points layer required."))
            else:
                self.lblPointsLayer.setStyleSheet('color:black')

            if self.mcboRasterLayer.currentLayer() is None:
                self.lblRasterLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input strips raster layer required."))
            else:
                self.lblRasterLayer.setStyleSheet('color:black')

            if self.dsbMovingWinSize.value() <= 0:
                self.lblMovingWinSize.setStyleSheet('color:red')
                errorList.append(self.tr("Pixel size must be greater than 0."))
            else:
                self.lblMovingWinSize.setStyleSheet('color:black')

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
                    self.send_to_messagebar(str(ea), level=Qgis.Warning,
                                            duration=(i + 1) * 5)
                return False

        return True

    def accept(self, *args, **kwargs):
        try:

            if not self.validate():
                return False

            # disable form via a frame, this will still allow interaction with the message bar
            # self.fraMain.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)

            # Change cursor to Wait cursor
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))

            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait. QGIS will be locked. See log panel for progress.",
                                    level=Qgis.Warning,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'

            if self.chkUseSelected.isChecked():
                settingsStr += '\n    {:20}\t{} with {} selected features'.format(
                    'Strip points layer:', self.mcboPointsLayer.currentLayer().name(),
                    self.mcboPointsLayer.currentLayer().selectedFeatureCount())
            else:
                settingsStr += '\n    {:20}\t{}'.format('Strip points layer:',
                                                        self.mcboPointsLayer.currentLayer().name())

            settingsStr += '\n    {:20}\t{}'.format('Strip values raster:',
                                                    self.mcboRasterLayer.currentLayer().name())

            control_file, zone_file = ['', '']
            if self.mcboCtrlRasterLayer.currentLayer() is not None:
                settingsStr += '\n    {:20}\t{}'.format('Control values raster:',
                                                        self.mcboCtrlRasterLayer.currentLayer().name())
                control_file = get_layer_source(self.mcboCtrlRasterLayer.currentLayer())

            if self.mcboZoneRasterLyr.currentLayer() is not None:
                settingsStr += '\n    {:20}\t{}'.format('Control values raster:',
                                                        self.mcboZoneRasterLyr.currentLayer().name())
                zone_file = get_layer_source(self.mcboZoneRasterLyr.currentLayer())

            settingsStr += '\n    {:20}\t{}'.format('Moving window size: ', self.dsbMovingWinSize.value())
            settingsStr += '\n    {:30}\t{}\n'.format('Output folder:', self.lneOutputFolder.text())

            LOGGER.info(settingsStr)

            lyrPoints = self.mcboPointsLayer.currentLayer()

            if self.chkUseSelected.isChecked() or lyrPoints.providerType() == 'delimitedtext':
                savePtsName = lyrPoints.name() + '_strippts.shp'
                fileStripPts = os.path.join(TEMPDIR, savePtsName)

                if os.path.exists(fileStripPts):
                    removeFileFromQGIS(fileStripPts)

                QgsVectorFileWriter.writeAsVectorFormat(lyrPoints, fileStripPts, "utf-8",
                                                        lyrPoints.crs(), driverName="ESRI Shapefile",
                                                        onlySelected=self.chkUseSelected.isChecked())

                if self.DISP_TEMP_LAYERS:
                    addVectorFileToQGIS(fileStripPts, layer_name=os.path.splitext(os.path.basename(fileStripPts))[0],
                                        group_layer_name='DEBUG', atTop=True)
            else:
                fileStripPts = get_layer_source(lyrPoints)

            points_desc = describe.VectorDescribe(fileStripPts)
            gdf_pts = points_desc.open_geo_dataframe()

            df_table = ttest_analysis(gdf_pts, points_desc.crs,
                                      get_layer_source(self.mcboRasterLayer.currentLayer()),
                                      self.lneOutputFolder.text(),
                                      zone_file, control_file,
                                      size=self.dsbMovingWinSize.value())

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()

            QApplication.restoreOverrideCursor()
            return super(tTestAnalysisDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=Qgis.Critical,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
