# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  RandomPixelSelectionDialog - create a shapefile of randomly select pixels
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
import re
from builtins import str
from builtins import range
import logging
import os
import sys
import traceback

import rasterio
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from qgis.PyQt import QtGui, uic, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QDockWidget, QTabWidget, QPushButton, QApplication, QDialog

from qgis.core import QgsMessageLog, Qgis, QgsApplication, QgsMapLayerProxyModel
from qgis.gui import QgsMessageBar

from pyprecag import processing, crs as pyprecag_crs
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import removeFileFromQGIS, save_as_dialog, addVectorFileToQGIS, get_layer_source
from util.settings import read_setting, write_setting

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'randomPixelSelection_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class RandomPixelSelectionDialog(QDialog, FORM_CLASS):
    """create a shapefile of randomly select pixels"""
    toolKey = 'RandomPixelSelectionDialog'

    def __init__(self, iface, parent=None):

        super(RandomPixelSelectionDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

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

        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_randomPixel.svg'))

        last_size = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastSampleSize")

        if last_size is not None and int(last_size) > 0:
            self.dsbSize.setValue(read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastSampleSize", int))

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

    def openLogPanel(self):
        logMessagesPanel = self.iface.mainWindow().findChild(QDockWidget, 'MessageLog')
        # Check to see if it is already open
        if not logMessagesPanel.isVisible():
            logMessagesPanel.setVisible(True)

        # find and set the active tab
        tabWidget = logMessagesPanel.findChildren(QTabWidget)[0]
        for iTab in range(0, tabWidget.count()):
            if tabWidget.tabText(iTab) == PLUGIN_SHORT:
                tabWidget.setCurrentIndex(iTab)
                break

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

    @QtCore.pyqtSlot(name='on_cmdSaveFile_clicked')
    def on_cmdSaveFile_clicked(self):
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + "/BASE_OUT_FOLDER")

        filename = self.mcboTargetLayer.currentLayer().name() + '_{}randompts'.format(int(self.dsbSize.value()))

        # Only use alpha numerics and underscore and hyphens.
        filename = re.sub('[^A-Za-z0-9_-]+', '', filename)

        # replace more than one instance of underscore with a single one.
        filename = re.sub(r"_+", "_", filename)

        s = save_as_dialog(self, self.tr("Save As"),
                         self.tr("ESRI Shapefile") + " (*.shp);;",
                         default_name=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

        self.lneSaveFile.setText(s)
        self.lblSaveFile.setStyleSheet('color:black')
        self.lneSaveFile.setStyleSheet('color:black')

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.cleanMessageBars(True)
            errorList = []
            targetLayer = self.mcboTargetLayer.currentLayer()
            if targetLayer is None or self.mcboTargetLayer.currentLayer().name() == '':
                errorList.append(self.tr('Target layer is not set. Please load a raster layer into QGIS'))

            if self.lneSaveFile.text() == '':
                self.lblSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Enter output Shapefile"))
            elif not os.path.exists(os.path.dirname(self.lneSaveFile.text())):
                self.lneSaveFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output shapefile folder does not exist"))
            else:
                self.lblSaveFile.setStyleSheet('color:black')
                self.lneSaveFile.setStyleSheet('color:black')

            if len(errorList) > 0:
                raise ValueError(errorList)

        except ValueError as e:
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

            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastSampleSize", self.dsbSize.value())

            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Sample Size:', self.dsbSize.value())
            settingsStr += '\n    {:30}\t{}'.format('Layer:', self.mcboTargetLayer.currentLayer().name())
            settingsStr += '\n    {:30}\t{}'.format('Output Shapefile:', self.lneSaveFile.text())

            LOGGER.info(settingsStr)

            lyrTarget = self.mcboTargetLayer.currentLayer()
            removeFileFromQGIS(self.lneSaveFile.text())

            raster_file = get_layer_source(lyrTarget)
            rasterCRS = pyprecag_crs.getCRSfromRasterFile(raster_file)

            if rasterCRS.epsg is None:
                rasterCRS.getFromEPSG(lyrTarget.crs().authid())

            with rasterio.open(os.path.normpath(raster_file)) as src:
                processing.random_pixel_selection(src, rasterCRS, int(self.dsbSize.value()), self.lneSaveFile.text())

            lyrPts = addVectorFileToQGIS(self.lneSaveFile.text(), atTop=True,
                                         layer_name=os.path.splitext(os.path.basename(self.lneSaveFile.text()))[0])

            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            return super(RandomPixelSelectionDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.send_to_messagebar(str(err), level=Qgis.Critical, duration=0, addToLog=True,
                                    exc_info=sys.exc_info())
            return False  # leave dialog open
