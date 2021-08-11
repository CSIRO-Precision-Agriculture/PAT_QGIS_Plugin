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
from builtins import str
from builtins import range
import logging
import os
import sys
import traceback
import re
import numpy as np
import pandas as pd
from shapely.geometry import box
from unidecode import unidecode

from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton, QApplication, QFileDialog, QDialog
from qgis.PyQt.QtGui import QIntValidator

from qgis.gui import QgsMessageBar
from qgis.core import QgsCoordinateReferenceSystem, QgsApplication, QgsMessageLog, Qgis

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from pyprecag import describe, config
from pyprecag.kriging_ops import prepare_for_vesper_krige, VesperControl
from pyprecag.describe import predictCoordinateColumnNames

from util.check_dependencies import check_vesper_dependency
from util.custom_logging import errorCatcher, openLogPanel
from util.settings import read_setting, write_setting
from util.qgis_common import check_for_overlap

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'preVesper_dialog_base.ui'))


class PreVesperDialog(QDialog, FORM_CLASS):
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

        # Catch and redirect python errors directed at the log messages python
        # error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_vesperKriging.svg'))

        self.validationLayout = QtWidgets.QFormLayout(self)
        # source: https://nathanw.net/2013/08/02/death-to-the-message-box-use-the-qgis-messagebar/
        # Add the error messages to top of form via a message bar.
        # leave this message bar for bailouts
        self.messageBar = QgsMessageBar(self)

        if isinstance(self.layout(), (QtWidgets.QFormLayout, QtWidgets.QGridLayout)):
            # create a validation layout so multiple messages can be added and
            # cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            # for use with Vertical/horizontal layout box
            self.layout().insertWidget(0, self.messageBar)

        # Set Class default variables -------------------------------------
        self.vesp_dict = None
        self.dfCSV = None

        # this is a validation flag
        self.OverwriteCtrlFile = False
        self.cboMethod.addItems(
            ['High Density Kriging', 'Low Density Kriging (Advanced)'])

        # To allow only integers for the min number of pts.
        self.onlyInt = QIntValidator()
        self.lneMinPoint.setValidator(self.onlyInt)

        self.vesper_exe = check_vesper_dependency()
        if self.vesper_exe is None or self.vesper_exe == '':
            self.gbRunVesper.setTitle('WARNING:Vesper not found please configure using the about dialog.')
            self.gbRunVesper.setChecked(False)
            self.gbRunVesper.setCheckable(False)
            self.gbRunVesper.setEnabled(False)

    def cleanMessageBars(self, AllBars=True):
        """Clean Messages from the validation layout.
        Args:
            AllBars (bool): Remove All bars including. Defaults to True
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

    def updateCtrlFileName(self):
        if self.chkAutoCtrlFileName.isChecked():
            ctrl_name = os.path.splitext(
                os.path.basename(self.lneInCSVFile.text()))[0]
            ctrl_name = ctrl_name.replace('_normtrimmed', '')
            fld = ''

            if self.cboKrigColumn.currentText() != '':
                # convert field name to something meaningful if it contains
                # invalid chars, ie degC
                fld = unidecode(self.cboKrigColumn.currentText())

                # remove field from filename, then add it according to the naming
                #  convention to avoid duplications.
                # flags=re.I is for a case insensitive find and replace
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

                # and again with invalid characters removed. Only allow
                # alpha-numeric Underscores and hyphens
                fld = re.sub('[^A-Za-z0-9_-]+', '', fld)
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

                # and again with the field truncated to 10 chars
                # fld = fld[:10]
                ctrl_name = re.sub(fld, '', ctrl_name, flags=re.I)

            if self.cboMethod.currentText() == 'High Density Kriging':
                krig_type = 'HighDensity'
            else:
                krig_type = 'LowDensity'

            # add the chosen field name to the control filename
            ctrl_name = '{}_{}_{}_control'.format(ctrl_name, krig_type, fld)

            # only allow alpha-numeric Underscores and hyphens
            ctrl_name = re.sub('[^A-Za-z0-9_-]+', '', ctrl_name)

            # replace more than one instance of underscore with a single one.
            # ie'file____norm__control___yield_h__' to
            # 'file_norm_control_yield_h_'
            ctrl_name = re.sub(r"_+", "_", ctrl_name)
            self.lneCtrlFile.setText(ctrl_name + '.txt')

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
        self.cboMethod.setCurrentIndex(0)
        self.dfCSV = None

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_CSV")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s, _f = QFileDialog.getOpenFileName(self,
                                            caption=self.tr("Select a CSV file to krige"),
                                            directory=inFolder,
                                            filter='{}  (*.csv);;{}  (*.*);;'.format(
                                                self.tr("Comma delimited files"),
                                                self.tr("All Files"))
                                            )

        if s == '':
            return

        self.cleanMessageBars(self)
        self.lneInCSVFile.clear()

        # validate files first
        overlaps, message = self.validate_csv_grid_files(s, self.lneInGridFile.text())

        if not overlaps or message is not None:
            self.lblInCSVFile.setStyleSheet('color:red')
            self.lneInCSVFile.setStyleSheet('color:red')

            self.send_to_messagebar(message,
                                    level=Qgis.Critical,
                                    duration=0, addToLog=True, showLogPanel=True,
                                    exc_info=sys.exc_info())
            return

        s = os.path.normpath(s)
        self.lblInCSVFile.setStyleSheet('color:black')
        self.lneInCSVFile.setStyleSheet('color:black')
        self.lneInCSVFile.setText(s)

        descCSV = describe.CsvDescribe(s)
        self.dfCSV = descCSV.open_pandas_dataframe(nrows=150)

        if len(self.dfCSV) <= 100:
            self.lneMinPoint.clear()
            QMessageBox.warning(self, 'Cannot Krige', 'Kriging is not advised for less '
                                                      'than 100 points')

        self.lneMinPoint.clear()
        self.cboKrigColumn.clear()

        coord_cols = predictCoordinateColumnNames(self.dfCSV.columns)
        epsgcols = [col for col in self.dfCSV.columns if 'EPSG' in col.upper()]

        field_names = list(self.dfCSV.drop(coord_cols + epsgcols, axis=1)
                           .select_dtypes(include=[np.number]).columns.values)

        self.cboKrigColumn.addItems([''] + field_names)

        # To set a coordinate system for vesper2raster, try and get it from
        # a column in the data.
        epsg = 0
        if len(epsgcols) > 0:
            for col in epsgcols:
                if self.dfCSV.iloc[0][col] > 0:
                    epsg = int(self.dfCSV.iloc[0][col])
                    break

        if epsg > 0:
            self.mCRSinput.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(epsg))

        write_setting(PLUGIN_NAME + "/" + self.toolKey +
                      "/LastInFolder_CSV", os.path.dirname(s))
        del descCSV
        self.updateCtrlFileName()

    @QtCore.pyqtSlot(name='on_cmdInGridFile_clicked')
    def on_cmdInGridFile_clicked(self):
        self.lneInGridFile.clear()
        self.messageBar.clearWidgets()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_VesperGrid")

        if inFolder is None or not os.path.exists(inFolder):

            inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_CSV")

            if inFolder is None or not os.path.exists(inFolder):
                inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s, _f = QFileDialog.getOpenFileName(self, caption=self.tr("Choose the Vesper Grid File"),
                                            directory=inFolder,
                                            filter='{}  (*_v.txt);;{}  (*.*);;'.format(
                                                self.tr("Vesper Grid File(s)"),
                                                self.tr("All Files"))
                                            )

        self.cleanMessageBars(self)
        s = os.path.normpath(s)

        self.lneInGridFile.clear()
        self.lneInGridFile.setStyleSheet('color:red')
        self.lblInGridFile.setStyleSheet('color:red')

        overlaps, message = self.validate_csv_grid_files(self.lneInCSVFile.text(), s)

        if overlaps or message is None:
            self.lneInGridFile.setStyleSheet('color:black')
            self.lblInGridFile.setStyleSheet('color:black')
            if overlaps:
                self.lneInGridFile.setText(s)
                write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_VesperGrid",
                              os.path.dirname(s))
        else:
            self.send_to_messagebar(message,
                                    level=Qgis.Critical,
                                    duration=0, addToLog=True, showLogPanel=True,
                                    exc_info=sys.exc_info())

    @QtCore.pyqtSlot(name='on_cmdVariogramFile_clicked')
    def on_cmdVariogramFile_clicked(self):
        self.lneVariogramFile.clear()
        self.messageBar.clearWidgets()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_Variogram")

        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_Variogram")

            if inFolder is None or not os.path.exists(inFolder):
                inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        s, _f = QFileDialog.getOpenFileName(self, caption=self.tr("Choose the Vesper Variogram File"),
                                            directory=inFolder,
                                            filter='{}  (*.txt);;{}  (*.*);;'.format(
                                                self.tr("Variogram Text File(s)"),
                                                self.tr("All Files"))
                                            )

        self.cleanMessageBars(self)

        if s == '':
            self.lneVariogramFile.setStyleSheet('color:red')
            self.lblVariogramFile.setStyleSheet('color:red')
            return

        if 'Variogram Model' not in open(s).read():
            self.lneVariogramFile.setStyleSheet('color:red')
            self.lblVariogramFile.setStyleSheet('color:red')
            self.send_to_messagebar("Invalid Variogram File", level=Qgis.Critical,
                                    duration=0, addToLog=True, showLogPanel=True,
                                    exc_info=sys.exc_info())
            # self.lneVariogramFile.clear()
            return

        s = os.path.normpath(s)
        self.lblVariogramFile.setStyleSheet('color:black')
        self.lneVariogramFile.setStyleSheet('color:black')
        self.lneVariogramFile.setText(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey +
                      "/LastInFolder_Variogram", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdVesperFold_clicked')
    def on_cmdVesperFold_clicked(self):
        self.messageBar.clearWidgets()

        if self.lneVesperFold.text() is None:
            outFolder = ''
        else:
            outFolder = self.lneVesperFold.text()

        if outFolder == '':
            outFolder = read_setting(
                PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
            if outFolder is None or not os.path.exists(outFolder):
                outFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')
        
        outFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder_CSV")
        s = QFileDialog.getExistingDirectory(self, self.tr(
            "Vesper processing folder. A Vesper sub-folder will be created."), outFolder,
                                             QFileDialog.ShowDirsOnly)

        self.cleanMessageBars(self)
        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lblVesperFold.setStyleSheet('color:black')
        self.lneVesperFold.setStyleSheet('color:black')
        self.lneVesperFold.setText(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", s)

    @QtCore.pyqtSlot(int)
    def on_chkAutoCtrlFileName_stateChanged(self, state):
        self.updateCtrlFileName()

    @QtCore.pyqtSlot(int)
    def on_cboMethod_currentIndexChanged(self, index):
        self.stackedWidget.setCurrentIndex(index)
        self.updateCtrlFileName()
        if self.dfCSV is None:
            return

        if len(self.dfCSV) <= 100:
            self.cleanMessageBars(self)
            self.lneMinPoint.clear()
            QMessageBox.warning(
                self, 'Cannot Krige', 'Kriging is not advised for less than 100 points')

        if 'Low Density Kriging' in self.cboMethod.currentText():
            if len(self.dfCSV) <= 150:  # only partial file opened so open it all
                descCSV = describe.CsvDescribe(self.lneInCSVFile.text())
                self.dfCSV = descCSV.open_pandas_dataframe()
            self.lblRowCount.setText("The maximum number of points is {}.".format(len(self.dfCSV)))
            self.lneMinPoint.setText(str(len(self.dfCSV) - 2))
        else:
            self.lneMinPoint.clear()
            self.lblRowCount.setText('')

    def parse_variogram_file(self):

        vario_values = {}

        for line in open(self.lneVariogramFile.text()):
            # reset some text to control file tags
            line = line.replace('C0', 'CO')
            line = line.replace('Variogram Model', 'modtyp').strip()

            if set(':=.').intersection(set(line)):
                for ea in ['=', ':', ' ']:
                    if ea in line:
                        key, val = line.split(ea, 1)
                        break

                # sort out the numerics from the strings
                try:
                    key = int(float(key)) if int(
                        float(key)) == float(key) else float(key)
                except ValueError:
                    key = key.strip()

                try:
                    val = int(float(val)) if int(
                        float(val)) == float(val) else float(val)
                except ValueError:
                    val = val.strip()

                # only return keys required for the control file.
                # and key in VESPER_OPTIONS.keys():
                if isinstance(key, str):
                    vario_values[key] = val

        return vario_values

    def validate_csv_grid_files(self, csv_file, grid_file, show_msgbox=True):
        """ validate the csv and grid files and check for overlap assuming that they are
        of the same coordinate system if True then message will be blank else a message
        will be generated
        """

        overlaps = False

        if csv_file != '':
            if not os.path.exists(csv_file):
                return False, 'CSV file does not exist'
            else:
                try:
                    df_csv = pd.read_csv(csv_file)
                    csvX, csvY = predictCoordinateColumnNames(df_csv.columns)
                    csv_bbox = box(df_csv[csvX].min(), df_csv[csvY].min(),
                                   df_csv[csvX].max(), df_csv[csvY].max())

                except Exception as err:
                    self.lblInCSVFile.setStyleSheet('color:red')
                    self.lneInCSVFile.setStyleSheet('color:red')
                    return False, 'Invalid CSV file'

        if grid_file != '':
            if not os.path.exists(grid_file):
                return False, 'Grid file does not exist'
            else:
                try:
                    df_grid = pd.read_table(grid_file, names=['X', 'Y'], delim_whitespace=True, skipinitialspace=True)

                    grid_bbox = box(df_grid['X'].min(), df_grid['Y'].min(),
                                    df_grid['X'].max(), df_grid['Y'].max())


                except Exception as err:
                    self.lblInGridFile.setStyleSheet('color:red')
                    self.lneInGridFile.setStyleSheet('color:red')
                    return False, 'Invalid VESPER grid file'

        # only continue if both inputs aren't blank
        if csv_file == '' or grid_file == '':
            # if one or the other is blank keep validate as true or it wont write to the GUI
            return True, None

        if csv_file == grid_file:
            return False, "VESPER grid file and CSV file cannot be the same file"

        # now we can check for overlap

        if self.mCRSinput.crs().isValid():
            epsg = self.mCRSinput.crs().authid()
        else:
            epsg = ''

        overlaps = check_for_overlap(csv_bbox, grid_bbox, epsg, epsg)
        if not overlaps:
            message = 'There is no overlap between the VESPER Grid file and the CSV file.\n' \
                      'Please check input files and coordinate systems'

            if show_msgbox:
                QMessageBox.warning(self, 'No Overlap', message)

            self.lblInGridFile.setStyleSheet('color:red')
            self.lneInGridFile.setStyleSheet('color:red')
            self.lblInCSVFile.setStyleSheet('color:red')
            self.lneInCSVFile.setStyleSheet('color:red')
        else:
            message = None
            self.lblInGridFile.setStyleSheet('color:black')
            self.lneInGridFile.setStyleSheet('color:black')
            self.lblInCSVFile.setStyleSheet('color:black')
            self.lneInCSVFile.setStyleSheet('color:black')

        return overlaps, message

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.messageBar.clearWidgets()
            self.cleanMessageBars(AllBars=True)
            errorList = []

            if self.lneInCSVFile.text() is None or self.lneInCSVFile.text() == '':
                self.lblInCSVFile.setStyleSheet('color:red')
                self.lneInCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select an input csv data file"))
            elif not os.path.exists(self.lneInCSVFile.text()):
                self.lblInCSVFile.setStyleSheet('color:red')
                self.lneInCSVFile.setStyleSheet('color:red')
                errorList.append(self.tr("Input csv data file does not exist"))
            else:
                self.lblInCSVFile.setStyleSheet('color:black')
                self.lneInCSVFile.setStyleSheet('color:black')

            if self.lneInGridFile.text() is None or self.lneInGridFile.text() == '':
                self.lblInGridFile.setStyleSheet('color:red')
                self.lneInGridFile.setStyleSheet('color:red')
                errorList.append(self.tr("Select a Vesper grid file"))
            elif not os.path.exists(self.lneInGridFile.text()):
                self.lblInGridFile.setStyleSheet('color:red')
                self.lneInGridFile.setStyleSheet('color:red')
                errorList.append(self.tr("Vesper grid file does not exists."))
            else:
                self.lblInGridFile.setStyleSheet('color:black')
                self.lneInGridFile.setStyleSheet('color:black')

            if not self.mCRSinput.crs().isValid():
                self.lblInCRS.setStyleSheet('color:red;background:transparent;')
                errorList.append(self.tr("Select a valid coordinate system"))
            else:
                self.lblInCRS.setStyleSheet('color:black;background:transparent;')

            pass_check, message = self.validate_csv_grid_files(self.lneInCSVFile.text(),
                                                               self.lneInGridFile.text())
            if not pass_check:
                errorList.append(self.tr(message))
                # errorList.append(self.tr("Input csv file and grid file do not overlap. Could be "
                #                          "due to differing coordinate systems or invalid files"))

            if self.cboKrigColumn.currentText() == '':
                self.lblKrigColumn.setStyleSheet('color:red')
                errorList.append(self.tr("Select a column to krige"))
            else:
                self.lblKrigColumn.setStyleSheet('color:black')

            if self.cboMethod.currentText() != 'High Density Kriging':

                if self.lneVariogramFile.text() is None or self.lneVariogramFile.text() == '':
                    self.lblVariogramFile.setStyleSheet('color:red')
                    self.lneVariogramFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Select a variogram text file"))
                elif not os.path.exists(self.lneVariogramFile.text()):
                    self.lblVariogramFile.setStyleSheet('color:red')
                    self.lneVariogramFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Variogram text file does not exists."))
                else:
                    self.lblVariogramFile.setStyleSheet('color:black')
                    self.lneVariogramFile.setStyleSheet('color:black')

                if int(self.lneMinPoint.text()) >= len(self.dfCSV):
                    self.lneMinPoint.setStyleSheet('color:red')
                    self.lneMinPoint.setStyleSheet('color:red')
                    errorList.append(
                        self.tr("Minimum number of points should be at least "
                                "2 less than the dataset count"))
                else:
                    self.lneMinPoint.setStyleSheet('color:black')
                    self.lneMinPoint.setStyleSheet('color:black')

            if len(self.lneCtrlFile.text()) > 100:
                self.lblCtrlFile.setStyleSheet('color:red')
                self.lneCtrlFile.setStyleSheet('color:red')
                errorList.append(self.tr("Control file name should be less than 100 characters"))
            else:
                self.lblCtrlFile.setStyleSheet('color:black')
                self.lneCtrlFile.setStyleSheet('color:black')

            if self.lneVesperFold.text() == '':
                self.lblVesperFold.setStyleSheet('color:red')
                errorList.append(self.tr("Select output Vesper data folder"))
            elif not os.path.exists(self.lneVesperFold.text()):
                self.lneVesperFold.setStyleSheet('color:red')
                errorList.append(
                    self.tr("Output Vesper data folder does not exist"))
            else:
                self.lblVesperFold.setStyleSheet('color:black')
                self.lneVesperFold.setStyleSheet('color:black')

            ctrl_file = os.path.join(self.lneVesperFold.text(), self.lneCtrlFile.text())

            if os.path.exists(ctrl_file):
                message = 'Vesper Control File {} already exists. Do you want to' \
                          ' overwrite?'.format(self.lneCtrlFile.text())

                reply = QMessageBox.question(self, 'Control File', message, QMessageBox.Yes, QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.overwrite_ctrl_file = True
                    self.lblVesperFold.setStyleSheet('color:black')
                else:
                    self.overwrite_ctrl_file = False
                    self.lblCtrlFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Output control file exists please choose a different name"))

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

            message = '- and run VESPER' if self.gbRunVesper.isChecked() else ''
            LOGGER.info('{st}\nProcessing {} {}'.format(
                self.windowTitle(), message, st='*' * 50))

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:30}\t{}'.format('Data File:', self.lneInCSVFile.text())

            settingsStr += '\n    {:30}\t{} - {}'.format('Input Projected Coordinate System:',
                                                         self.mCRSinput.crs().authid(),
                                                         self.mCRSinput.crs().description())

            settingsStr += '\n    {:30}\t{}'.format('Krige Column:', self.cboKrigColumn.currentText())
            settingsStr += '\n    {:30}\t{}'.format('Grid File:', self.lneInGridFile.text())
            settingsStr += '\n    {:30}\t{}'.format('Output Vesper Folder:', self.lneVesperFold.text())
            settingsStr += '\n    {:30}\t{}'.format('Control File:', self.lneCtrlFile.text())

            settingsStr += '\n    {:30}\t{}'.format('Mode:',self.cboMethod.currentText())

            if self.cboMethod.currentText() == 'High Density Kriging':
                settingsStr += '\n    {:30}\t{}'.format('Block Kriging Size:',
                                                        int(self.dsbBlockKrigSize.value()))

            else:
                settingsStr += '\n    {:30}\t{}'.format('Variogram File:', self.lneVariogramFile.text())
                settingsStr += '\n    {:30}\t{}'.format('Min Point Number:', self.lneMinPoint.text())

            settingsStr += '\n    {:30}\t{}'.format('Display Vesper Graphics:', self.chkDisplayGraphics.isChecked())

            settingsStr += '\n    {:30}\t{}'.format('Run Vesper Now:', self.gbRunVesper.isChecked())

            if self.gbRunVesper.isChecked():
                settingsStr += '\n    {:30}\t{}'.format('Import Vesper Files to Rasters:',self.chkVesper2Raster.isChecked())

            LOGGER.info(settingsStr)

            # get a fresh dataframe for the input csv file
            self.dfCSV = pd.read_csv(self.lneInCSVFile.text())

            vc = VesperControl()

            if self.cboMethod.currentText() == 'High Density Kriging':
                vc.update(xside=int(self.dsbBlockKrigSize.value()),
                          yside=int(self.dsbBlockKrigSize.value()))
            else:
                # from the variogram text file find and update the control file keys
                vario = self.parse_variogram_file()

                vesp_keys = {key: val for key, val in list(vario.items()) if key in vc}
                vc.update(vesp_keys)

                # apply the other keys.
                vc.update({'jpntkrg': 1,
                           'jlockrg': 0,
                           'minpts': int(self.lneMinPoint.text()),
                           'maxpts': len(self.dfCSV),
                           'jcomvar': 0,
                           })
            epsg = int(self.mCRSinput.crs().authid().replace('EPSG:', ''))
            bat_file, ctrl_file = prepare_for_vesper_krige(self.dfCSV,
                                                           self.cboKrigColumn.currentText(),
                                                           self.lneInGridFile.text(),
                                                           self.lneVesperFold.text(),
                                                           control_textfile=self.lneCtrlFile.text(),
                                                           coord_columns=[],
                                                           epsg=epsg,
                                                           display_graphics=self.chkDisplayGraphics.isChecked(),
                                                           control_options=vc)

            epsg = 0
            if self.mCRSinput.crs() is not None and self.chkVesper2Raster.isChecked():
                epsg = int(self.mCRSinput.crs().authid().replace('EPSG:', ''))
            
            message = 'Successfully created files for Vesper kriging. The control file is {}'.format(ctrl_file)
            self.send_to_messagebar(message, level=Qgis.Success, duration=0, addToLog=True, core_QGIS=True)
            LOGGER.info('Successfully created files for Vesper kriging')
            
            if self.gbRunVesper.isChecked():
                # Add to vesper queue
                self.vesp_dict = {'control_file': ctrl_file, 
                                  'epsg': epsg,
                                  'block_size':int(self.dsbBlockKrigSize.value())}
         

            QApplication.restoreOverrideCursor()
            return super(PreVesperDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.cleanMessageBars(True)
            self.send_to_messagebar(str(err), level=Qgis.Critical, duration=0,
                                    addToLog=True, showLogPanel=True, exc_info=sys.exc_info())
            return False
