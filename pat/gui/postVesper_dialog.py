# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 postVesperDialog - Convert an vesper kriged text file output to raster files

           -------------------
        begin      : 2018-02-01
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

from qgis.PyQt.QtWidgets import QPushButton, QDialog, QApplication, QFileDialog

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from qgis.PyQt import QtCore, QtGui, uic, QtWidgets
from qgis.core import QgsMessageLog, QgsCoordinateReferenceSystem, QgsApplication, Qgis
from qgis.gui import QgsMessageBar

from pyprecag import config
from pyprecag.kriging_ops import vesper_text_to_raster
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import removeFileFromQGIS, addRasterFileToQGIS
from util.settings import read_setting, write_setting
from pat.util.qgis_symbology import RASTER_SYMBOLOGY,\
    raster_apply_classified_renderer

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'postVesper_dialog_base.ui'))


class PostVesperDialog(QDialog, FORM_CLASS):
    """A dialog for converting VESPER text file outputs to raster"""
    toolKey = 'PostVesperDialog'

    def __init__(self, iface, parent=None):

        super(PostVesperDialog, self).__init__(iface.mainWindow())

        # Set up the user interface from Designer.
        self.setupUi(self)

        # The qgis interface
        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_importVesperKriging.svg'))

        self.validationLayout = QtWidgets.QFormLayout(self)

        # source: https://nathanw.net/2013/08/02/death-to-the-message-box-use-the-qgis-messagebar/
        # Add the error messages to top of form via a message bar.
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts

        if isinstance(self.layout(), (QtWidgets.QFormLayout, QtWidgets.QGridLayout)):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # Set Class default variables -------------------------------------
        self.vesper_qgscrs = None
        self.vesp_dict = None
        self.dfCSV = None
        self.block_size = 0
        # self.chkRunVesper.hide()

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

    @QtCore.pyqtSlot(name='on_cmdInVesperCtrlFile_clicked')
    def on_cmdInVesperCtrlFile_clicked(self):
        self.lneInVesperCtrlFile.clear()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s,_f = QFileDialog.getOpenFileName(
            self,
            caption=self.tr("Select a vesper control file to import"),
            directory=inFolder,
            filter=self.tr("Vesper Control File") + " (*control*.txt);;"
                   + self.tr("All Files") + " (*.*);;")

        if s == '':
            self.lblInVesperCtrlFile.setStyleSheet('color:red')
            return
        else:
            s = os.path.normpath(s)
            self.lblInVesperCtrlFile.setStyleSheet('color:black')
            self.lneInVesperCtrlFile.setText(s)
            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder", os.path.dirname(s))

        with open(s) as f:
            for line in f:
                if "epsg=" in line:
                    epsg = int(line.strip().split('=')[-1])
                    self.mCRSinput.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(epsg))
                if 'xside' in line :
                    self.block_size = int(line.strip().split('=')[-1])
                    break

    def on_mCRSinput_crsChanged(self):
        self.vesper_qgscrs = self.mCRSinput.crs()
        self.vesper_qgscrs.validate


    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.cleanMessageBars(AllBars=True)
            errorList = []

            if self.lneInVesperCtrlFile.text() is None or self.lneInVesperCtrlFile.text() == '':
                self.lblInVesperCtrlFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select an vesper control file"))
            elif not os.path.exists(self.lneInVesperCtrlFile.text()):
                self.lblInVesperCtrlFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select an vesper control file"))
            else:
                self.lblInVesperCtrlFile.setStyleSheet('color:black')

            if self.vesper_qgscrs is None or not self.vesper_qgscrs.isValid():
                self.lblInCRSTitle.setStyleSheet('color:red')
                errorList.append(self.tr("Select a valid coordinate system"))
            else:
                self.lblInCRSTitle.setStyleSheet('color:black')
                
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
            self.cleanMessageBars(True)
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))

            # Add settings to log
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Vesper Control File:', self.lneInVesperCtrlFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Coordinate System:',  self.vesper_qgscrs.authid(),
                                                         self.vesper_qgscrs.description())

            settingsStr += '\n    {:30}\t{}'.format('Run Vesper', self.chkRunVesper.isChecked())

            LOGGER.info(settingsStr)

            if self.chkRunVesper.isChecked():
                # if epsg is in the vesp queue, then run vesper to raster
                if self.vesper_qgscrs is not None:
                    epsg = int(self.vesper_qgscrs.authid().replace('EPSG:', ''))

                self.vesp_dict = {'control_file': self.lneInVesperCtrlFile.text(),
                                   'epsg': epsg,
                                   'block_size': self.block_size}

            else:
                out_PredTif, out_SETif, out_CITxt = vesper_text_to_raster(self.lneInVesperCtrlFile.text(),
                                                                          int(self.vesper_qgscrs.authid().replace(
                                                                              'EPSG:', '')))

                raster_sym = RASTER_SYMBOLOGY['Yield']

                removeFileFromQGIS(out_PredTif)
                rasterLyr = addRasterFileToQGIS(out_PredTif, atTop=False)
                raster_apply_classified_renderer(rasterLyr,
                                rend_type=raster_sym['type'],
                                num_classes=raster_sym['num_classes'],
                                color_ramp=raster_sym['colour_ramp'])

                addRasterFileToQGIS(out_SETif, atTop=False)

            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()

            return super(PostVesperDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QApplication.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.iface.mainWindow().statusBar().clearMessage()
            self.send_to_messagebar(str(err), level=Qgis.Critical, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=sys.exc_info())
            return False  # leave dialog open
