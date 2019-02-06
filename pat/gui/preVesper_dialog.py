# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 preVesperDialog - Prepare data and run vesper kriging
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
import logging
import os
import sys
import traceback
import re
import numpy as np
from PyQt4.QtGui import QMessageBox, QPushButton
from unidecode import unidecode

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from PyQt4 import QtCore, QtGui, uic
from qgis.core import QgsCoordinateReferenceSystem
from qgis.core import QgsMessageLog
from qgis.gui import QgsGenericProjectionSelector
from qgis.gui import QgsMessageBar

from pyprecag import describe, config
from pyprecag.kriging_ops import prepare_for_vesper_krige
from util.check_dependencies import check_vesper_dependency
from util.custom_logging import errorCatcher, openLogPanel
from util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'preVesper_dialog_base.ui'))


class PreVesperDialog(QtGui.QDialog, FORM_CLASS):
    """Dialog to prepare data and run vesper kriging"""
    toolKey = 'PreVesperDialog'

    def __init__(self, iface, parent=None):

        super(PreVesperDialog, self).__init__(iface.mainWindow())

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
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_vesperKriging.svg'))

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
        self.vesp_dict = None
        self.vesper_qgscrs = None
        self.dfCSV = None

        # this is a validation flag
        self.OverwriteCtrlFile = False

        self.vesper_exe = check_vesper_dependency()
        if self.vesper_exe is None or self.vesper_exe == '':
            self.gbRunVesper.setTitle('WARNING:Vesper not found please configure using the about dialog.')
            self.gbRunVesper.setChecked(False)
            self.gbRunVesper.setCheckable(False)
            self.gbRunVesper.setEnabled(False)

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

    @QtCore.pyqtSlot(int)
    def on_cboKrigColumn_currentIndexChanged(self, index):
        if self.cboKrigColumn.currentText() != '':
            self.lblKrigColumn.setStyleSheet('color:black')
        if self.chkAutoCtrlFileName.isChecked():
            self.updateCtrlFileName()

    @QtCore.pyqtSlot(name='on_cmdInCSVFile_clicked')
    def on_cmdInCSVFile_clicked(self):
        self.lneInCSVFile.clear()
        self.messageBar.clearWidgets()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastCSVFolder")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s = QtGui.QFileDialog.getOpenFileName(
            self,
            caption=self.tr("Select a CSV file to krige"),
            directory=inFolder,
            filter=self.tr("Comma delimited files") + " (*.csv);;" + self.tr("All Files") + " (*.*);;")

        self.cleanMessageBars(self)
        if s == '':
            self.lblInCSVFile.setStyleSheet('color:red')

        else:
            s = os.path.normpath(s)
            self.lblInCSVFile.setStyleSheet('color:black')
            self.lneInCSVFile.setText(s)

            descCSV = describe.CsvDescribe(s)
            self.dfCSV = descCSV.open_pandas_dataframe(nrows=10)

            self.cboKrigColumn.clear()
            self.cboKrigColumn.addItems([''] + list(self.dfCSV.select_dtypes(include=[np.number]).columns.values))

            # To set a coordinate system for vesper2raster, try and get it from a column in the data.
            epsg = 0
            epsgcol = [col for col in self.dfCSV.columns if 'EPSG' in col.upper()]
            if len(epsgcol) > 0:
                for col in epsgcol:
                    if self.dfCSV.iloc[0][col] > 0:
                        epsg = self.dfCSV.iloc[0][col]
                        break

            if epsg > 0:
                self.vesper_qgscrs = QgsCoordinateReferenceSystem("EPSG:{}".format(epsg))  # 0 will return
                self.lblInCRS.setText('{}  -  {}'.format(self.vesper_qgscrs.description(), self.vesper_qgscrs.authid()))
            else:
                self.lblInCRS.setText('Unspecified')

            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastCSVFolder", os.path.dirname(s))
            del descCSV
            self.updateCtrlFileName()

    @QtCore.pyqtSlot(name='on_cmdInGridFile_clicked')
    def on_cmdInGridFile_clicked(self):
        self.lneInGridFile.clear()
        self.messageBar.clearWidgets()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastVesperGridFolder")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastCSVFolder")
            if inFolder is None or not os.path.exists(inFolder):
                inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s = QtGui.QFileDialog.getOpenFileName(
            self,
            caption=self.tr("Choose the Vesper Grid File"),
            directory=inFolder,
            filter=self.tr("Vesper Grid File(s)") + " (*_v.txt);;" + self.tr("All Files") + " (*.*);;")

        self.cleanMessageBars(self)
        if s == '':
            self.lneInGridFile.setStyleSheet('color:red')
        else:
            s = os.path.normpath(s)
            self.lblInGridFile.setStyleSheet('color:black')
            self.lneInGridFile.setText(s)
            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastVesperGridFolder", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdVesperFold_clicked')
    def on_cmdVesperFold_clicked(self):
        self.messageBar.clearWidgets()

        if self.lneVesperFold.text() is None:
            outFolder = ''
        else:
            outFolder = self.lneVesperFold.text()

        if outFolder == '':
            outFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastVesperOutFolder")
            if outFolder is None or not os.path.exists(outFolder):
                outFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        s = QtGui.QFileDialog.getExistingDirectory(self, self.tr(
            "Vesper processing folder. A Vesper sub-folder will be created."), outFolder,
                                                   QtGui.QFileDialog.ShowDirsOnly)

        self.cleanMessageBars(self)
        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lblVesperFold.setStyleSheet('color:black')
        self.lneVesperFold.setStyleSheet('color:black')
        self.lneVesperFold.setText(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastVesperOutFolder", s)

    @QtCore.pyqtSlot(int)
    def on_chkAutoCtrlFileName_stateChanged(self, state):
        self.updateCtrlFileName()

    def updateCtrlFileName(self):
        if self.chkAutoCtrlFileName.isChecked():
            ctrl_name = os.path.splitext(os.path.basename(self.lneInCSVFile.text()))[0]
            ctrl_name = ctrl_name.replace('_normtrimmed', '')
            fld = ''

            if self.cboKrigColumn.currentText() != '':
                # convert field name to something meaningful if it contains invalid chars, ie degC
                fld = unidecode(self.cboKrigColumn.currentText())

                # remove field from filename, then addit according to the naming convention to avoid duplications.
                # flags=re.I is for a case insensitive find and replace
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

                # and again with invalid characters removed. Only allow alpha-numeric Underscores and hyphens
                fld = re.sub('[^A-Za-z0-9_-]+', '', fld)
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

                # and again with the field truncated to 10 chars
                fld = fld[:10]
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

            # add the chosen field name to the control filename
            ctrl_name = '{}_{}_control'.format(ctrl_name[:20], fld)

            # only allow alpha-numeric Underscores and hyphens
            ctrl_name = re.sub('[^A-Za-z0-9_-]+', '', ctrl_name)

            # replace more than one instance of underscore with a single one.
            # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
            ctrl_name = re.sub(r"_+", "_", ctrl_name)
            self.lneCtrlFile.setText(ctrl_name + '.txt')

    @QtCore.pyqtSlot(name='on_cmdInCRS_clicked')
    def on_cmdInCRS_clicked(self):
        self.messageBar.clearWidgets()

        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage('Select coordinate system for the Vesper raster files')
        if dlg.exec_():
            if dlg.selectedAuthId() != '':
                self.vesper_qgscrs = QgsCoordinateReferenceSystem(dlg.selectedAuthId())
                if self.vesper_qgscrs == 'Unspecified' or self.vesper_qgscrs == '':
                    self.lblInCRS.setText('Unspecified')
                    self.lblOutCRS.setText('Unspecified')
                else:
                    self.lblInCRS.setText(
                        '{}  -  {}'.format(self.vesper_qgscrs.description(), self.vesper_qgscrs.authid()))
                    self.lblInCRS.setStyleSheet('color:black;background:transparent;')
                    self.lblInCRSTitle.setStyleSheet('color:black')
        self.cleanMessageBars(self)

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.messageBar.clearWidgets()
            self.cleanMessageBars(AllBars=True)
            errorList = []

            if self.lneInCSVFile.text() is None or self.lneInCSVFile.text() == '':
                self.lblInCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select an input csv data file"))
            elif not os.path.exists(self.lneInCSVFile.text()):
                self.lblInCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Input csv data file does not exist"))
            else:
                self.lblInCSVFile.setStyleSheet('color:black')

            if self.cboKrigColumn.currentText() == '':
                self.lblKrigColumn.setStyleSheet('color:red')
                errorList.append(self.tr("Select a column to krige"))
            else:
                self.lblKrigColumn.setStyleSheet('color:black')

            if self.lneInGridFile.text() is None or self.lneInGridFile.text() == '':
                self.lblInGridFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select a Vesper grid file"))
            elif not os.path.exists(self.lneInGridFile.text()):
                self.lblInGridFile.setStyleSheet('color:red')
                errorList.append(self.tr("Vesper grid file does not exists."))
            else:
                self.lblInGridFile.setStyleSheet('color:black')

            if self.lneVesperFold.text() == '':
                self.lblVesperFold.setStyleSheet('color:red')
                errorList.append(self.tr("Select output Vesper data folder"))
            elif not os.path.exists(self.lneVesperFold.text()):
                self.lneVesperFold.setStyleSheet('color:red')
                errorList.append(self.tr("Output Vesper data folder does not exist"))
            else:
                self.lblVesperFold.setStyleSheet('color:black')
                self.lneVesperFold.setStyleSheet('color:black')

            ctrl_file = os.path.join(self.lneVesperFold.text(), self.lneCtrlFile.text())
            if os.path.exists(ctrl_file):
                message = 'Vesper Control File {} already exists in the output Vesper' \
                          ' Folder. Do you want to overwrite?'.format(self.lneCtrlFile.text())

                reply = QMessageBox.question(self, 'Control File', message, QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
                if reply == QtGui.QMessageBox.Yes:
                    self.overwrite_ctrl_file = True
                    self.lblVesperFold.setStyleSheet('color:black')
                else:
                    self.overwrite_ctrl_file = False
                    self.lblCtrlFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Output control file exists please choose a different name"))

            if self.vesper_qgscrs is None:
                self.lblInCRSTitle.setStyleSheet('color:red')
                self.lblInCRS.setStyleSheet('color:red;background:transparent;')
                errorList.append(self.tr("Select coordinate system"))
            else:
                self.lblInCRSTitle.setStyleSheet('color:black')
                self.lblInCRS.setStyleSheet('color:black;background:transparent;')

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

            message = '- and run VESPER' if self.gbRunVesper.isChecked() else ''
            LOGGER.info('{st}\nProcessing {} {}'.format(self.windowTitle(), message, st='*' * 50))

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Data File:', self.lneInCSVFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Krige Column:', self.cboKrigColumn.currentText())
            settingsStr += '\n    {:30}\t{}'.format('Block Kriging Size:', int(self.dsbBlockKrigSize.value()))
            settingsStr += '\n    {:30}\t{}'.format('Grid File:', self.lneInGridFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Output Vesper Folder:', self.lneVesperFold.text())
            settingsStr += '\n    {:30}\t{}'.format('Output Control File:', self.lneCtrlFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Display Vesper Graphics:', self.chkDisplayGraphics.isChecked())

            settingsStr += '\n    {:30}\t{}'.format('Run Vesper Now:', self.gbRunVesper.isChecked())
            if self.gbRunVesper.isChecked():
                settingsStr += '\n    {:30}\t{}'.format('Import Vesper Files to Rasters:',
                                                        self.chkVesper2Raster.isChecked())
                if self.chkVesper2Raster.isChecked():
                    settingsStr += '\n    {:30}\t{}'.format('Vesper Files Coordinate System:', self.lblInCRS.text())

            LOGGER.info(settingsStr)

            descCSV = describe.CsvDescribe(self.lneInCSVFile.text())
            dfCSV = descCSV.open_pandas_dataframe()
            bat_file, ctrl_file = prepare_for_vesper_krige(dfCSV, self.cboKrigColumn.currentText(),
                                                           self.lneInGridFile.text(), self.lneVesperFold.text(),
                                                           control_textfile=self.lneCtrlFile.text(),
                                                           block_size=int(self.dsbBlockKrigSize.text()),
                                                           coord_columns=[],
                                                           epsg=int(self.vesper_qgscrs.authid().replace('EPSG:', '')),
                                                           display_graphics=self.chkDisplayGraphics.isChecked())

            epsg = 0
            if self.vesper_qgscrs is not None and self.chkVesper2Raster.isChecked():
                epsg = int(self.vesper_qgscrs.authid().replace('EPSG:', ''))

            if self.gbRunVesper.isChecked():
                # Add to vesper queue
                self.vesp_dict = {'control_file': ctrl_file, 'epsg': epsg}

            else:
                message = 'Successfully created files for Vesper kriging. The control file is {}'.format(ctrl_file)
                self.send_to_messagebar(message, level=QgsMessageBar.SUCCESS, duration=0, addToLog=True,
                                        core_QGIS=True)

            QtGui.qApp.restoreOverrideCursor()
            return super(PreVesperDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QtGui.qApp.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=sys.exc_info())
            return False
