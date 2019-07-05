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

import logging
import os
import sys
import traceback

import geopandas as gpd
from shapely import wkt
import rasterio
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel

from util.qgis_common import (save_as_dialog, file_in_use, removeFileFromQGIS,
    copyLayerToMemory, addVectorFileToQGIS, addRasterFileToQGIS, check_for_overlap,
    build_layer_table, get_pixel_size)

from util.settings import read_setting, write_setting

from pyprecag import config, crs, describe
from pyprecag.processing import ttest_analysis

from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QPushButton

from qgis.core import (QgsMapLayer, QgsMessageLog, QgsVectorFileWriter,
                       QgsCoordinateReferenceSystem, QgsUnitTypes)

from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__),
                                            'tTestAnalysis_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())


class tTestAnalysisDialog(QtGui.QDialog, FORM_CLASS):
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
            # for use with Vertical/horizontal layout box
            self.layout().insertWidget(0, self.messageBar)

        self.pixel_size = [0, '']
        self.layer_table = build_layer_table()
        self.exclude_map_layers()
        self.updateUseSelected()

        self.raster_filter_message = self.lblLayerFilter.text()

        # GUI Runtime Customisation -----------------------------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_t-test.svg'))

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including those which haven't timed-out. Default - True
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

    def send_to_messagebar(self, message, title='', level=QgsMessageBar.INFO, duration=5,
                           exc_info=None, core_QGIS=False, addToLog=False, showLogPanel=False):

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

    def exclude_map_layers(self):
        """ Run through all loaded layers to find ones which should be excluded.
            In this case exclude services."""
        
        if len(self.layer_table) == 0:
            return
        
        if self.mcboPointsLayer.currentLayer() is None:
            return
        
        if self.mcboCtrlRasterLayer.currentLayer() is None:
            return
        
        # df = self.layer_table[self.layer_table['layer_type']==QgsMapLayer.VectorLayer]
        # df = df[df['is_projected']==True]
        # self.mcboPointsLayer.setExceptedLayerList(self.create_excluded_list(df)['layer'])

        old_exRLayer_ids = []
        if self.mcboCtrlRasterLayer.count() > 0:
            old_exRLayer_ids = [ea_lyr.id() for ea_lyr in self.mcboCtrlRasterLayer.exceptedLayerList()]

        df = self.layer_table[self.layer_table['layer_type'] == QgsMapLayer.RasterLayer]

        # check for coordinate system
        pts_layer = self.mcboPointsLayer.currentLayer()
        df = df[df['epsg'] == pts_layer.crs().authid()].copy()

        # check for overlap with points
        df['overlap'] = df['extent'].apply(lambda x :
                                           check_for_overlap(pts_layer.extent().asWktPolygon(), x))
        df = df[df['overlap'] == True]

        rasterLayerExcl = self.create_excluded_list(df)

        self.mcboRasterLayer.setExceptedLayerList(rasterLayerExcl['layer'])
        # the above line changed the mcbo list with out triggering an event so update the pixel size.
        pix = get_pixel_size(self.mcboRasterLayer.currentLayer())
        self.pixel_size = pix

        if self.pixel_size[0] > 0:
            df = df[df['pixel_size'] == self.pixel_size[0] ]
            rasterLayerExcl = self.create_excluded_list(df)

        if len(rasterLayerExcl) > 0 and old_exRLayer_ids != rasterLayerExcl['id']:
            self.mcboCtrlRasterLayer.setExceptedLayerList(rasterLayerExcl['layer'])
            self.mcboZoneRasterLyr.setExceptedLayerList(rasterLayerExcl['layer'])
            self.chkCtrlRasterLayer.setChecked(False)
            self.chkZoneLayer.setChecked(False)

        if self.mcboRasterLayer.count() > 0:
            crs_desc = self.mcboRasterLayer.currentLayer().crs().description()
            self.lblLayerFilter.setText('Raster lists below have been <b>filtered</b> to only show rasters with'
                                        +'<br>    - a pixelsize of <b>{} {}</b>'.format(pix[0], pix[1])
                                        +'<br>    - a coordinate system of <b>{}</b>'.format(crs_desc)
                                        +'<br>    - and <b>overlaps</b> with the points layer')

        self.mcboCtrlRasterLayer.setEnabled(self.mcboCtrlRasterLayer.count() > 1)
        self.mcboZoneRasterLyr.setEnabled(self.mcboCtrlRasterLayer.count() > 1)

        self.chkCtrlRasterLayer.setEnabled(self.mcboCtrlRasterLayer.count() > 1)
        self.chkZoneLayer.setEnabled(self.mcboCtrlRasterLayer.count() > 1)

    def create_excluded_list(self, df):
        from collections import defaultdict
        exclude = defaultdict(list)

        for layer in self.iface.legendInterface().layers():
            if layer.type() not in  df['layer_type'].unique().tolist():
                continue
            if layer.id() not in df['layer_id'].unique().tolist() and layer.id() not in exclude['id']:
                exclude['layer'].append(layer)
                exclude['id'].append(layer.id())

        return exclude

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        self.chkUseSelected.setChecked(False)

        if self.mcboPointsLayer.count() == 0:
            return

        point_lyr = self.mcboPointsLayer.currentLayer()
        if len(point_lyr.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(
                len(point_lyr.selectedFeatures())))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def on_mcboRasterLayer_layerChanged(self):
        if not self.mcboRasterLayer.currentLayer() is None:
            self.pixel_size = get_pixel_size(self.mcboRasterLayer.currentLayer())
        self.exclude_map_layers()

    def on_mcboCtrlRasterLayer_layerChanged(self):
        self.chkCtrlRasterLayer.setChecked(True)

    def on_mcboZoneRasterLyr_layerChanged(self):
        # ToDo: QGIS 3 implement QgsMapLayerComboBox.allowEmptyLayer() instead of chkUsePoly checkbox
        self.chkZoneLayer.setChecked(True)

    def on_mcboPointsLayer_layerChanged(self):
        self.updateUseSelected()
        self.exclude_map_layers()

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

            if self.mcboPointsLayer.currentLayer() is None:
                self.lblPointsLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input points layer required."))
            else:
                self.lblPointsLayer.setStyleSheet('color:black')

            if self.mcboRasterLayer.currentLayer() is None:
                self.lblRasterLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input image layer required."))
            else:
                self.lblRasterLayer.setStyleSheet('color:black')

            selected_layers = []
            duplicate_raster = False

            for cbo, chk in [(self.mcboRasterLayer, None),
                           (self.mcboCtrlRasterLayer, self.chkCtrlRasterLayer),
                           (self.mcboZoneRasterLyr, self.chkZoneLayer)]:
                if not chk:
                    selected_layers.append(cbo.currentLayer().id())

                elif chk.isChecked():
                    if not cbo.currentLayer().id() in selected_layers:
                        selected_layers.append(cbo.currentLayer().id())
                        chk.setStyleSheet('color:black')

                    else:
                        chk.setStyleSheet('color:red')
                        duplicate_raster = True

            if duplicate_raster:
                errorList.append(self.tr("Input rasters can only be used once"))

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
                    self.send_to_messagebar(unicode(ea), level=QgsMessageBar.WARNING,
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
            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            self.iface.mainWindow().statusBar().showMessage(
                'Processing {}'.format(self.windowTitle()))

            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait. QGIS will be locked. See log panel for progress.",
                                    level=QgsMessageBar.WARNING,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'

            if self.chkUseSelected.isChecked():
                settingsStr += '\n    {:20}\t{} with {} selected features'.format(
                    'Strip points layer:', self.mcboPointsLayer.currentLayer().name(),
                    len(self.mcboPointsLayer.currentLayer().selectedFeatures()))
            else:
                settingsStr += '\n    {:20}\t{}'.format('Strip points layer:',
                                                        self.mcboPointsLayer.currentLayer().name())

            settingsStr += '\n    {:20}\t{}'.format('Strip values raster:',
                                                    self.mcboRasterLayer.currentLayer().name())

            control_file, zone_file = ['', '']
            if  self.chkCtrlRasterLayer.isChecked():
                settingsStr += '\n    {:20}\t{}'.format(
                    'Control values raster:', self.mcboCtrlRasterLayer.currentLayer().name())
                control_file = self.mcboCtrlRasterLayer.currentLayer().source()
            if  self.chkZoneLayer.isChecked():
                settingsStr += '\n    {:20}\t{}'.format(
                    'Control values raster:', self.mcboZoneRasterLyr.currentLayer().name())
                zone_file = self.mcboZoneRasterLyr.currentLayer().source()

            settingsStr += '\n    {:20}\t{}'.format('Moving window size: ',
                                                    self.dsbMovingWinSize.value())
            settingsStr += '\n    {:30}\t{}\n'.format('Output folder:',
                                                      self.lneOutputFolder.text())

            LOGGER.info(settingsStr)

            lyrPoints = self.mcboPointsLayer.currentLayer()
            if self.chkUseSelected.isChecked() or lyrPoints.providerType() == 'delimitedtext':
                savePtsName = lyrPoints.name() + '_strippts.shp'
                fileStripPts = os.path.join(TEMPDIR, savePtsName)
                if os.path.exists(fileStripPts):  removeFileFromQGIS(fileStripPts)

                QgsVectorFileWriter.writeAsVectorFormat(lyrPoints, fileStripPts, "utf-8",
                                                        lyrPoints.crs(), "ESRI Shapefile",
                                                        onlySelected=self.chkUseSelected.isChecked())

                if self.DISP_TEMP_LAYERS:
                    addVectorFileToQGIS(fileStripPts, layer_name=os.path.splitext(
                        os.path.basename(fileStripPts))[0], group_layer_name='DEBUG', atTop=True)
            else:
                fileStripPts = lyrPoints.source()

            points_desc = describe.VectorDescribe(fileStripPts)
            gdf_pts = points_desc.open_geo_dataframe()

            df_table = ttest_analysis(gdf_pts, points_desc.crs,
                            self.mcboRasterLayer.currentLayer().source(),
                            self.lneOutputFolder.text(),
                            zone_file, control_file,
                            size=self.dsbMovingWinSize.value())

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()

            QtGui.qApp.restoreOverrideCursor()
            return super(tTestAnalysisDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
