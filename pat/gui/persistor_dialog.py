# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  Persistor -  Determine the performance persistence of yield
           -------------------
        begin      : 2019-06-11
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
import re
import sys
import time
import traceback
import math

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import save_as_dialog, file_in_use
from util.settings import read_setting, write_setting
from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QTableWidgetItem, QPushButton

from pyprecag import config
from pyprecag.processing import persistor_target_probability, persistor_all_years

from qgis.core import QgsMapLayerRegistry, QgsMapLayer, QgsMessageLog, QgsVectorFileWriter, \
    QgsUnitTypes
from qgis.gui import QgsMessageBar

from util.qgis_common import removeFileFromQGIS, copyLayerToMemory, addRasterFileToQGIS
import util.qgis_symbology as rs

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'persistor_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())


class PersistorDialog(QtGui.QDialog, FORM_CLASS):
    # The key used for saving settings for this dialog
    toolKey = 'PersistorDialog'

    def __init__(self, iface, parent=None):

        super(PersistorDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(
            PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()
        self.pixel_size = 0
        # Catch and redirect python errors directed at the log messages python
        # error tab.
        QgsMessageLog.instance().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        # leave this message bar for bailouts
        self.messageBar = QgsMessageBar(self)
        self.validationLayout = QtGui.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), QtGui.QFormLayout):
            # create a validation layout so multiple messages can be added and
            # cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            # for use with Vertical/horizontal layout box
            self.layout().insertWidget(0, self.messageBar)

        # GUI Runtime Customisation -------------------------------------------
        self.setWindowIcon(QtGui.QIcon(
            ':/plugins/pat/icons/icon_persistor.svg'))

        self.cboMethod.addItems(
            ['Target Probability', 'Target Over All Years'])
        self.cboMethod.setCurrentIndex(0)
        for ea_cbo in [self.cboAllYearTargetPerc, self.cboUpperPerc, self.cboLowerPerc]:
            ea_cbo.addItems(['{}%'.format(ea) for ea in range(50, -55,  -5)])

            ea_cbo.setCurrentIndex(ea_cbo.findText(
                '10%', QtCore.Qt.MatchFixedString))

        self.cboLowerPerc.setCurrentIndex(
            self.cboLowerPerc.findText('-10%', QtCore.Qt.MatchFixedString))

        for ea_tab in [self.tabUpper, self.tabLower]:
            ea_tab.setColumnCount(2)
            ea_tab.hideColumn(0)  # don't need to display the unique layer ID
            ea_tab.setHorizontalHeaderItem(0, QTableWidgetItem("ID"))
            ea_tab.setHorizontalHeaderItem(1, QTableWidgetItem("0 Raster(s)"))
            ea_tab.horizontalHeader().setResizeMode(QtGui.QHeaderView.Stretch)
            ea_tab.hideColumn(0)  # don't need to display the unique layer ID

        self.lblPixelFilter.setText('Only process rasters with one pixel size. '
                                    'Adding the first raster layer will set this pixel size')

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including those which haven't timed-out. Default: True
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
            level (QgsMessageBarLevel): The level of message to log. Defaults: QgsMessageBar.INFO
            duration (int): Number of seconds to display message for. 0 is no timeout. Default: 5
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
        """ Run through all loaded layers to find ones which should be excluded."""

        # loop through the pick list
        if self.cboMethod.currentText() == 'Target Over All Years':
            tab_obj_list = [self.tabUpper]
        else:
            tab_obj_list = [self.tabUpper, self.tabLower]

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

            # if layer is already in the table list the exclude it from the
            # pick list to avoid duplicates.
            in_use = [True if ea_tab.findItems(layer.id(), QtCore.Qt.MatchExactly)
                      else False for ea_tab in tab_obj_list]

            if all(in_use):
                exlayer_list.append(layer)

        if self.tabUpper.rowCount() == 0 and self.tabLower.rowCount() == 0:
            # reset to show all pixel sizes.
            self.mcboRasterLayer.setExceptedLayerList([])
            self.pixel_size = 0
            self.lblPixelFilter.setText('Only process rasters with one pixel size.'
                                        'Adding the first raster layer will set this pixel size')

        if sorted(exlayer_list) != sorted(self.mcboRasterLayer.exceptedLayerList()):
            self.mcboRasterLayer.setExceptedLayerList(exlayer_list)

        self.tabUpper.horizontalHeader().setStyleSheet('color:black')
        self.tabUpper.setHorizontalHeaderItem(1, QTableWidgetItem("{} Raster(s)".format(
            self.tabUpper.rowCount())))

        self.tabLower.horizontalHeader().setStyleSheet('color:black')
        self.tabLower.setHorizontalHeaderItem(1, QTableWidgetItem("{} Raster(s)".format(
            self.tabLower.rowCount())))

        self.cmdAdd.setEnabled(len(self.mcboRasterLayer) > 0)
        self.cmdDel.setEnabled(self.tabUpper.rowCount() > 0)

        self.cmdAddLower.setEnabled(len(self.mcboRasterLayer) > 0)
        self.cmdDelLower.setEnabled(self.tabLower.rowCount() > 0)

    def add_raster_to_table_list(self, raster_layer, upper=False, lower=False):
        if self.pixel_size == 0 and raster_layer is not None:

            # get the pixel units from the coordinate systems as a string  ie degrees, metres etc.
            # for QGIS 3  see the following functions
            # https://www.qgis.org/api/classQgsUnitTypes.html#a7d09b9df11b6dcc2fe29928f5de296a4
            # .toAbbreviatedString()
            # and /or DistanceValue
            # https://www.qgis.org/api/structQgsUnitTypes_1_1DistanceValue.html

            pixel_units = QgsUnitTypes.encodeUnit(
                raster_layer.crs().mapUnits())

            # Adjust for Aust/UK spelling
            pixel_units = pixel_units.replace('meters', 'metres')

            if raster_layer.crs().geographicFlag():
                ft = 'f'  # this will convert 1.99348e-05 to 0.000020
            else:
                ft = 'g'  # this will convert 2.0 to 2 or 0.5, '0.5'

            self.pixel_size = format(raster_layer.rasterUnitsPerPixelX(), ft)
            self.lblPixelFilter.setText('Only allow processing of rasters with a pixel size '
                                        'of {} {}'.format(self.pixel_size, pixel_units))

        # get list of objects to update
        tab_obj_list = []
        if upper:
            tab_obj_list.append(self.tabUpper)
        if lower:
            tab_obj_list.append(self.tabLower)

        for ea_tab in tab_obj_list:
            # find out if it is already there.
            if ea_tab.findItems(raster_layer.id(), QtCore.Qt.MatchExactly):
                continue

            rowPosition = ea_tab.rowCount()
            ea_tab.insertRow(rowPosition)

            # Save the id of the layer to a column used to get a layer object later on.
            # adapted from
            # https://gis.stackexchange.com/questions/165415/activating-layer-by-its-name-in-pyqgis
            ea_tab.setItem(rowPosition, 0, QtGui.QTableWidgetItem(raster_layer.id()))
            ea_tab.setItem(rowPosition, 1, QtGui.QTableWidgetItem(raster_layer.name()))

        self.setMapLayers()

    @QtCore.pyqtSlot(int)
    def on_cboMethod_currentIndexChanged(self, index):
        self.stackedWidget.setCurrentIndex(index)

        self.tabLower.clear()
        self.tabLower.setRowCount(0)
        self.fraLower.setHidden(index)
        self.lblUpper.setHidden(index)
        self.lblLower.setHidden(index)
        self.lineSplitter.setHidden(index)

        self.setMapLayers()

    @QtCore.pyqtSlot(name='on_cmdAdd_clicked')
    def on_cmdAdd_clicked(self):
        if self.mcboRasterLayer.currentLayer() is None:
            self.cmdAdd.setStyleSheet('color:red')
            self.tabUpper.horizontalHeader().setStyleSheet('color:red')
            self.lblRasterLayer.setStyleSheet('color:red')
            self.send_to_messagebar('No raster layers to process. Please add a RASTER '
                                    'layer into QGIS', level=QgsMessageBar.WARNING, duration=5)
            return

        self.add_raster_to_table_list(self.mcboRasterLayer.currentLayer(),
                                      upper=True, lower=False)
        if self.tabUpper.rowCount() >= 2:
            self.cboUpperProb.clear()
            cbo_options = ["{0:.0f}%".format(float(g) / self.tabUpper.rowCount() * 100)
                           for g in range(0, self.tabUpper.rowCount() + 1)]

            self.cboUpperProb.addItems(cbo_options)

            self.cboUpperProb.setCurrentIndex(
                int(math.ceil(len(cbo_options) / 2)))

    @QtCore.pyqtSlot(name='on_cmdAddLower_clicked')
    def on_cmdAddLower_clicked(self):
        if self.mcboRasterLayer.currentLayer() is None:
            self.cmdAddLower.setStyleSheet('color:red')
            self.tabLower.horizontalHeader().setStyleSheet('color:red')
            self.lblRasterLayer.setStyleSheet('color:red')
            self.send_to_messagebar(
                'No raster layers to process. Please add a RASTER layer into QGIS',
                level=QgsMessageBar.WARNING, duration=5)
            return

        self.add_raster_to_table_list(self.mcboRasterLayer.currentLayer(),
                                      upper=False, lower=True)
        if self.tabLower.rowCount() >= 2:
            self.cboLowerProb.clear()
            cbo_options = ["{0:.0f}%".format(float(g) / self.tabLower.rowCount() * 100)
                           for g in range(0, self.tabLower.rowCount() + 1)]

            self.cboLowerProb.addItems(cbo_options)
            self.cboLowerProb.setCurrentIndex(
                int(math.ceil(len(cbo_options) / 2)))

    @QtCore.pyqtSlot(name='on_cmdDel_clicked')
    def on_cmdDel_clicked(self):
        self.tabUpper.removeRow(self.tabUpper.currentRow())
        self.setMapLayers()

    @QtCore.pyqtSlot(name='on_cmdDelLower_clicked')
    def on_cmdDelLower_clicked(self):
        self.tabLower.removeRow(self.tabLower.currentRow())
        self.setMapLayers()

    @QtCore.pyqtSlot(name='on_cmdSaveFile_clicked')
    def on_cmdSaveFile_clicked(self):
        lastFolder = read_setting(
            PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        if self.cboMethod.currentText() == 'Target Over All Years':
            filename = 'persistor_allyears.tif'
        else:
            filename = 'persistor_targetprob.tif'

        # replace more than one instance of underscore with a single one.
        # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
        filename = re.sub(r"_+", "_", filename)

        s = save_as_dialog(self, self.tr("Save As"),
                           self.tr("GeoTIFF, TIFF") + " (*.tif);;",
                           default_name=os.path.join(lastFolder, filename))

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
            write_setting(PLUGIN_NAME + "/" + self.toolKey +
                          "/LastOutFolder", os.path.dirname(s))

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []

            if self.tabUpper.rowCount() >= 2:
                self.cmdAdd.setStyleSheet('color:black')
                self.tabUpper.horizontalHeader().setStyleSheet('color:black')
                self.lblRasterLayer.setStyleSheet('color:black')

            elif self.mcboRasterLayer.currentLayer() is None or self.tabUpper.rowCount() < 2:
                self.cmdAdd.setStyleSheet('color:red')
                self.tabUpper.horizontalHeader().setStyleSheet('color:red')
                self.lblRasterLayer.setStyleSheet('color:red')

                if self.mcboRasterLayer.currentLayer() is None:
                    errorList.append(
                        self.tr('No raster layers to process. Please add a RASTER layer into QGIS'))
                else:
                    if self.cboMethod.currentText() == 'Target Probability':
                        errorList.append(
                            self.tr('Please add at least TWO upper category rasters to analyse'))
                    else:
                        errorList.append(
                            self.tr('Please add at least TWO raster to analyse'))

            if self.cboMethod.currentText() == 'Target Probability':
                if self.tabLower.rowCount() >= 2:
                    self.cmdAddLower.setStyleSheet('color:black')
                    self.tabLower.horizontalHeader().setStyleSheet('color:black')
                    self.lblRasterLayer.setStyleSheet('color:black')

                elif self.mcboRasterLayer.currentLayer() is None or self.tabLower.rowCount() < 2:
                    self.cmdAddLower.setStyleSheet('color:red')
                    self.tabLower.horizontalHeader().setStyleSheet('color:red')
                    self.lblRasterLayer.setStyleSheet('color:red')

                    if self.mcboRasterLayer.currentLayer() is None:
                        errorList.append(self.tr('No raster layers to process. Please add'
                                                 ' a RASTER layer into QGIS'))
                    else:
                        errorList.append(
                            self.tr('Please add at least TWO lower category rasters to analyse'))

            if self.lneSaveFile.text() == '':
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(
                    self.tr("Please enter an output TIFF filename"))
            elif not os.path.exists(os.path.dirname(self.lneSaveFile.text())):
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output folder does not exist."))
            elif os.path.exists(self.lneSaveFile.text()) and \
                    file_in_use(self.lneSaveFile.text(), False):
                self.lneSaveFile.setStyleSheet('color:red')
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr(
                    "Output file {} is open in QGIS or another application".format(
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
                    self.send_to_messagebar(
                        unicode(ea), level=QgsMessageBar.WARNING, duration=(i + 1) * 5)
                return False

        return True

    def accept(self, *args, **kwargs):
        try:

            if not self.validate():
                return False

            # disable form via a frame, this will still allow interaction with
            # the message bar
            self.fraMain.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)

            # Change cursor to Wait cursor
            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))
            self.iface.mainWindow().statusBar().showMessage(
                'Processing {}'.format(self.windowTitle()))
            LOGGER.info('{st}\nProcessing {}'.format(
                self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait.. QGIS will be locked... "
                                    "See log panel for progress.", level=QgsMessageBar.WARNING,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            registry = QgsMapLayerRegistry.instance()
            upper_src = [registry.mapLayer(self.tabUpper.item(row, 0).text()).source() for row in
                         range(0, self.tabUpper.rowCount())]
            upper_names = [registry.mapLayer(self.tabUpper.item(row, 0).text()).name() for row in
                           range(0, self.tabUpper.rowCount())]

            lower_src = [registry.mapLayer(self.tabLower.item(row, 0).text()).source() for row in
                         range(0, self.tabLower.rowCount())]

            lower_names = [registry.mapLayer(self.tabLower.item(row, 0).text()).name() for row in
                           range(0, self.tabLower.rowCount())]

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:20}\t{}'.format('Persistor Method: ',
                                                    self.cboMethod.currentText())

            if self.cboMethod.currentText() == 'Target Probability':
                settingsStr += '\n    {:20}\t{}'.format('Upper Category: ',
                                                        'Count of rasters:{}'.format(
                                                            len(upper_names)))

                settingsStr += '\n\t\t    ' + '\n\t\t    '.join(upper_names)

                settingsStr += '\n    {:20}\t{}'.format('     Target Probability: ',
                                                        self.cboUpperProb.currentText())

                settingsStr += '\n    {:20}\t{}'.format('     Target Percentage: ',
                                                        self.cboUpperPerc.currentText())

                # ------------------------------------------------------
                settingsStr += '\n    {:20}\t{}'.format('Lower Category: ',
                                                        'Count of rasters:{}'.format(
                                                            len(upper_names)))

                settingsStr += '\n\t\t    ' + '\n\t\t    '.join(upper_names)

                settingsStr += '\n    {:20}\t{}'.format('     Target Probability: ',
                                                        self.cboLowerProb.currentText())

                settingsStr += '\n    {:20}\t{}'.format('     Target Percentage: ',
                                                        self.cboLowerPerc.currentText())
            else:
                settingsStr += '\n    {:20}\t{}'.format(
                    '     Rasters: ', len(upper_names))
                settingsStr += '\n\t\t' + '\n\t\t'.join(upper_names)

                settingsStr += '\n    {:20}\t{}'.format('Greater Than: ',
                                                        self.optGreaterThan.isChecked())
                settingsStr += '\n    {:20}\t{}'.format('Target Percentage: ',
                                                        self.cboAllYearTargetPerc.currentText())

            settingsStr += '\n    {:20}\t{}\n'.format(
                'Output TIFF File:', self.lneSaveFile.text())

            LOGGER.info(settingsStr)

            stepTime = time.time()

            if self.cboMethod.currentText() == 'Target Probability':
                _ = persistor_target_probability(upper_src,
                                                 int(self.cboUpperPerc.currentText().strip('%')),
                                                 int(self.cboUpperProb.currentText().strip('%')),
                                                 lower_src,
                                                 int(self.cboLowerPerc.currentText().strip('%')),
                                                 int(self.cboLowerProb.currentText().strip('%')),
                                                 self.lneSaveFile.text())
                raster_sym = rs.RASTER_SYMBOLOGY['Persistor - Target Probability']

            else:
                _ = persistor_all_years(upper_src,
                                        self.lneSaveFile.text(),
                                        self.optGreaterThan.isChecked(),
                                        int(self.cboAllYearTargetPerc.currentText().strip('%')))
                
                raster_sym = rs.RASTER_SYMBOLOGY['Persistor - All Years']

            rasterLyr = addRasterFileToQGIS(self.lneSaveFile.text(), atTop=False)
            rs.raster_apply_unique_value_renderer(rasterLyr,1,
                                                  color_ramp=raster_sym['colour_ramp'],
                                                  invert=raster_sym['invert'])

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QtGui.qApp.restoreOverrideCursor()
            return super(PersistorDialog, self).accept(*args, **kwargs)

        except Exception as err:
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)
            err_mess = str(err)
            exc_info = sys.exc_info()

            if isinstance(err, IOError) and err.filename == self.lneSaveFile.text():
                err_mess = 'Output CSV File in Use - IOError {} '.format(
                    err.strerror)
                exc_info = None

            self.send_to_messagebar(err_mess, level=QgsMessageBar.CRITICAL, duration=0,
                                    addToLog=True, showLogPanel=True, exc_info=exc_info)
            QtGui.qApp.restoreOverrideCursor()
            return False  # leave dialog open
