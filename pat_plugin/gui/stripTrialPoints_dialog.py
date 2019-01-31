# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  StripTrialPointsDialog  - Create points along and at an offset to a line. 
           -------------------
        begin      : 2019-01-29
        git sha    : $Format:%H$
        copyright  : (c) 2019, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
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
import warnings
from pat_plugin import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from pat_plugin.util.custom_logging import errorCatcher, openLogPanel
from pat_plugin.util.qgis_common import saveAsDialog, file_in_use, removeFileFromQGIS, \
    copyLayerToMemory, addVectorFileToQGIS
from pat_plugin.util.qgis_symbology import vector_apply_unique_value_renderer
from pat_plugin.util.settings import read_setting, write_setting
    
from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QPushButton

from qgis.core import (QgsMapLayer, QgsMessageLog, QgsVectorFileWriter, QgsCoordinateReferenceSystem)
from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'stripTrialPoints_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured

import pyprecag
from pyprecag import config, crs, describe

# check to see if new version of pyprecag is required
try: 
    from pyprecag.processing import create_points_along_line
except ImportError:
    LOGGER.warning(" Create strip trial points tool is not supported by pyprecag {}. Upgrade to version 0.2.0+".format(pyprecag.__version__))
    

class StripTrialPointsDialog(QtGui.QDialog, FORM_CLASS):
    """Extract statistics from a list of rasters at set locations."""
    toolKey = 'StripTrialPointsDialog'

    def __init__(self, iface, parent=None):

        super(StripTrialPointsDialog, self).__init__(parent)

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
        # self.updateUseSelected()
        self.autoSetCoordinateSystem()

        # GUI Runtime Customisation -----------------------------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat_plugin/icons/icon_stripTrialPoints.svg'))
        self.chkUseSelected.setChecked(False)
        self.chkUseSelected.hide()
        self.chkSaveLinesFile.setChecked(False)

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

        for layer in self.iface.legendInterface().layers():
            if layer.type() == QgsMapLayer.VectorLayer:
                if layer.providerType() != 'ogr':
                    exVlayer_list.append(layer)

        if len(exVlayer_list) > 0:
            self.mcboLineLayer.setExceptedLayerList(exVlayer_list)

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        self.chkUseSelected.setChecked(False)

        if self.mcboLineLayer.count() == 0:
            return

        line_lyr = self.mcboLineLayer.currentLayer()
        self.mFieldComboBox.setLayer(line_lyr)
        if len(line_lyr.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(len(line_lyr.selectedFeatures())))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

    def autoSetCoordinateSystem(self):
        if self.mcboLineLayer.count() == 0:
            return
        
        self.cleanMessageBars()
        line_lyr = self.mcboLineLayer.currentLayer()

        line_utm_crs = crs.getProjectedCRSForXY(line_lyr.extent().xMinimum(),
                                                  line_lyr.extent().yMinimum(),
                                                  int(line_lyr.crs().authid().replace('EPSG:', '')))
        self.outQgsCRS = None

        if line_utm_crs is not None:
            line_crs = QgsCoordinateReferenceSystem('EPSG:{}'.format(line_utm_crs.epsg_number))
            self.outQgsCRS = line_crs

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

    def on_mcboLineLayer_layerChanged(self):
        # self.updateUseSelected()
        self.autoSetCoordinateSystem()

    @QtCore.pyqtSlot(int)
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

    @QtCore.pyqtSlot(name='on_cmdSavePointsFile_clicked')
    def on_cmdSavePointsFile_clicked(self):
        self.messageBar.clearWidgets()
 
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")

        filename = self.mcboLineLayer.currentText() + '_strip-trial-points'

        s = saveAsDialog(self, self.tr("Save As"),
                         self.tr("ESRI Shapefile") + " (*.shp);;",
                         defaultName=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

        self.lneSavePointsFile.setText(s)
        self.lblSavePointsFile.setStyleSheet('color:black')
        self.lneSavePointsFile.setStyleSheet('color:black')
    
    @QtCore.pyqtSlot(int)
    def on_chkSaveLinesFile_stateChanged(self, state):
        self.lneSaveLinesFile.setEnabled(state)
        if state :
            lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
            if lastFolder is None or not os.path.exists(lastFolder):
                lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")
    
            if self.lneSavePointsFile.text() == '':
                filename = os.path.join(lastFolder, self.mcboLineLayer.currentText() + '_strip-trial-lines.shp')
            else:
                path, file = os.path.split(self.lneSavePointsFile.text())
                file, ext = os.path.splitext(file)
                filename = os.path.join(path, file.replace('-points', '') + '-lines' + ext)
            
            self.lneSaveLinesFile.setText(filename)
            self.chkSaveLinesFile.setStyleSheet('color:black')
            self.lneSaveLinesFile.setStyleSheet('color:black')
        else:
            self.lneSaveLinesFile.setText('')
            
    @QtCore.pyqtSlot(name='on_cmdSaveLinesFile_clicked')
    def on_cmdSaveLinesFile_clicked(self):
        self.messageBar.clearWidgets()
 
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")

        if self.lneSaveLinesFile.text() != '':
            filename = self.lneSaveLinesFile.text()
        elif self.lneSavePointsFile.text() == '':
            filename = os.path.join(lastFolder, self.mcboLineLayer.currentText() + '_strip-trial-lines')
        else:
            path, file = os.path.split(self.lneSavePointsFile.text())
            file, ext = os.path.splitext(file)
            filename = os.path.join(path, file.replace('-points', '') + '-lines' + ext)

        s = saveAsDialog(self, self.tr("Save As"),
                         self.tr("ESRI Shapefile") + " (*.shp);;",
                         defaultName=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

        self.chkSaveLinesFile.setChecked(True)
        self.lneSaveLinesFile.setText(s)
        self.chkSaveLinesFile.setStyleSheet('color:black')
        self.lneSaveLinesFile.setStyleSheet('color:black')
        
    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.messageBar.clearWidgets()
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []
            if self.mcboLineLayer.currentLayer() is None:
                self.lblLineLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input line layer required."))
            else:
                self.lblLineLayer.setStyleSheet('color:black')

            if self.dsbDistBtwnPoints.value() <= 0:
                self.lblDistBtwnPoints.setStyleSheet('color:red')
                errorList.append(self.tr("Distance between points must be greater than 0."))
            else:
                self.lblDistBtwnPoints.setStyleSheet('color:black')

            if self.dsbLineOffsetDist.value() <= 0:
                self.lblLineOffsetDist.setStyleSheet('color:red')
                errorList.append(self.tr("Line offset distance must be greater than 0"))
            else:
                self.lblLineOffsetDist.setStyleSheet('color:black')

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

            if self.lneSavePointsFile.text() == '':
                self.lblSavePointsFile.setStyleSheet('color:red')
                errorList.append(self.tr("Save points shapefile"))
            elif not os.path.exists(os.path.dirname(self.lneSavePointsFile.text())):
                self.lneSavePointsFile.setStyleSheet('color:red')
                self.lblSavePointsFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output shapefile folder cannot be found"))
            else:
                self.lblSavePointsFile.setStyleSheet('color:black')
                self.lneSavePointsFile.setStyleSheet('color:black')

            if self.chkSaveLinesFile.isChecked():
                if self.lneSaveLinesFile.text() == '':
                    self.chkSaveLinesFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Save lines shapefile"))
                elif not os.path.exists(os.path.dirname(self.lneSaveLinesFile.text())):
                    self.lneSaveLinesFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Output shapefile folder cannot be found"))
                else:
                    self.chkSaveLinesFile.setStyleSheet('color:black')
                    self.lneSaveLinesFile.setStyleSheet('color:black')
            else:
                self.chkSaveLinesFile.setStyleSheet('color:black')
                self.lneSaveLinesFile.setStyleSheet('color:black')

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
            settingsStr += '\n    {:20}\t{}'.format('Line layer:', self.mcboLineLayer.currentLayer().name())
            settingsStr += '\n    {:20}\t{}'.format('Distance between points (m):', self.dsbDistBtwnPoints.value())
            settingsStr += '\n    {:20}\t{}'.format('Line offset distance (m):', self.dsbLineOffsetDist.value())

            if self.chkUseSelected.isChecked():
                settingsStr += '\n    {:20}\t{} with {} selected features'.format('Layer:',
                                                                                  self.mcboLineLayer.currentLayer().name(),
                                                                                  len(self.mcboLineLayer.currentLayer().selectedFeatures()))

            settingsStr += '\n    {:30}\t{}'.format('Output coordinate system:', self.lblOutCRS.text())
            settingsStr += '\n    {:30}\t{}'.format('Output points :', self.lneSavePointsFile.text())

            if self.chkSaveLinesFile.isChecked():
                settingsStr += '\n    {:30}\t{}\n'.format('Output points :', self.chkSaveLinesFile.text())

            LOGGER.info(settingsStr)

            lyr_line = self.mcboLineLayer.currentLayer()

            if self.chkUseSelected.isChecked():
                line_shapefile = os.path.join(TEMPDIR , lyr_line.name() + '_lines.shp')

                if os.path.exists(line_shapefile):  removeFileFromQGIS(line_shapefile)

                QgsVectorFileWriter.writeAsVectorFormat(lyr_line, line_shapefile, "utf-8", self.outQgsCRS,
                                                        "ESRI Shapefile", onlySelected=True)

                if self.DISP_TEMP_LAYERS:
                    addVectorFileToQGIS(line_shapefile, layer_name=os.path.splitext(os.path.basename(line_shapefile))[0]
                                        , group_layer_name='DEBUG', atTop=True)
            else:
                line_shapefile = lyr_line.source()

            lines_desc = describe.VectorDescribe(line_shapefile)
            gdf_lines = lines_desc.open_geo_dataframe()
            epsgOut = int(self.outQgsCRS.authid().replace('EPSG:', ''))
            
            out_lines = None
            if self.chkSaveLinesFile.isChecked():
                out_lines = self.lneSaveLinesFile.text() 
            
            _ = create_points_along_line(gdf_lines, lines_desc.crs, self.dsbDistBtwnPoints.value(),
                                         self.dsbLineOffsetDist.value(), epsgOut,
                                         out_points_shapefile=self.lneSavePointsFile.text(),
                                         out_lines_shapefile = out_lines)

            out_lyr_points = addVectorFileToQGIS(self.lneSavePointsFile.text(), atTop=True, layer_name=
                                                 os.path.splitext(os.path.basename(self.lneSavePointsFile.text()))[0])
            vector_apply_unique_value_renderer(out_lyr_points, 'Side')
            
            if self.chkSaveLinesFile.isChecked():
                out_lyr_lines = addVectorFileToQGIS(self.lneSaveLinesFile.text(), atTop=True,
                                                    layer_name=
                                                    os.path.splitext(os.path.basename(self.lneSaveLinesFile.text()))[
                                                        0])
                vector_apply_unique_value_renderer(out_lyr_lines, 'Side')

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QtGui.qApp.restoreOverrideCursor()
            return super(StripTrialPointsDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
