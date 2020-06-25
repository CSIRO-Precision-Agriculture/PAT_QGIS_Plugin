# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 CleanTrimPointsDialog

 Clean and Trim a points or csv layer based on a field to remove excess points
           -------------------
        begin      : 2017-10-18
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au

 Modified from: Spreadsheet Layers QGIS Plugin on 21/08/2017
     https://github.com/camptocamp/QGIS-SpreadSheetLayers/blob/master/widgets/SpreadsheetLayersDialog.py
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the associated CSIRO Open Source Software       *
 *   License Agreement (GPLv3) provided with this plugin.                  *
 *                                                                         *
 ***************************************************************************/
"""
from __future__ import print_function, division

import time
from  datetime import timedelta

from builtins import str
from builtins import range


import logging

import re
import shutil
import sys
import os
import traceback
from unidecode import unidecode
import csv
import inspect

import chardet
import pandas as pd

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR

from pyprecag import processing, describe, crs as pyprecag_crs, convert, config, LOGGER
from pyprecag.describe import predictCoordinateColumnNames

from qgis.PyQt import uic, QtGui, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import (QDialog, QSpinBox, QHeaderView, QTableView, QPushButton, QFrame, QFileDialog,
                                 QApplication, QDialogButtonBox)

from qgis.core import (QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsMessageLog, QgsMapLayerProxyModel,
                       QgsApplication, Qgis)
from qgis.gui import QgsMessageBar, QgsProjectionSelectionWidget

from util.qgis_common import (copyLayerToMemory, removeFileFromQGIS, addVectorFileToQGIS, save_as_dialog,
                              file_in_use, get_UTM_Coordinate_System)
from util.settings import read_setting, write_setting

from util.custom_logging import errorCatcher, openLogPanel

from pat.util.qgis_symbology import vector_apply_unique_value_renderer


class PandasModel(QtCore.QAbstractTableModel):
    """
    Class to populate a table view with a pandas dataframe
    source:https://stackoverflow.com/a/42955764
    Source: https://github.com/datalyze-solutions/pandas-qt/blob/master/pandasqt/models/DataFrameModel.py
    """

    def __init__(self, data, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self._dataFrame = data

    def rowCount(self, parent=None):
        return self._dataFrame.shape[0]

    def columnCount(self, parent=None):
        return self._dataFrame.shape[1]

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == QtCore.Qt.DisplayRole:
            try:
                return str(self._dataFrame.iloc[index.row(), index.column()])
            except:
                return None

    def headerData(self, section, orientation, role):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            try:
                val = self._dataFrame.columns[section] + '\n{}'.format(self._dataFrame.dtypes[section])
                return val
            except:
                return None

        if orientation == QtCore.Qt.Vertical and role == QtCore.Qt.DisplayRole:
            return self._dataFrame.index[section]

        return None


FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'cleanTrimPoints_wizard_base.ui'))


class CleanTrimPointsDialog(QDialog, FORM_CLASS):
    """Note we use multiple inheritance so you can reference any gui elements
    directly from this class without needing to go through self.ui and
    so that qt autoconnect slots work."""

    toolKey = 'CleanTrimPointsDialog'

    def __init__(self, iface, parent=None):

        super(CleanTrimPointsDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        # The qgis interface
        self.iface = iface  # The qgis interface

        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()
        self.source_file = None

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        # Setup for validation messagebar on gui-----------------------------
        ''' source: https://nathanw.net/2013/08/02/death-to-the-message-box-use-the-qgis-messagebar/
        Add the error messages to top of form via a message bar. '''

        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtWidgets.QFormLayout(self)

        if isinstance(self.layout(), QtWidgets.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # #save default values so they can be easily reset when a new file is selected.
        self.default_vals = {}
        for name, obj in inspect.getmembers(self):
            if isinstance(obj, QSpinBox):
                self.default_vals[obj.objectName()] = obj.value()

        self.stackedWidget.setCurrentIndex(0)
        self.stackedWidget.currentChanged.connect(self.update_prev_next_buttons)
        self.button_box.button(QDialogButtonBox.Ok).setVisible(False)
        for obj, lay_filter in [(self.mcboTargetLayer,QgsMapLayerProxyModel.PointLayer),
                            (self.mcboClipPolyLayer,QgsMapLayerProxyModel.PolygonLayer)]:

            obj.setFilters(lay_filter)

            if hasattr(obj, "setAllowEmptyLayer"):
                obj.setAllowEmptyLayer(True)
                obj.setShowCrs(True)
                obj.setLayer(None)    # set default to empty layer

        #print(self.mgbPreviewTable.isCollapsed())


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

    # @QtCore.pyqtSlot(name='on_optFile_clicked')
    # def on_optFile_clicked(self):
    #     self.mcboTargetLayer.setEnabled(False)

    # @QtCore.pyqtSlot(name='on_optLayer_clicked')
    # def on_optLayer_clicked(self):
    #     self.mcboTargetLayer.setEnabled(True)

    def on_mcboClipPolyLayer_layerChanged(self):
        if self.mcboClipPolyLayer.currentLayer() is None:
            self.chkClipToPoly.setChecked(False)
            return

        self.chkClipToPoly.setChecked(True)
        lyrTarget = self.mcboClipPolyLayer.currentLayer()

        if lyrTarget.selectedFeatureCount() == 0:
            self.chkUseSelected_ClipPoly.setText('No features selected')
            self.chkUseSelected_ClipPoly.setEnabled(False)
            self.chkUseSelected_ClipPoly.setChecked(False)
            self.chkUseSelected_ClipPoly.setStyleSheet('font:regular')
        else:
            self.chkUseSelected_ClipPoly.setText(
                'Use the {} selected feature(s) ?'.format(lyrTarget.selectedFeatureCount()))
            self.chkUseSelected_ClipPoly.setEnabled(True)
            self.chkUseSelected_ClipPoly.setStyleSheet('font:bold')
    

        
    def on_mcboTargetLayer_layerChanged(self):
        if not self.mcboTargetLayer.currentLayer():
            return

        process_fields = [''] + [field.name() for field in self.mcboTargetLayer.currentLayer().fields() if field.isNumeric()]

        self.cboProcessField.clear()
        self.cboProcessField.addItems(process_fields)
        
        self.optLayer.setChecked(True)
        lyrTarget = self.mcboTargetLayer.currentLayer()

        if lyrTarget.selectedFeatureCount() == 0:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)
            self.chkUseSelected.setChecked(False)
            self.chkUseSelected.setStyleSheet('font:regular')
        else:
            self.chkUseSelected.setText(
                'Use the {} selected feature(s) ?'.format(lyrTarget.selectedFeatureCount()))
            self.chkUseSelected.setEnabled(True)
            self.chkUseSelected.setStyleSheet('font:bold')

    def on_optFile_toggled(self):
        self.lneInCSVFile.setEnabled(self.optFile.isChecked())
        self.cmdInFile.setEnabled(self.optFile.isChecked())

    def on_mgbPreviewTable_collapsedStateChanged(self):
        a= self.mgbPreviewTable.isCollapsed()

    @QtCore.pyqtSlot(int)
    def on_chkAutoCRS_stateChanged(self, state):
        if self.chkAutoCRS.isChecked() :

            layer = self.mcboTargetLayer.currentLayer()
            out_crs= get_UTM_Coordinate_System(layer.extent().xMinimum(),
                                      layer.extent().yMinimum(),
                                      layer.crs().authid())

            if out_crs:
                self.mCRSoutput.setCrs(out_crs)

    @QtCore.pyqtSlot(name='on_cmdBack_clicked')
    def on_cmdBack_clicked(self):
        self.button_box.button(QDialogButtonBox.Ok).setVisible(False)
        self.cmdNext.setVisible(True)

        idx = self.stackedWidget.currentIndex()

        widget_page = self.stackedWidget.currentWidget().objectName()
        moveby=1

        if (widget_page=='pgeParameters' and not self.optFile.isChecked()):
            moveby=2

        self.stackedWidget.setCurrentIndex(idx - moveby)

    @QtCore.pyqtSlot(name='on_cmdNext_clicked')
    def on_cmdNext_clicked(self):
        self.button_box.button(QDialogButtonBox.Ok).setVisible(False)
        self.cmdNext.setVisible(True)
                
        if self.validate():
            moveby = 1 
            idx = self.stackedWidget.currentIndex()

            widget_page = self.stackedWidget.currentWidget().objectName()
            
            if self.stackedWidget.currentIndex() == 0 or widget_page=='pgeSource':
                if self.optFile.isChecked():
                    self.csv_properties(self.lneInCSVFile.text())
                    self.loadTablePreview()
                    
                    # set default coordinate system
                    self.qgsCRScsv.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(4326))
                    
                else:
                    self.lneInCSVFile.clear()    
                    #move by two
                    moveby = 2
                    
            elif idx == 1 or widget_page=='pgeFromFile':
                self.mgbPreviewTable.setCollapsed(False)
                
            elif idx == 2 or widget_page=='pgeParameters':
                self.button_box.button(QDialogButtonBox.Ok).setVisible(True)
                self.cmdNext.setVisible(False)
                self.getOutputCRS()
            
            self.stackedWidget.setCurrentIndex(idx+moveby)
            

    @QtCore.pyqtSlot(name='on_cmdInFile_clicked')
    def on_cmdInFile_clicked(self):
        self.resetFormToDefaults()
        
        """Click Button Event."""
        self.optFile.setChecked(True)
        s = QFileDialog.getOpenFileName(
            self,
            caption=self.tr("Choose a file to open"),
            directory=r'C:\_Projects\PAT\PAT_Demo_internal\Sample_Data',
            filter=self.tr("Delimited files") + " (*.csv *.txt);;")
                   # + self.tr("Spreadsheet files") + " (*.ods *.xls *.xlsx);;"
                   # + self.tr("GDAL Virtual Format") + " (*.vrt);;")

        if type(s) == tuple:
            s = s[0]

        if s == '':
            return

        
        self.lneInCSVFile.setText(s)
        
        
    @QtCore.pyqtSlot(int)
    def on_spnIgnoreRows_valueChanged(self, value):
        self.loadTablePreview()

    @QtCore.pyqtSlot(int)
    def on_spnHeaderRow_valueChanged(self, value):
        self.loadTablePreview()

    @QtCore.pyqtSlot(int)
    def on_spnPreviewRowCount_valueChanged(self, value):
        self.loadTablePreview()

    def on_mCRSoutput_clicked(self):
        # https://gis-ops.com/qgis-3-plugin-tutorial-plugin-development-explained-part-1/
        projSelector = QgsProjectionSelectionWidget()
        projSelector.selectCrs()
        try:
            authid = projSelector.crs().authid()
            description = projSelector.crs().description()
            self.crs = projSelector.crs()
            success = projSelector.crs()
            if not success:
                self.crs = None
            else:
                self.crsDesc.setText(description)
                self.form_crsID.setText(authid)
        except:
            self.crs = None

        print(projSelector.crs().authid() + projSelector.crs().description())


    @QtCore.pyqtSlot(name='on_cmdSaveCSVFile_clicked')
    def on_cmdSaveCSVFile_clicked(self):

        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        # start building a filename
        if self.optLayer.isChecked():
            lyrTarget = self.mcboTargetLayer.currentLayer()
            filename = lyrTarget.name()
        else:
            filename = os.path.splitext(os.path.basename(self.lneInCSVFile.text()))[0]

        # convert field name to something meaningful if it contains invalid chars, ie degC
        fld = unidecode(self.processField())

        # remove field from filename, then addit according to the naming convention to avoid duplications.
        # flags=re.I is for a case insensitive find and replace
        try:
            # this triggers and error if an invalid character is in the field ie ')'
            filename = re.sub(fld, '', filename, flags=re.I)
        except:
            pass

        # and again with invalid characters removed. Only allow alpha-numeric Underscores and hyphens
        fld = re.sub('[^A-Za-z0-9_-]+', '', fld)
        filename = re.sub(fld, '', filename)

        # and again with the field truncated to 10 chars
        fld = fld[:10]
        filename = re.sub(fld, '', filename)

        # add the chosen field name to the filename
        filename = '{}_{}_normtrimmed.csv'.format(filename, fld)

        # replace more than one instance of underscore with a single one.
        # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
        filename = re.sub(r"_+", "_", filename)

        s = save_as_dialog(self, self.tr("Save As"),
                           self.tr("Comma Delimited") + " (*.csv);;",
                           default_name=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lneSaveCSVFile.setText(s)

        if file_in_use(s):
            self.lneSaveCSVFile.setStyleSheet('color:red')
            self.lblSaveCSVFile.setStyleSheet('color:red')
        else:
            self.lblSaveCSVFile.setStyleSheet('color:black')
            self.lneSaveCSVFile.setStyleSheet('color:black')
            write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdSavePointsFile_clicked')
    def on_cmdSavePointsFile_clicked(self):

        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        fld = re.sub('[^A-Za-z0-9_-]+', '', unidecode(self.processField()))[:10]

        if self.lneSaveCSVFile.text() == '':

            if self.optLayer.isChecked():
                lyrTarget = self.mcboTargetLayer.currentLayer()
                filename = lyrTarget.name() + '_{}_normtrimmed.shp'.format(fld)
            else:
                filename = self.lneLayerName.text() + '_{}_normtrimmed.shp'.format(fld)
        else:
            filename = os.path.splitext(self.lneSaveCSVFile.text())[0]

        # replace more than one instance of underscore with a single one.
        # ie'file____norm__control___yield_h__' to 'file_norm_control_yield_h_'
        filename = re.sub(r"_+", "_", filename)

        s = save_as_dialog(self, self.tr("Save As"),
                           self.tr("ESRI Shapefile") + " (*.shp);;",
                           default_name=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)

        self.chkSavePointsFile.setChecked(True)
        self.lneSavePointsFile.setEnabled(self.chkSavePointsFile.isChecked())
        self.lneSavePointsFile.setText(s)
        self.chkSavePointsFile.setStyleSheet('color:black')
        self.lblSaveCSVFile.setStyleSheet('color:black')

        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    def processField(self):
        index = self.cboProcessField.currentIndex()
        if index == -1:
            return ''
        return self.cboProcessField.itemData(index, QtCore.Qt.EditRole)

    def update_prev_next_buttons(self):
        i = self.stackedWidget.currentIndex()
        self.cmdBack.setEnabled(i > 0)

    def resetFormToDefaults(self):
        for name, obj in inspect.getmembers(self):
            if isinstance(obj, QSpinBox):
                obj.setValue( self.default_vals[obj.objectName()])

    def csv_properties(self, csv_file):
        detector = chardet.UniversalDetector()
        with open(csv_file, 'rb') as eaop:
            for line in eaop.readlines(100):
                detector.feed(line)
                if detector.done:
                    break
            detector.close()

        try:
            with open(csv_file, 'r', newline='', encoding=detector.result['encoding']) as f:
                file_subset = f.read(10240)
        except:
            with open(csv_file, 'rb') as f:
                # sniff into 10KB of the file to check its dialect
                # this will sort out the delimiter and quote character.
                file_subset = f.read(10240)

        csvDialect = csv.Sniffer().sniff(file_subset)
        hasFieldHeader = csv.Sniffer().has_header(file_subset)

        # read header based on the 10k of file.
        self.chkHasHeader.setChecked(hasFieldHeader)
        self.source_file = {'file': csv_file,
                            'dialect': csvDialect,
                            'encoding': detector.result['encoding'],
                            'has_header': hasFieldHeader,
                            'field_types': {},
                            }
    def loadTablePreview(self):
        # # build a dictionary of args dependent on form selections
        readArgs = {}
        readArgs['encoding'] = self.source_file['encoding']

        if not self.chkHasHeader.isChecked():
            readArgs['header'] = None
            readArgs['prefix'] = 'col_'
        else:
            if self.spnHeaderRowStart.value() > 1:
                readArgs['header'] = list(range(self.spnHeaderRowStart.value() - 1,
                                                self.spnHeaderRowEnd.value()))

        if self.spnIgnoreRows.value() > 0:
            readArgs['skiprows'] = range(self.spnHeaderRowEnd.value(),
                                         self.spnHeaderRowEnd.value() + self.spnIgnoreRows.value())

        # if the table has already been read once before then we have the field types and
        # dont need to load the entire table which will speed things up
        if len(self.source_file['field_types']) > 0:
            readArgs['nrows'] = self.spnPreviewRowCount.value()
            readArgs['dtype'] = self.source_file['field_types']

        if self.source_file['dialect'].delimiter == ',':
            df = pd.read_csv(self.source_file['file'], **readArgs)
        else:
            readArgs['sep'] = self.source_file['dialect'].delimiter
            df = pd.read_table(self.source_file['file'], **readArgs)

        if len(self.source_file['field_types']) == 0:
            self.source_file['field_types'] = df.dtypes.to_dict()
            df = df[:self.spnPreviewRowCount.value()]

        model = PandasModel(df)
        self.tvwSample.setModel(model)

        # #https://centaurialpha.github.io/resize-qheaderview-to-contents-and-interactive
        #self.tvwSample.horizontalHeader().setResizeMode(QHeaderView.ResizeToContents)
        
        # get numeric fields
        #df.select_dtypes(include=np.number).columns.tolist()
        #df.select_dtypes('number').columns
        coord_cols = predictCoordinateColumnNames(df.columns.tolist())

        for i,obj in enumerate([self.cboXField,self.cboYField]):
            obj.clear()
            obj.addItems([' '] + df.select_dtypes('number').columns.tolist())
            index = obj.findText(coord_cols[i], QtCore.Qt.MatchFixedString)
            if index >= 0:
                obj.setCurrentIndex(index)
        
        self.cboProcessField.clear()
        self.cboProcessField.addItems([' '] + df.select_dtypes('number').columns.tolist())


    def getOutputCRS(self):
        if not self.chkAutoCRS.isChecked():
            return
        out_crs= QgsCoordinateReferenceSystem()
        if self.optLayer.isChecked():
            if not self.mcboTargetLayer.currentLayer():
                return
            layer = self.mcboTargetLayer.currentLayer()
            if layer.crs().isGeographic():
                out_crs = get_UTM_Coordinate_System(layer.extent().xMinimum(),
                                                           layer.extent().yMinimum(),
                                                           layer.crs().authid())
            else:
                out_crs = layer.crs()
        else:

            df = self.tvwSample.model()._dataFrame
            
            x = float(df[self.cboXField.currentText()].min())
            y = float(df[self.cboYField.currentText()].min())

            out_crs = get_UTM_Coordinate_System(x,y, self.qgsCRScsv.crs().authid())
        
        
        if out_crs:
            try:
                self.mCRSoutput.setCrs(out_crs)
            except:
                self.lblOutCRS.setText('Unspecified')

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.cleanMessageBars(AllBars=True)
            errorList = []

            widget_page = self.stackedWidget.currentWidget().objectName()
            widget_idx = self.stackedWidget.currentIndex() + 1

            if widget_page =='pgeSource' or widget_idx == self.stackedWidget.count():
                if self.optFile.isChecked():
                    if self.lneInCSVFile.text()== '':
                        self.optFile.setStyleSheet('color:red')
                        errorList.append(self.tr("Select an input file"))
                    else:
                        self.optLayer.setStyleSheet('color:black')
                        self.optFile.setStyleSheet('color:black')
                else:
                    targetLayer = self.mcboTargetLayer.currentLayer()
                    if targetLayer is None or self.mcboTargetLayer.currentLayer().name() == '':
                        self.optLayer.setStyleSheet('color:red')
                        errorList.append(self.tr("Select a layer"))
                    else:
                        self.optLayer.setStyleSheet('color:black')
                        self.optFile.setStyleSheet('color:black')

            if widget_page == 'pgeFromFile' or widget_idx == self.stackedWidget.count():
                if self.optFile.isChecked():
                    if self.cboXField.currentText() == ' ':
                        self.lblXField.setStyleSheet('color:red')
                        errorList.append(self.tr("Select an x field"))
                    else:
                        self.lblXField.setStyleSheet('color:black')

                    if self.cboYField.currentText() == ' ':
                        self.lblYField.setStyleSheet('color:red')
                        errorList.append(self.tr("Select an y field"))
                    else:
                        self.lblYField.setStyleSheet('color:black')

                    if self.qgsCRScsv.crs().isValid():
                        self.lblInCRSTitle.setStyleSheet('color:black')
                    else:
                        self.lblInCRSTitle.setStyleSheet('color:red')
                        errorList.append(self.tr("Select coordinate system for geometry fields"))

            if widget_page == 'pgeParameters' or widget_idx == self.stackedWidget.count():
                if self.cboProcessField.currentText() == ' ':
                    self.lblProcessField.setStyleSheet('color:red')
                    errorList.append(self.tr("Select a field to process"))
                else:
                    self.lblProcessField.setStyleSheet('color:black')

            if widget_page == 'pgeOutput' or widget_idx == self.stackedWidget.count() :
                if self.mCRSoutput.crs().isValid():
                    if self.mCRSoutput.crs().isGeographic():
                        self.lblOutCRSTitle.setStyleSheet('color:red')
                        self.mCRSoutput.setStyleSheet('color:red')
                        errorList.append(self.tr("Select output projected coordinate system (not geographic)"))
                    else:
                        self.lblOutCRSTitle.setStyleSheet('color:black')
                        self.mCRSoutput.setStyleSheet('color:black')
                else:
                    self.lblOutCRSTitle.setStyleSheet('color:red')
                    self.mCRSoutput.setStyleSheet('color:red')
                    errorList.append(self.tr("Select output projected coordinate system"))

                if self.lneSaveCSVFile.text() == '':
                    self.lneSaveCSVFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Enter output CSV file"))
                elif not os.path.exists(os.path.dirname(self.lneSaveCSVFile.text())):
                    self.lneSaveCSVFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Output CSV folder cannot be found"))
                elif os.path.exists(self.lneSaveCSVFile.text()) and file_in_use(self.lneSaveCSVFile.text(), False):
                    self.lneSaveCSVFile.setStyleSheet('color:red')
                    self.lblSaveCSVFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Output file {} is open in QGIS or another application".format(
                        os.path.basename(self.lneSaveCSVFile.text()))))
                else:
                    self.lblSaveCSVFile.setStyleSheet('color:black')
                    self.lneSaveCSVFile.setStyleSheet('color:black')

                if self.chkSavePointsFile.isChecked():
                    if self.lneSavePointsFile.text() == '':
                        self.chkSavePointsFile.setStyleSheet('color:red')
                        errorList.append(self.tr("Enter output points shapefile file"))
                    elif not os.path.exists(os.path.dirname(self.lneSavePointsFile.text())):
                        self.lneSavePointsFile.setStyleSheet('color:red')
                        errorList.append(self.tr("Output shapefile folder cannot be found"))
                    else:
                        self.chkSavePointsFile.setStyleSheet('color:black')
                        self.lneSavePointsFile.setStyleSheet('color:black')
                else:
                    self.chkSavePointsFile.setStyleSheet('color:black')
                    self.lneSavePointsFile.setStyleSheet('color:black')

            if len(errorList) > 0:
                raise ValueError(errorList)

            return True

        except ValueError as e:
            self.cleanMessageBars(True)
            if len(errorList) > 0:
                for i, ea in enumerate(errorList):
                    self.send_to_messagebar(str(ea), level=Qgis.Warning, duration=(i + 1) * 5)

                return False


    def accept(self, *args, **kwargs):
        if not self.validate():
            return False

        try:
            # disable form via a frame, this will still allow interaction with the message bar
            self.stackedWidget.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)
            # self.iface.messageBar().clearWidgets()

            # Change cursor to Wait cursor
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)

            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))
            self.send_to_messagebar("Please wait.. QGIS will be locked... See log panel for progress.",
                                    level=Qgis.Warning,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            if self.optFile.isChecked():
                settingsStr += '\n    {:30}\t{}'.format('File:', self.lneInCSVFile.text())
                settingsStr += '\n    {:30}\t{}, {}'.format('Geometry Fields:', self.cboXField.currentText(), 
                                                            self.cboYField.currentText())
                settingsStr += '\n    {:30}\t{} - {}'.format('CSV Coordinate System:', self.qgsCRScsv.crs().authid(),
                                                              self.qgsCRScsv.crs().description())
            else:
                if self.chkUseSelected.isChecked():
                    settingsStr += '\n    {:30}\t{} with {} selected features'.format('Layer:',
                                                                                      self.mcboTargetLayer.currentLayer().name(),
                                                                                      self.mcboTargetLayer.currentLayer().selectedFeatureCount())
                else:
                    settingsStr += '\n    {:30}\t{}'.format('Layer:', self.mcboTargetLayer.currentLayer().name())

            settingsStr += '\n    {:30}\t{}'.format('Process Field:', self.processField())

            if self.chkClipToPoly.isChecked():
                if self.chkUseSelected_ClipPoly.isChecked():
                    settingsStr += '\n    {:30}\t{} with {} selected features'.format('Clip Layer:',
                                                                                      self.mcboClipPolyLayer.currentLayer().name(),
                                                                                      self.mcboClipPolyLayer.currentLayer().selectedFeatureCount())
                else:
                    settingsStr += '\n    {:30}\t{}'.format('Clip Layer:', self.mcboClipPolyLayer.currentLayer().name())

            points_clean_shp = None
            points_remove_shp = None
            gp_layer_name = ''

            if self.chkSavePointsFile.isChecked():
                points_clean_shp = self.lneSavePointsFile.text()
                if 'norm_trim' in os.path.basename(points_clean_shp):
                    points_remove_shp = self.lneSavePointsFile.text().replace('_normtrimmed', '_removedpts')
                else:
                    points_remove_shp = self.lneSavePointsFile.text().replace('.shp', '_removedpts.shp')

                settingsStr += '\n    {:30}\t{}'.format('Saved Points:', points_clean_shp)
                settingsStr += '\n    {:30}\t{}'.format('Saved Removed Points:', points_remove_shp)

            elif self.DEBUG:
                gp_layer_name = 'DEBUG'
                points_clean_shp = os.path.join(TEMPDIR,
                                                os.path.basename(self.lneSaveCSVFile.text().replace('.csv', '.shp')))
                points_remove_shp = os.path.join(TEMPDIR, os.path.basename(
                    self.lneSaveCSVFile.text().replace('.csv', '_removepts.shp')))

            settingsStr += '\n    {:30}\t{}m'.format('Thinning Distance:', self.dsbThinDist.value())
            settingsStr += '\n    {:30}\t{}'.format('Remove Zeros:', self.chkRemoveZero.isChecked())
            settingsStr += '\n    {:30}\t{}'.format("Standard Devs to Use:", self.dsbStdCount.value())
            settingsStr += '\n    {:30}\t{}'.format("Trim Iteratively:", self.chkIterate.isChecked())

            settingsStr += '\n    {:30}\t{}'.format('Output CSV File:', self.lneSaveCSVFile.text())
            settingsStr += '\n    {:30}\t{} - {}\n\n'.format('Output Projected Coordinate System:',
                                                              self.mCRSoutput.crs().authid(),
                                                              self.mCRSoutput.crs().description())
                            

            LOGGER.info(settingsStr)
            stepTime = time.time()

            if self.optFile.isChecked():
                in_epsg = int(self.qgsCRScsv.crs().authid().replace('EPSG:',''))
                in_crs = self.qgsCRScsv.crs()
            else: 
                in_epsg =self.mcboTargetLayer.currentLayer().crs().authid().replace('EPSG:','')
                in_crs = self.mcboTargetLayer.currentLayer().crs()
                
            out_epsg = int(self.mCRSoutput.crs().authid().replace('EPSG:',''))
            
            filePoly = None

            if self.chkClipToPoly.isChecked():
                lyrPlyTarget = self.mcboClipPolyLayer.currentLayer()

                if self.chkUseSelected_ClipPoly.isChecked():

                    savePlyName = lyrPlyTarget.name() + '_poly.shp'
                    filePoly = os.path.join(TEMPDIR, savePlyName)
                    if os.path.exists(filePoly):  removeFileFromQGIS(filePoly)

                    QgsVectorFileWriter.writeAsVectorFormat(lyrPlyTarget, filePoly,'utf-8',
                                                            driverName='ESRI Shapefile',onlySelected=True)

                    LOGGER.info('{:<30} {d:<15} {}'.format('Save Clip Polygon layer selection to file', filePoly,
                                                         d=str(timedelta(seconds=time.time() - stepTime))))

                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoly, layer_name=os.path.splitext(os.path.basename(filePoly))[0]
                                            , group_layer_name='DEBUG', atTop=True)

                else:
                    filePoly = lyrPlyTarget.source()

            gdfPoints = None
            filePoints = None
            stepTime = time.time()
            if self.optFile.isChecked():

                if self.DEBUG:
                    filePoints = os.path.join(TEMPDIR, os.path.splitext(os.path.basename(self.lneSaveCSVFile.text()))[0] + '_table2pts.shp')

                if os.path.splitext(self.lneInCSVFile.text())[-1] == '.csv':
                    gdfPoints, gdfPtsCrs = convert.convert_csv_to_points(self.lneInCSVFile.text() , out_shapefilename=filePoints,
                                                                         coord_columns=[self.cboXField.currentText(),
                                                                                        self.cboYField.currentText()],
                                                                         coord_columns_epsg=in_epsg)

                elif os.path.splitext(self.lneInCSVFile.text())[-1] in ['.xls', '.xlsx', '.ods']:
                    xls_file = pd.ExcelFile(self.lneInCSVFile.text())
                    pdfxls = xls_file.parse(self.sheet(), skiprows=self.linesToIgnore() - 1)
                    del xls_file

                    gdfPoints, gdfPtsCrs = convert.add_point_geometry_to_dataframe(pdfxls,
                                                                                   coord_columns=[
                                                                                       self.cboXField.currentText(),
                                                                                       self.cboYField.currentText()],
                                                                                   coord_columns_epsg=in_epsg)
                    del pdfxls

                LOGGER.info('{:<30} {d:<15} {}'.format('Add Geometry to Table',filePoints,
                                                          d=str(timedelta(seconds=time.time() - stepTime))))
                stepTime = time.time()

                if filePoints is not None:
                    describe.save_geopandas_tofile(gdfPoints, filePoints) #, file_encoding=self.file_encoding)


                if self.DISP_TEMP_LAYERS and filePoints != '':
                    addVectorFileToQGIS(filePoints, layer_name=os.path.splitext(os.path.basename(filePoints))[0],
                                        group_layer_name='DEBUG', atTop=True)

            else:
                layerPts = self.mcboTargetLayer.currentLayer()

                if layerPts.providerType() == 'delimitedtext' or \
                        os.path.splitext(layerPts.source())[-1] == '.vrt' or \
                        self.chkUseSelected.isChecked() or self.optFile.isChecked():

                    filePoints = os.path.join(TEMPDIR, "{}_points.shp".format(layerPts.name()))

                    if self.chkUseSelected.isChecked():
                        filePoints = os.path.join(TEMPDIR, "{}_selected_points.shp".format(layerPts.name()))

                    if os.path.exists(filePoints):
                        removeFileFromQGIS(filePoints)

                    ptsLayer = copyLayerToMemory(layerPts, layerPts.name() + "_memory", bAddUFI=True,
                                                 bOnlySelectedFeat=self.chkUseSelected.isChecked())

                    _writer = QgsVectorFileWriter.writeAsVectorFormat(ptsLayer, filePoints, "utf-8",
                                                                      self.mCRSoutput.crs(), driverName="ESRI Shapefile")

                    # reset field to match truncated field in the saved shapefile.
                    shpField = re.sub('[^A-Za-z0-9_-]+', '', self.cboProcessField.currentText())[:10]

                    idx = self.cboProcessField.findText(shpField)
                    if idx == -1:
                        self.cboProcessField.addItem(shpField)
                        idx = self.cboProcessField.findText(shpField)
                        
                    self.cboProcessField.setCurrentIndex(idx)

                    del ptsLayer

                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoints, layer_name=os.path.splitext(os.path.basename(filePoints))[0],
                                            group_layer_name='DEBUG', atTop=True)

                else:
                    filePoints = layerPts.source()

            if gdfPoints is None:
                ptsDesc = describe.VectorDescribe(filePoints)
                gdfPtsCrs = ptsDesc.crs
                gdfPoints = ptsDesc.open_geo_dataframe()

            if in_crs.authid() != self.mCRSoutput.crs().authid():
                
                gdfPoints = gdfPoints.to_crs(epsg=out_epsg)
                gdfPtsCrs = pyprecag_crs.crs()
                gdfPtsCrs.getFromEPSG(out_epsg)

                if self.DEBUG:
                    filePoints = os.path.join(TEMPDIR, os.path.basename(
                        self.lneSaveCSVFile.text().replace('.csv', '_ptsprj.shp')))
                    removeFileFromQGIS(filePoints)
                    describe.save_geopandas_tofile(gdfPoints, filePoints)
                    if self.DISP_TEMP_LAYERS:
                        if self.DEBUG:
                            addVectorFileToQGIS(filePoints,
                                                layer_name=os.path.splitext(os.path.basename(filePoints))[0],
                                                group_layer_name='DEBUG', atTop=True)
                        else:
                            addVectorFileToQGIS(filePoints,
                                                layer_name=os.path.splitext(os.path.basename(filePoints))[0],
                                                atTop=True)

            _ = processing.clean_trim_points(gdfPoints, gdfPtsCrs, self.processField(),
                                             output_csvfile=self.lneSaveCSVFile.text(), boundary_polyfile=filePoly,
                                             out_keep_shapefile=points_clean_shp,
                                             out_removed_shapefile=points_remove_shp,
                                             thin_dist_m=self.dsbThinDist.value(),
                                             remove_zeros=self.chkRemoveZero.isChecked(),
                                             stdevs=self.dsbStdCount.value(),
                                             iterative=self.chkIterate.isChecked())

            if points_clean_shp is not None and points_clean_shp != '':
                lyrFilter = addVectorFileToQGIS(points_clean_shp,
                                                layer_name=os.path.basename(os.path.splitext(points_clean_shp)[0]),
                                                atTop=True, group_layer_name=gp_layer_name)

            if points_remove_shp is not None and points_remove_shp != '':
                lyrRemoveFilter = addVectorFileToQGIS(points_remove_shp, 
                                                      layer_name=os.path.basename(os.path.splitext(points_remove_shp)[0]),
                                                      atTop=True, group_layer_name=gp_layer_name)

                vector_apply_unique_value_renderer(lyrRemoveFilter, 'filter')

            self.cleanMessageBars(True)
            self.stackedWidget.setDisabled(False)
            QApplication.restoreOverrideCursor()
            self.iface.messageBar().popWidget()
            self.iface.mainWindow().statusBar().clearMessage()

            return super(CleanTrimPointsDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.stackedWidget.setDisabled(False)

            self.send_to_messagebar(str(err), level=Qgis.Critical,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
