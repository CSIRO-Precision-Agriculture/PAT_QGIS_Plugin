# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 RescaleNormaliseDialog - Rescale or normalise a single band from an image
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

import logging
import os
import re
import sys
import traceback

from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtGui import QPushButton

from qgis._core import QgsMessageLog
from qgis.gui import QgsMessageBar

import rasterio
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import removeFileFromQGIS, addRasterFileToQGIS, saveAsDialog
from util.settings import read_setting, write_setting

from pyprecag.raster_ops import rescale, normalise
from pyprecag import crs as pyprecag_crs

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'rescaleNormalise_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class RescaleNormaliseDialog(QtGui.QDialog, FORM_CLASS):
    """Dialog for Rescaling or normalising a single band from an image"""

    toolKey = 'RescaleNormaliseDialog'

    def __init__(self, iface, parent=None):

        super(RescaleNormaliseDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        # The qgis interface
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsMessageLog.instance().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui --------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtGui.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), QtGui.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # GUI Customisation -----------------------------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_rescaleNormalise.svg'))
        self.cboMethod.addItems(['Rescale', 'Normalise'])
        self.update_bandlist()

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

    def on_mcboTargetLayer_layerChanged(self):
        self.update_bandlist()

    def update_bandlist(self):
        self.cboBand.clear()
        if self.mcboTargetLayer.currentLayer() is not None:
            bandCount = self.mcboTargetLayer.currentLayer().bandCount()
            bandlist = ['band {}'.format(i) for i in range(1, bandCount + 1)]
            self.cboBand.addItems(bandlist)

    @QtCore.pyqtSlot(int)
    def on_cboMethod_currentIndexChanged(self, index):
        self.lblRescale.setDisabled(self.cboMethod.currentText() != 'Rescale')
        self.dsbRescaleLower.setDisabled(self.cboMethod.currentText() != 'Rescale')
        self.dsbRescaleUpper.setDisabled(self.cboMethod.currentText() != 'Rescale')

    @QtCore.pyqtSlot(name='on_cmdSaveRasterFile_clicked')
    def on_cmdSaveRasterFile_clicked(self):
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")

        filename = self.mcboTargetLayer.currentText() + '_' + self.cboMethod.currentText()
        if self.cboMethod.currentText() == 'Rescale':
            filename = self.mcboTargetLayer.currentText() + '_{}{}-{}'.format(self.cboMethod.currentText(),
                                                                              int(self.dsbRescaleLower.value()),
                                                                              int(self.dsbRescaleUpper.value()))

        filename = re.sub('[^A-Za-z0-9_-]+', '', filename)

        s = saveAsDialog(self, self.tr("Save As"),
                         self.tr("Tiff") + " (*.tif);;",
                         defaultName=os.path.join(lastFolder, filename + '.tif'))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)

        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))
        self.lneSaveRasterFile.setText(s)
        self.lblOutputFile.setStyleSheet('color:black')
        self.lneSaveRasterFile.setStyleSheet('color:black')

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            errorList = []
            targetLayer = self.mcboTargetLayer.currentLayer()
            if targetLayer is None or self.mcboTargetLayer.currentText() == '':
                errorList.append(self.tr('Target layer is not set. Please load a raster layer into QGIS'))

            if self.lneSaveRasterFile.text() == '':
                self.lblOutputFile.setStyleSheet('color:red')
                errorList.append(self.tr("Please enter an output raster filename"))
            elif not os.path.exists(os.path.dirname(self.lneSaveRasterFile.text())):
                self.lneSaveRasterFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output raster folder does not exist."))
            else:
                self.lblOutputFile.setStyleSheet('color:black')
                self.lneSaveRasterFile.setStyleSheet('color:black')

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
        if not self.validate():
            return False
        try:

            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))

            LOGGER.info('{st}\nProcessing {} Raster'.format(self.cboMethod.currentText(), st='*' * 50))
            self.iface.mainWindow().statusBar().showMessage('Processing {} Raster'.format(self.cboMethod.currentText()))

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Layer:', self.mcboTargetLayer.currentLayer().name())
            settingsStr += '\n    {:30}\t{}'.format('For Band: ', self.cboBand.currentText())
            settingsStr += '\n    {:30}\t{}'.format('Method: ', self.cboMethod.currentText())
            if self.cboMethod.currentText() == 'Rescale':
                settingsStr += '\n    {:30}\t{} - {}'.format('Between:', self.dsbRescaleLower.value(),
                                                             self.dsbRescaleUpper.value())
            settingsStr += '\n    {:30}\t{}'.format('Output Raster File:', self.lneSaveRasterFile.text())

            LOGGER.info(settingsStr)

            lyrTarget = self.mcboTargetLayer.currentLayer()
            rasterOut = self.lneSaveRasterFile.text()
            removeFileFromQGIS(rasterOut)

            rasterIn = lyrTarget.source()
            # need this to maintain correct wkt otherwise gda/mga defaults to utm zonal
            in_crswkt = lyrTarget.crs().toWkt()

            band_num = int(self.cboBand.currentText().replace('band ', ''))
            with rasterio.open(os.path.normpath(rasterIn)) as src:
                if self.cboMethod.currentText() == 'Rescale':
                    rast_result = rescale(src, self.dsbRescaleLower.value(), self.dsbRescaleUpper.value(),
                                          band_num=band_num, ignore_nodata=True)
                else:
                    rast_result = normalise(src, band_num=band_num, ignore_nodata=True)
                meta = src.meta.copy()

                meta['crs'] = str(in_crswkt)
                meta['count'] = 1
                meta['dtype'] = rasterio.float32

            with rasterio.open(os.path.normpath(rasterOut), 'w', **meta) as dst:
                dst.write_band(1, rast_result)

            rasterLyr = addRasterFileToQGIS(rasterOut, atTop=False)

            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            return super(RescaleNormaliseDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QtGui.qApp.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.iface.mainWindow().statusBar().clearMessage()

            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL,
                                    duration=0, addToLog=True, exc_info=sys.exc_info())
            return False  # leave dialog open
