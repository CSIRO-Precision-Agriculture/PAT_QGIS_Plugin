# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 postVesperDialog - Convert an vesper kriged text file output to raster files

           -------------------
        begin      : 2018-02-01
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au PAT@csiro.au

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

from PyQt4.QtGui import QPushButton

from pat_plugin import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from PyQt4 import QtCore, QtGui, uic
from qgis.core import QgsMessageLog, QgsCoordinateReferenceSystem
from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector

from pyprecag import config
from pyprecag.kriging_ops import vesper_text_to_raster
from pat_plugin.util.custom_logging import errorCatcher, openLogPanel
from pat_plugin.util.qgis_common import removeFileFromQGIS, addRasterFileToQGIS
from pat_plugin.util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'postVesper_dialog_base.ui'))


class PostVesperDialog(QtGui.QDialog, FORM_CLASS):
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
        QgsMessageLog.instance().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.validationLayout = QtGui.QFormLayout(self)

        # source: https://nathanw.net/2013/08/02/death-to-the-message-box-use-the-qgis-messagebar/
        # Add the error messages to top of form via a message bar.
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts

        if isinstance(self.layout(), (QtGui.QFormLayout, QtGui.QGridLayout)):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # Set Class default variables -------------------------------------
        self.vesper_qgscrs = None
        self.vesp_dict = None
        self.dfCSV = None
        self.chkRunVesper.hide()

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

    @QtCore.pyqtSlot(name='on_cmdInVesperCtrlFile_clicked')
    def on_cmdInVesperCtrlFile_clicked(self):
        self.lneInVesperCtrlFile.clear()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s = QtGui.QFileDialog.getOpenFileName(
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
                    if line.strip().split('=') > 2:
                        epsg = line.strip().replace("'", '').split('=')[-1]
                        self.vesper_qgscrs = QgsCoordinateReferenceSystem("EPSG:{}".format(epsg))
                        self.vesper_qgscrs.validate()
                        self.lneInCRS.setText('{}  -  {}'.format(self.vesper_qgscrs.description(),
                                                                 self.vesper_qgscrs.authid()))
                    break

    @QtCore.pyqtSlot(name='on_cmdInCRS_clicked')
    def on_cmdInCRS_clicked(self):
        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage('Select coordinate system for the input file geometry')
        if self.vesper_qgscrs is not None:
            dlg.setSelectedAuthId(self.vesper_qgscrs.authid())
        if dlg.exec_():
            if dlg.selectedAuthId() != '':  # ie clicked ok without selecting a projection
                crs = QgsCoordinateReferenceSystem(dlg.selectedAuthId())
                if crs == 'Unspecified' or crs == '':
                    self.vesper_qgscrs = None
                    self.lneInCRS.setText('Unspecified')
                else:
                    self.vesper_qgscrs = QgsCoordinateReferenceSystem(crs)
                    self.vesper_qgscrs.validate()
                    self.lneInCRS.setText(
                        '{}  -  {}'.format(self.vesper_qgscrs.description(), self.vesper_qgscrs.authid()))
                    self.lneInCRS.setStyleSheet('color:black;background:transparent;')
                    self.lblInCRSTitle.setStyleSheet('color:black')

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

            if self.vesper_qgscrs is None:
                self.lblInCRSTitle.setStyleSheet('color:red')
                self.lneInCRS.setStyleSheet('color:red;background:transparent;')
                errorList.append(self.tr("Select coordinate system of the vesper outputs"))
            else:
                self.lblInCRSTitle.setStyleSheet('color:black')
                self.lneInCRS.setStyleSheet('color:black;background:transparent;')

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
            self.cleanMessageBars(True)
            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))

            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))

            # Add settings to log
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Vesper Control File:', self.lneInVesperCtrlFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Coordinate System:', self.lneInCRS.text())
            settingsStr += '\n    {:30}\t{}'.format('Run Vesper', self.chkRunVesper.isChecked())

            LOGGER.info(settingsStr)

            if self.chkRunVesper.isChecked():
                # if epsg is in the vesp queue, then run vesper to raster
                if self.vesper_qgscrs is not None:
                    epsg = int(self.vesper_qgscrs.authid().replace('EPSG:', ''))

                self.vesp_dict = {'control_file': self.lneInVesperCtrlFile.text(), 'epsg': epsg}

            else:
                out_PredTif, out_SETif, out_CITxt = vesper_text_to_raster(self.lneInVesperCtrlFile.text(),
                                                                          int(self.vesper_qgscrs.authid().replace(
                                                                              'EPSG:', '')))

                removeFileFromQGIS(out_PredTif)
                addRasterFileToQGIS(out_PredTif, atTop=False)
                addRasterFileToQGIS(out_SETif, atTop=False)

            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()

            return super(PostVesperDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QtGui.qApp.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.iface.mainWindow().statusBar().clearMessage()
            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=sys.exc_info())
            return False  # leave dialog open
