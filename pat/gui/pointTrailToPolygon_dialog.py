# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 PointTrailToPolygonDialog -  Create a polygon from a Point Trail created
 from a file containing GPS coordinates.

           -------------------
        begin      : 2017-05-25
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

import datetime
import logging
import os
import re
import shutil
import sys
import time
import traceback

import chardet
import pandas as pd
from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR, PLUGIN_SHORT
from PyQt4 import QtCore, QtGui, uic
from PyQt4.QtGui import QPushButton
from osgeo import ogr
from qgis.core import (QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsMessageLog)
from qgis.gui import QgsMessageBar, QgsGenericProjectionSelector
from unidecode import unidecode

from pyprecag import processing, crs as pyprecag_crs, config, convert, describe
from util.custom_logging import errorCatcher, openLogPanel
from util.gdal_util import GDAL_COMPAT
from util.qgis_common import copyLayerToMemory, removeFileFromQGIS, addVectorFileToQGIS, saveAsDialog
from util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


class FieldsModel(QtCore.QAbstractListModel):
    """FieldsModel provide a ListModel class to display fields in QComboBox.
    """

    def __init__(self, fields, parent=None):
        super(FieldsModel, self).__init__(parent)
        self._fields = fields

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._fields)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        field = self._fields[index.row()]
        if role == QtCore.Qt.DisplayRole:
            return field['name']
        if role == QtCore.Qt.EditRole:
            return field['src']


class OgrTableModel(QtGui.QStandardItemModel):
    """OgrTableModel provide a TableModel class
    for displaying OGR layers data.

    OGR layer is read at creation or by setLayer().
    All data are stored in parent QtCore.QStandardItemModel object.
    No reference to any OGR related object is kept.
    """

    def __init__(self, layer=None, fields=None, parent=None, maxRowCount=None):
        super(OgrTableModel, self).__init__(parent)
        self.maxRowCount = maxRowCount
        self.setLayer(layer)
        self.fields = fields

    def setLayer(self, layer):

        self.clear()
        if layer is None:
            return

        layerDefn = layer.GetLayerDefn()

        rows = min(layer.GetFeatureCount(), self.maxRowCount)
        columns = layerDefn.GetFieldCount()

        self.setRowCount(rows)
        self.setColumnCount(columns)

        # Headers
        for column in xrange(0, columns):
            fieldDefn = layerDefn.GetFieldDefn(column)
            fieldName = fieldDefn.GetNameRef().decode('UTF-8')
            item = QtGui.QStandardItem(fieldName)
            self.setHorizontalHeaderItem(column, item)

        # Lines
        for row in xrange(0, rows):
            for column in xrange(0, columns):
                layer.SetNextByIndex(row)
                feature = layer.GetNextFeature()
                item = self.createItem(layerDefn, feature, column)
                self.setItem(row, column, item)

        # No header for column format line
        for column in xrange(0, columns):
            item = QtGui.QStandardItem("")
            self.setVerticalHeaderItem(rows, item)

    def createItem(self, layerDefn, feature, iField):

        fieldDefn = layerDefn.GetFieldDefn(iField)

        value = None
        if fieldDefn.GetType() == ogr.OFTDate:
            if feature.IsFieldSet(iField):
                value = datetime.date(*feature.GetFieldAsDateTime(iField)[:3])
            hAlign = QtCore.Qt.AlignCenter

        elif fieldDefn.GetType() == ogr.OFTInteger:
            if feature.IsFieldSet(iField):
                value = feature.GetFieldAsInteger(iField)
            hAlign = QtCore.Qt.AlignRight

        elif fieldDefn.GetType() == ogr.OFTReal:
            if feature.IsFieldSet(iField):
                value = feature.GetFieldAsDouble(iField)
            hAlign = QtCore.Qt.AlignRight

        elif fieldDefn.GetType() == ogr.OFTString:
            if feature.IsFieldSet(iField):
                value = feature.GetFieldAsString(iField).decode('UTF-8')
            hAlign = QtCore.Qt.AlignLeft

        else:
            if feature.IsFieldSet(iField):
                value = feature.GetFieldAsString(iField).decode('UTF-8')
            hAlign = QtCore.Qt.AlignLeft

        if value is None:
            item = QtGui.QStandardItem(u'NULL')
            item.setForeground(QtGui.QBrush(QtCore.Qt.gray))
            font = item.font()
            font.setItalic(True)
            item.setFont(font)
        else:
            item = QtGui.QStandardItem(unicode(value))
        item.setTextAlignment(hAlign | QtCore.Qt.AlignVCenter)
        return item


ogrFieldTypes = []
for fieldType in [ogr.OFTInteger,
                  ogr.OFTIntegerList,
                  ogr.OFTReal,
                  ogr.OFTRealList,
                  ogr.OFTString,
                  ogr.OFTStringList,
                  # ogr.OFTWideString,
                  # ogr.OFTWideStringList,
                  #  ogr.OFTInteger64,
                  #  ogr.OFTInteger64List,
                  ogr.OFTBinary,
                  ogr.OFTDate,
                  ogr.OFTTime,
                  ogr.OFTDateTime]:
    ogrFieldTypes.append((fieldType, ogr.GetFieldTypeName(fieldType)))


class OgrFieldTypeDelegate(QtGui.QStyledItemDelegate):
    def __init__(self, parent=None):
        super(OgrFieldTypeDelegate, self).__init__(parent)

    def createEditor(self, parent, option, index):
        editor = QtGui.QComboBox(parent)
        for value, text in ogrFieldTypes:
            editor.addItem(text, value)
        editor.setAutoFillBackground(True)
        return editor

    def setEditorData(self, editor, index):
        if not editor:
            return
        edType = index.model().fields[index.column()]['type']
        editor.setCurrentIndex(editor.findData(edType))

    def setModelData(self, editor, model, index):
        if not editor:
            return
        edType = editor.itemData(editor.currentIndex())
        model.fields[index.column()]['type'] = edType


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pointTrailToPolygon_dialog_base.ui'))


class PointTrailToPolygonDialog(QtGui.QDialog, FORM_CLASS):
    """Dialg for create a polygon from a point trail created from a yield monitor file csv file."""

    toolKey = 'PointTrailToPolygonDialog'
    sampleRowCount = 20

    def __init__(self, iface, parent=None):

        super(PointTrailToPolygonDialog, self).__init__(iface.mainWindow())

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
        self.validationLayout = QtGui.QFormLayout(self)

        # Add the error messages to top of form via a message bar.
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts

        if isinstance(self.layout(), QtGui.QFormLayout):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # Set Class default variables -------------------------------------
        self.dataSource = None
        self.layer = None
        self.fields = None
        self.sampleDatasource = None
        self.lblOGRHeaders.setText('')
        self.inQgsCRS = None
        self.outQgsCRS = None
        self.currentFile = None

        # GUI Runtime Customisation -----------------------------------------------
        # Exclude services (WFS, WCS etc from list)
        # Source: https://gis.stackexchange.com/a/231792
        # python 2 solution....

        expected = []
        for layer in self.iface.legendInterface().layers():
            if hasattr(layer, 'providerType') and layer.providerType() not in ['ogr', 'delimitedtext']:
                expected.append(layer)

        self.mcboTargetLayer.setExceptedLayerList(expected)

        # python3 solution
        # providers = QgsProviderRegistry.instance().providerList()
        # providers.remove('WFS')
        # self.dlg.comboBox.setExcludedProviders( providers )

        # Setting Defaults
        if self.mcboTargetLayer.count() > 0:
            self.cgbFromLayer.setChecked(True)
            self.toggleSource()
            self.updateUseSelected()
        else:
            self.cgbFromLayer.setChecked(False)
            self.toggleSource()

        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_pointTrailToPolygon.svg'))
        self.gpbGeometry.setChecked(False)
        self.chkSavePointsFile.setChecked(False)
        self.sampleRefreshDisabled = False
        self.tvwSample.setItemDelegate(OgrFieldTypeDelegate())

        self.chkHeader.hide()
        self.chkEOFDetection.hide()

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

    def filePath(self):
        return self.currentFile

    def setFilePath(self, path):
        self.lneInCSVFile.setText(path)

    def verifyFile(self, file_name):
        """ This will check (verify) the file. If non-utf-8 characters are found (ie degree symbol, cubed symbol
        it will make a local copy in the project temp, then resolve the characters, and from then on use the corrected
        file.

        Args:
            file_name (str): The file to verify for invalid characters.

        Returns (str): The file to use.

        """

        result = file_name
        self.cleanMessageBars(True)
        dataSource = ogr.Open(file_name, 0)
        if dataSource is None:
            self.send_to_messagebar(u"Could not open file. Try loading as a Delimited Text Layer",
                                    level=QgsMessageBar.CRITICAL, duration=0,
                                    addToLog=True)
            return ''

        validFile = True

        for i in xrange(0, dataSource.GetLayerCount()):
            layer = dataSource.GetLayer(i)
            layerDefn = layer.GetLayerDefn()
            for iField in xrange(0, layerDefn.GetFieldCount()):
                fieldDefn = layerDefn.GetFieldDefn(iField)
                try:
                    src = fieldDefn.GetNameRef().decode('UTF-8')
                except:
                    validFile = False
                    break

        dataSource = None
        del layer, fieldDefn, dataSource
        if not validFile:
            tmpCopy = os.path.join(TEMPDIR, os.path.basename(file_name))
            self.send_to_messagebar('Invalid characters found in field names. Creating a temporary copy to resolve.',
                                    '', QgsMessageBar.WARNING, addToLog=True)
            self.fraMain.setDisabled(True)
            if not os.path.exists(tmpCopy):
                shutil.copy(file_name, tmpCopy)

            # make a copy using the driver
            dsNew = ogr.Open(tmpCopy, 1)
            iRenamedFields = 0
            # Loop through each layer
            for iLyr in xrange(0, dsNew.GetLayerCount()):
                layer = dsNew.GetLayer(iLyr)
                layerdef = layer.GetLayerDefn()
                # Loop through each field
                for iFld in xrange(0, layerdef.GetFieldCount()):

                    # rename the field name in the copy
                    # Source:https://github.com/stefanct/OGD_Wien_tools/blob/master/FAHRRADABSTELLANLAGEOGD.py
                    fieldDefn = layerdef.GetFieldDefn(iFld)
                    fieldName = fieldDefn.GetNameRef()
                    try:
                        encodeType = 'UTF-8'
                        tmp = fieldName.decode('UTF-8')
                    except:
                        try:
                            tmp = fieldName.decode('latin1', 'ignore')
                            encodeType = 'latin1'
                        except:
                            pass

                    # using unidecode, convert fieldnames to something meaningful
                    # ie the degree symbol to letters deg, or cubed symbol to 3
                    newName = unidecode(fieldName.decode(encodeType, 'ignore'))

                    if fieldName != newName:
                        iRenamedFields += 1
                        self.send_to_messagebar(
                            '     {}   to   {} using {}'.format(fieldName, str(newName), encodeType),
                            '', QgsMessageBar.WARNING, iRenamedFields * 5, addToLog=True)

                        # Make a copy of the definition
                        newFldDef = ogr.FieldDefn(fieldDefn.GetName(), fieldDefn.GetType())
                        newFldDef.SetWidth(fieldDefn.GetWidth())
                        newFldDef.SetPrecision(fieldDefn.GetPrecision())

                        # Change the name
                        newFldDef.SetName(str(newName))
                        layer.AlterFieldDefn(iFld, newFldDef, ogr.ALTER_NAME_FLAG)
                    else:
                        pass

            dsNew = None
            result = tmpCopy
        self.fraMain.setDisabled(False)
        return result

    def afterOpenFile(self):

        self.sampleRefreshDisabled = True

        self.openDataSource()
        self.update_Sheets()
        self.readVrt()

        self.sampleRefreshDisabled = False
        self.updatetvwSample()

    def layerName(self):
        return self.lneLayerName.text()

    def setLayerName(self, name):
        self.lneLayerName.setText(name)

    def closeDataSource(self):

        if self.dataSource is not None:
            self.dataSource = None
            self.update_Sheets()

    def openDataSource(self):

        self.closeDataSource()

        filePath = self.filePath()
        self.finfo = QtCore.QFileInfo(filePath)
        if not self.finfo.exists():
            return

        dataSource = ogr.Open(filePath, 0)
        if dataSource is None:
            self.messageBar.pushMessage(u"Could not open {}".format(filePath),
                                        QgsMessageBar.WARNING, 5)
        self.dataSource = dataSource

        if self.dataSource and self.dataSource.GetDriver().GetName() in ['XLS']:
            self.setEofDetection(True)
        else:
            self.setEofDetection(False)

    def closeSampleDatasource(self):

        if self.sampleDatasource is not None:
            self.sampleDatasource = None

    def openSampleDatasource(self):

        self.closeSampleDatasource()

        filePath = self.samplePath()
        finfo = QtCore.QFileInfo(filePath)
        if not finfo.exists():
            return False
        dataSource = ogr.Open(filePath, 0)
        if dataSource is None:
            self.messageBar.pushMessage(u"Could not open {}".format(filePath),
                                        QgsMessageBar.WARNING, 5)
        self.sampleDatasource = dataSource

    def sheet(self):
        return self.cboSheet.currentText()

    def setSheet(self, sheetName):
        self.cboSheet.setCurrentIndex(self.cboSheet.findText(sheetName))

    def update_Sheets(self):
        """Update the form sample for the cbosheet"""

        self.cboSheet.clear()
        dataSource = self.dataSource
        if dataSource is None:
            return

        for i in xrange(0, dataSource.GetLayerCount()):
            layer = dataSource.GetLayer(i)
            self.cboSheet.addItem(layer.GetName().decode('UTF-8'), layer)

        if self.cboSheet.count() > 1:
            self.setLayerName(u"{}-{}".format(self.finfo.completeBaseName(),
                                              self.cboSheet.currentText()))
        else:
            self.setLayerName(u"{}".format(self.finfo.completeBaseName()))

    @QtCore.pyqtSlot(int)
    def on_cboSheet_currentIndexChanged(self, index):

        if index is None:
            self.layer = None
        else:
            self.lblSheet.setStyleSheet('color:black')
            self.layer = self.cboSheet.itemData(index)
            if self.cboSheet.count() > 1:
                self.setLayerName(u"{}-{}".format(self.finfo.completeBaseName(),
                                                  self.cboSheet.itemText(index)))
            else:
                self.setLayerName(u"{}".format(self.finfo.completeBaseName()))

        self.countNonEmptyRows()
        self.updateFields()
        self.updateFieldBoxes()
        self.updatetvwSample()

    def linesToIgnore(self):
        return self.spnLinesToIgnore.value()

    def setLinesToIgnore(self, value):
        self.spnLinesToIgnore.setValue(value)

    @QtCore.pyqtSlot(int)
    def on_spnLinesToIgnore_valueChanged(self, value):
        self.updateFields()
        self.updateFieldBoxes()
        self.updatetvwSample()

    def header(self):
        return self.chkHeader.checkState() == QtCore.Qt.Checked

    def setHeader(self, value):
        self.chkHeader.setCheckState(QtCore.Qt.Checked if value else QtCore.Qt.Unchecked)

    @QtCore.pyqtSlot(name='on_cmdInFile_clicked')
    def on_cmdInFile_clicked(self):
        # Reset for new file....
        self.setInCrs('Unspecified')
        self.lneSavePolyFile.clear()
        self.lneSavePointsFile.clear()

        inFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder")
        if inFolder is None or not os.path.exists(inFolder):
            inFolder = read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER')

        # Reset the Message Box
        self.messageBar.clearWidgets()
        s = QtGui.QFileDialog.getOpenFileName(
            self, self.tr("Choose a spreadsheet file to open"),
            inFolder, self.tr("Delimited files") + " (*.csv *.txt);;"
                      + self.tr("Spreadsheet files") + " (*.ods *.xls *.xlsx);;"
                      + self.tr("GDAL Virtual Format") + " (*.vrt);;")

        s = os.path.normpath(s)
        self.currentFile = self.verifyFile(s)

        if self.currentFile == '':
            return

        self.cleanMessageBars(self)
        self.setFileEncoding(self.currentFile)
        self.lneInCSVFile.setText(self.currentFile)
        self.afterOpenFile()

        try:
            x = float(self.tvwSample.model().index(1, self.cboXField.currentIndex()).data())
            y = float(self.tvwSample.model().index(1, self.cboYField.currentIndex()).data())

            # if it looks like geographics then use gps default coordinate system of wgs84
            if abs(x) < 180 and abs(y) <= 90:
                self.setInCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
            else:
                self.setInCrs('Unspecified')
        except:
            self.setInCrs('Unspecified')

        self.setOutCRS()

        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastInFolder", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdSavePointsFile_clicked')
    def on_cmdSavePointsFile_clicked(self):

        # If the setting has been previously set use this.
        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        if self.cgbFromLayer.isChecked():
            lyrTarget = self.mcboTargetLayer.currentLayer()
            filename = lyrTarget.name() + '_points.shp'
        else:
            filename = self.lneLayerName.text() + '_points.shp'

        s = saveAsDialog(self, self.tr("Save Points As"),
                         self.tr("ESRI Shapefile") + " (*.shp);;",
                         defaultName=os.path.join(lastFolder, filename))
        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.chkSavePointsFile.setChecked(True)
        self.lneSavePointsFile.setText(s)
        self.chkSavePointsFile.setStyleSheet('color:black')
        self.lneSavePointsFile.setStyleSheet('color:black')
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdSavePolyFile_clicked')
    def on_cmdSavePolyFile_clicked(self):

        lastFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
        if lastFolder is None or not os.path.exists(lastFolder):
            lastFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        if self.cgbFromLayer.isChecked():
            lyrTarget = self.mcboTargetLayer.currentLayer()
            filename = lyrTarget.name() + '_polygon.shp'
        else:
            filename = self.lneLayerName.text() + '_polygon.shp'

        s = saveAsDialog(self, self.tr("Save Polygon As"),
                         self.tr("ESRI Shapefile") + " (*.shp);;",
                         defaultName=os.path.join(lastFolder, filename))

        if s == '' or s is None:
            return

        s = os.path.normpath(s)
        self.lneSavePolyFile.setText(s)
        self.lblSavePolyFile.setStyleSheet('color:black')
        self.lneSavePolyFile.setStyleSheet('color:black')
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", os.path.dirname(s))

    @QtCore.pyqtSlot(name='on_cmdInCRS_clicked')
    def on_cmdInCRS_clicked(self):

        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage('Select CRS for the input file geometry')
        if self.inQgsCRS is not None:
            dlg.setSelectedAuthId(self.inQgsCRS.authid())
        if dlg.exec_():
            if dlg.selectedAuthId() != '':  # ie clicked ok without selecting a projection
                self.setInCrs(QgsCoordinateReferenceSystem(dlg.selectedAuthId()))

    @QtCore.pyqtSlot(str)
    def on_lneInCRS_textChanged(self):
        self.setOutCRS()

    @QtCore.pyqtSlot(name='on_cmdOutCRS_clicked')
    def on_cmdOutCRS_clicked(self):

        dlg = QgsGenericProjectionSelector(self)
        dlg.setMessage('Select coordinate reference system for output files')
        if self.outQgsCRS is not None:
            dlg.setSelectedAuthId(self.outQgsCRS.authid())

        if dlg.exec_():
            if dlg.selectedAuthId() != '':  # ie clicked ok without selecting a projection
                self.outQgsCRS = QgsCoordinateReferenceSystem(dlg.selectedAuthId())
                self.chkAutoCRS.setChecked(False)
                self.setOutCRS()

    @QtCore.pyqtSlot(int)
    def on_chkAutoCRS_stateChanged(self, state):
        if self.chkAutoCRS.isChecked():
            self.setOutCRS()

    @QtCore.pyqtSlot(int)
    def on_chkEOFDetection_stateChanged(self, state):
        self.countNonEmptyRows()
        self.updatetvwSample()

    @QtCore.pyqtSlot(int)
    def on_chkHeader_stateChanged(self, state):
        self.updateFields()
        self.updateFieldBoxes()
        self.updatetvwSample()

    @QtCore.pyqtSlot(int)
    def on_chkSavePointsFile_stateChanged(self, state):
        self.lneSavePointsFile.setEnabled(state)

    @QtCore.pyqtSlot(name='on_lneInCSVFile_editingFinished')
    def on_lneInCSVFile_editingFinished(self):
        self.afterOpenFile()

    def on_cgbFromLayer_collapsedStateChanged(self):
        self.toggleSource()

    def on_cgbFromFile_collapsedStateChanged(self):
        self.toggleSource()

    @QtCore.pyqtSlot(name='on_cgbFromLayer_clicked')
    def on_cgbFromLayer_clicked(self):
        self.toggleSource()

    @QtCore.pyqtSlot(name='on_cgbFromFile_clicked')
    def on_cgbFromFile_clicked(self):
        self.cgbFromLayer.setChecked(not (self.cgbFromLayer.isChecked()))
        self.toggleSource()

    def on_mcboTargetLayer_layerChanged(self):
        self.updateUseSelected()

    def toggleSource(self):
        """Toggles or set collapse state of collapsible group box. """
        if self.cgbFromLayer.isChecked():
            self.cgbFromLayer.setCollapsed(False)  # Expand Layer group
            self.cgbFromFile.setCollapsed(True)  # Shrink File Group
            self.cgbFromFile.setChecked(False)  # Uncheck File Group
        else:
            self.cgbFromLayer.setCollapsed(True)
            self.cgbFromFile.setCollapsed(False)
            self.cgbFromFile.setChecked(True)
            self.setInCrs('Unspecified')

        self.chkHeader.hide()
        self.chkEOFDetection.hide()

    def offset(self):
        offset = self.linesToIgnore()
        if self.header():
            offset += 1
        return offset

    def setOffset(self, value):
        try:
            value = int(value)
        except:
            return False
        if self.header():
            value -= 1
        self.setLinesToIgnore(value)

    def limit(self):
        return self._non_empty_rows - self.offset()

    def eofDetection(self):
        return self.chkEOFDetection.checkState() == QtCore.Qt.Checked

    def setEofDetection(self, value):
        self.chkEOFDetection.setCheckState(QtCore.Qt.Checked if value else QtCore.Qt.Unchecked)

    def countNonEmptyRows(self):
        if self.layer is None:
            return
        if self.eofDetection():
            self._non_empty_rows = 0

            layer = self.layer
            layerDefn = layer.GetLayerDefn()
            layer.SetNextByIndex(0)
            feature = layer.GetNextFeature()
            current_row = 1
            while feature is not None:
                for iField in xrange(0, layerDefn.GetFieldCount()):
                    if feature.IsFieldSet(iField):
                        self._non_empty_rows = current_row

                feature = layer.GetNextFeature()
                current_row += 1
        else:
            self._non_empty_rows = self.layer.GetFeatureCount()

    def sql(self):
        sql = (u'SELECT * FROM \'{}\''
               u' LIMIT {} OFFSET {}'
               ).format(self.sheet(),
                        self.limit(),
                        self.offset())
        return sql

    def updateGeometry(self):

        if GDAL_COMPAT or self.offset() == 0:
            self.gpbGeometry.setEnabled(True)
            self.gpbGeometry.setToolTip('')
        else:
            self.gpbGeometry.setEnabled(False)
            msg = self.tr(u"Used GDAL version doesn't support VRT layers with sqlite dialect"
                          u" mixed with PointFromColumn functionality.\n"
                          u"For more information, consult the plugin documentation.")
            self.gpbGeometry.setToolTip(msg)

    def geometry(self):
        return (self.gpbGeometry.isEnabled()
                and self.gpbGeometry.isChecked())

    def xField(self):
        index = self.cboXField.currentIndex()
        if index == -1:
            return ''
        return self.cboXField.itemData(index, QtCore.Qt.EditRole)

    def setXField(self, fieldName):
        self.cboXField.setCurrentIndex(self.cboXField.findData(fieldName, QtCore.Qt.EditRole))

    def yField(self):
        index = self.cboYField.currentIndex()
        if index == -1:
            return ''
        return self.cboYField.itemData(index, QtCore.Qt.EditRole)

    def setYField(self, fieldName):
        self.cboYField.setCurrentIndex(self.cboYField.findData(fieldName, QtCore.Qt.EditRole))

    def updateFieldBoxes(self):
        if self.offset() > 0:
            pass

        if self.layer is None:
            self.cboXField.clear()
            self.cboYField.clear()
            return

        model = FieldsModel(self.fields)

        xField = self.xField()
        yField = self.yField()

        self.cboXField.setModel(model)
        self.cboYField.setModel(model)

        self.setXField(xField)
        self.setYField(yField)

        if self.xField() != '' and self.yField() != '':
            return

        self.tryFields("longitude", "latitude")
        self.tryFields("lon", "lat")
        self.tryFields("x", "y")

    def tryFields(self, xName, yName):
        if self.xField() == '':
            for i in xrange(0, self.cboXField.count()):
                xField = self.cboXField.itemText(i)
                if xField.lower().find(xName.lower()) != -1:
                    self.cboXField.setCurrentIndex(i)
                    break

        if self.yField() == '':
            for i in xrange(0, self.cboYField.count()):
                yField = self.cboYField.itemText(i)
                if yField.lower().find(yName.lower()) != -1:
                    self.cboYField.setCurrentIndex(i)
                    break

    def crs(self):
        return self.inQgsCRS.authid()

    def setInCrs(self, crs):
        if crs == 'Unspecified' or crs == '':
            self.inQgsCRS = None
            self.outQgsCRS = None
        else:
            self.inQgsCRS = QgsCoordinateReferenceSystem(crs)

        if self.inQgsCRS is None:
            self.lneInCRS.setText('Unspecified')
            self.lblOutCRS.setText('Unspecified')
        else:
            self.lneInCRS.setText('{}  -  {}'.format(self.inQgsCRS.description(), self.inQgsCRS.authid()))
            self.lneInCRS.setStyleSheet('color:black;background:transparent;')
            self.lblInCRSTitle.setStyleSheet('color:black')
            self.inQgsCRS.validate()
            self.setOutCRS()

    def setOutCRS(self):
        if self.chkAutoCRS.isChecked() and self.inQgsCRS is None:
            self.lblOutCRS.setText('Unspecified')
            self.outQgsCRS = None
            return

        if self.chkAutoCRS.isChecked():
            if self.cgbFromFile.isChecked():
                if self.inQgsCRS.geographicFlag():

                    # https://stackoverflow.com/questions/8157688/specifying-an-index-in-qtableview-with-pyqt
                    # QTableView.model().index(row, column).data()
                    try:
                        x = float(self.tvwSample.model().index(1, self.cboXField.currentIndex()).data())
                        y = float(self.tvwSample.model().index(1, self.cboYField.currentIndex()).data())
                        utm_crs = pyprecag_crs.getProjectedCRSForXY(x, y, self.inQgsCRS.authid().replace('EPSG:', ''))
                        self.outQgsCRS = QgsCoordinateReferenceSystem('EPSG:{}'.format(utm_crs.epsg_number))

                    except:
                        self.outQgsCRS = None
                        self.lblOutCRS.setText('Unspecified')
                else:
                    self.outQgsCRS = self.inQgsCRS

            elif self.cgbFromLayer.isChecked():
                lyrPtTarget = self.mcboTargetLayer.currentLayer()

                if lyrPtTarget.crs().geographicFlag():
                    utm_crs = pyprecag_crs.getProjectedCRSForXY(lyrPtTarget.extent().xMinimum(),
                                                                lyrPtTarget.extent().yMinimum(),
                                                                int(lyrPtTarget.crs().authid().replace('EPSG:', '')))

                    self.outQgsCRS = QgsCoordinateReferenceSystem('EPSG:{}'.format(utm_crs.epsg_number))
                else:
                    self.outQgsCRS = lyrPtTarget.crs()

        if self.outQgsCRS is not None:
            self.outQgsCRS.validate()
            self.lblOutCRS.setText('{}  -  {}'.format(self.outQgsCRS.description(), self.outQgsCRS.authid()))

            self.lblOutCRSTitle.setStyleSheet('color:black')
            self.lblOutCRS.setStyleSheet('color:black')

    def updatetvwSample(self):
        if self.sampleRefreshDisabled:
            return

        self.updateGeometry()

        if self.layer is not None:
            self.writeSampleVrt()
            self.openSampleDatasource()

        layer = None
        dataSource = self.sampleDatasource
        if dataSource is not None:
            for i in xrange(0, dataSource.GetLayerCount()):
                layer = dataSource.GetLayer(i)

        if layer is None:
            self.tvwSample.setModel(None)
            return

        self.tvwSample.reset()
        model = OgrTableModel(layer,
                              self.fields,
                              parent=self,
                              maxRowCount=self.sampleRowCount)
        self.tvwSample.setModel(model)

    def vrtPath(self):
        if self.cboSheet.count() > 1:
            vrtpth = u'{}.{}.vrt'.format(os.path.basename(self.filePath()), self.sheet())
        else:
            vrtpth = u'{}.vrt'.format(os.path.basename(self.filePath()))
        return os.path.join(TEMPDIR, vrtpth)

    def samplePath(self):
        filename = u'{}.tmp.vrt'.format(os.path.basename(self.filePath()))
        return os.path.join(TEMPDIR, filename)

    def readVrt(self):
        if self.dataSource is None:
            return False

        vrtPath = self.vrtPath()
        if not os.path.exists(vrtPath):
            return False

        in_file = QtCore.QFile(vrtPath)
        if not in_file.open(QtCore.QIODevice.ReadOnly | QtCore.QIODevice.Text):
            self.warning(u"Impossible to open VRT file {}".format(vrtPath))
            return False

        self.gpbGeometry.setChecked(False)

        try:
            self.readVrtStream(in_file)
        except Exception:
            self.warning("An error occurs during existing VRT file loading")
            return False

        finally:
            in_file.close()

        return True

    def readVrtStream(self, in_file):
        stream = QtCore.QXmlStreamReader(in_file)

        stream.readNextStartElement()
        if stream.name() == "OGRVRTDataSource":

            stream.readNextStartElement()
            if stream.name() == "OGRVRTLayer":
                self.setLayerName(stream.attributes().value("name"))

                while stream.readNext() != QtCore.QXmlStreamReader.EndDocument:
                    if stream.isComment():
                        text = stream.text()
                        pattern = re.compile(r"Header=(\w+)")
                        match = pattern.search(text)
                        if match:
                            self.setHeader(eval(match.group(1)))

                    if stream.isStartElement():
                        if stream.name() == "SrcDataSource":
                            # do nothing : datasource should be already set
                            pass

                        elif stream.name() == "SrcLayer":
                            text = stream.readElementText()
                            self.setSheet(text)
                            self.setOffset(0)

                        elif stream.name() == "SrcSql":
                            text = stream.readElementText()

                            pattern = re.compile(r"FROM '(.+)'")
                            match = pattern.search(text)
                            if match:
                                self.setSheet(match.group(1))

                            pattern = re.compile(r'OFFSET (\d+)')
                            match = pattern.search(text)
                            if match:
                                self.setOffset(int(match.group(1)))

                        elif stream.name() == "GeometryType":
                            self.gpbGeometry.setChecked(True)

                        elif stream.name() == "LayerSRS":
                            text = stream.readElementText()
                            self.setInCrs(text)

                        elif stream.name() == "GeometryField":
                            self.setXField(stream.attributes().value("x"))
                            self.setYField(stream.attributes().value("y"))

                        if not stream.isEndElement():
                            stream.skipCurrentElement()

            stream.skipCurrentElement()

        stream.skipCurrentElement()

    def updateFields(self):
        """Refreshes the list of field definitions."""

        if self.layer is None:
            self.fields = []
            return

        # Select header line
        if self.header() or self.offset() >= 1:
            self.layer.SetNextByIndex(self.offset() - 1)
            feature = self.layer.GetNextFeature()

        fields = []
        layerDefn = self.layer.GetLayerDefn()
        for iField in xrange(0, layerDefn.GetFieldCount()):
            fieldDefn = layerDefn.GetFieldDefn(iField)
            src = fieldDefn.GetNameRef().decode('UTF-8')
            name = src
            if self.header() or self.offset() >= 1:
                name = feature.GetFieldAsString(iField).decode('UTF-8') or name
            fields.append({'src': src,
                           'name': name,
                           'type': fieldDefn.GetType(),
                           'shapefile': re.sub('[^A-Za-z0-9_-]+', '', name)[:10]
                           })
        self.fields = fields

    def prepareVrt(self, sample=False, without_fields=False):
        """Create xml content for the vrt file.

        Args:
            sample (bool): Prepare for sample dataset as shown on the dialog. Defaults to False
            without_fields (bool):Include no fields. Defaults to False

        Returns (str): Contents of file
        """

        fileBuffer = QtCore.QBuffer()
        fileBuffer.open(QtCore.QBuffer.ReadWrite)

        stream = QtCore.QXmlStreamWriter(fileBuffer)
        stream.setAutoFormatting(True)
        stream.writeStartDocument()
        stream.writeStartElement("OGRVRTDataSource")

        stream.writeStartElement("OGRVRTLayer")
        stream.writeAttribute("name", self.layerName())

        stream.writeStartElement("SrcDataSource")
        if sample:
            stream.writeCharacters(self.filePath())
        elif os.path.dirname(self.filePath()) == os.path.dirname(self.vrtPath()):
            stream.writeAttribute("relativeToVRT", "1")
            stream.writeCharacters(os.path.basename(self.filePath()))
        else:
            stream.writeCharacters(self.filePath())
        stream.writeEndElement()

        stream.writeComment('Header={}'.format(self.header()))

        if self.offset() > 0 or self._non_empty_rows != self.layer.GetFeatureCount():
            stream.writeStartElement("SrcSql")
            stream.writeAttribute("dialect", "sqlite")
            stream.writeCharacters(self.sql())
            stream.writeEndElement()
        else:
            stream.writeStartElement("SrcLayer")
            stream.writeCharacters(self.sheet())
            stream.writeEndElement()

        if not without_fields:
            for field in self.fields:
                stream.writeStartElement("Field")
                stream.writeAttribute("name", field['name'])
                stream.writeAttribute("src", field['src'])
                stream.writeAttribute("type", ogr.GetFieldTypeName(field['type']))
                stream.writeEndElement()

        if not sample:
            stream.writeStartElement("GeometryType")
            stream.writeCharacters("wkbPoint")
            stream.writeEndElement()

            if self.crs():
                stream.writeStartElement("LayerSRS")
                stream.writeCharacters(self.inQgsCRS.authid())
                stream.writeEndElement()

            stream.writeStartElement("GeometryField")
            stream.writeAttribute("encoding", "PointFromColumns")
            stream.writeAttribute("x", self.xField())
            stream.writeAttribute("y", self.yField())
            stream.writeEndElement()

        stream.writeEndElement()  # OGRVRTLayer
        stream.writeEndElement()  # OGRVRTDataSource
        stream.writeEndDocument()

        fileBuffer.reset()
        content = fileBuffer.readAll()
        fileBuffer.close()

        return content

    def writeVrt(self):
        """Write the vrt file for whole dataset.

        Returns (bool): If file written successfully

        """

        content = self.prepareVrt()

        vrtPath = self.vrtPath()
        in_file = QtCore.QFile(vrtPath)
        if in_file.exists():
            QtCore.QFile.remove(vrtPath)

        if not in_file.open(QtCore.QIODevice.ReadWrite | QtCore.QIODevice.Text):
            self.warning(u"Impossible to open VRT file {}".format(vrtPath))
            return False

        in_file.write(content)
        in_file.close()
        return True

    def writeSampleVrt(self, without_fields=False):
        """ Create a vrt file for the sample data to load on the form.

        Args:
            without_fields (bool): Add all fields to vrt. Defaults to False

        Returns(bool): Successfully Written file

        """

        content = self.prepareVrt(sample=True,
                                  without_fields=without_fields)

        vrtPath = self.samplePath()
        in_file = QtCore.QFile(vrtPath)
        if in_file.exists():
            QtCore.QFile.remove(vrtPath)

        if not in_file.open(QtCore.QIODevice.ReadWrite | QtCore.QIODevice.Text):
            self.warning(u"Impossible to open VRT file {}".format(vrtPath))
            return False

        in_file.write(content)
        in_file.close()
        return True

    def updateUseSelected(self):
        """Update use selected checkbox if active layer has a feature selection"""

        self.chkUseSelected.setText('No features selected')
        self.chkUseSelected.setStyleSheet('font:regular')
        self.chkUseSelected.setEnabled(False)
        self.lneLayerName.setText('')

        if self.mcboTargetLayer.count() == 0:
            return

        lyrTarget = self.mcboTargetLayer.currentLayer()
        self.setInCrs(lyrTarget.crs())

        if len(lyrTarget.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(len(lyrTarget.selectedFeatures())))
            self.chkUseSelected.setStyleSheet('font:bold')
            self.chkUseSelected.setEnabled(True)

        self.lneLayerName.setText(lyrTarget.name())

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        try:
            self.cleanMessageBars(AllBars=True)
            errorList = []
            if self.cgbFromFile.isChecked():
                if self.dataSource is None:
                    self.lblInFile.setStyleSheet('color:red')
                    errorList.append(self.tr("Please select an input file"))
                else:
                    self.lblInFile.setStyleSheet('color:black')

                if self.layer is None:
                    self.lblSheet.setStyleSheet('color:red')
                    errorList.append(self.tr("Please select a sheet"))
                else:
                    self.lblSheet.setStyleSheet('color:black')

                if self.cboXField.currentText() == '':
                    self.lblXField.setStyleSheet('color:red')
                    errorList.append(self.tr("Please select an x field"))
                else:
                    self.lblXField.setStyleSheet('color:black')

                if self.cboYField.currentText() == '':
                    self.lblYField.setStyleSheet('color:red')
                    errorList.append(self.tr("Please select an y field"))
                else:
                    self.lblYField.setStyleSheet('color:black')

                if self.inQgsCRS is None:
                    self.lblInCRSTitle.setStyleSheet('color:red')
                    self.lneInCRS.setStyleSheet('color:red;background:transparent;')
                    errorList.append(self.tr("Select coordinate system for geometry fields"))
                else:
                    self.lblInCRSTitle.setStyleSheet('color:black')
                    self.lneInCRS.setStyleSheet('color:black;background:transparent;')

                if self.chkSavePointsFile.isChecked():
                    if self.lneSavePointsFile.text() == '':
                        self.chkSavePointsFile.setStyleSheet('color:red')
                        errorList.append(self.tr("Please enter an output points filename"))
                    elif not os.path.exists(os.path.dirname(self.lneSavePointsFile.text())):
                        self.lneSavePointsFile.setStyleSheet('color:red')
                        errorList.append(self.tr("Output point folder does not exist!"))
                else:
                    self.chkSavePointsFile.setStyleSheet('color:black')
                    self.lneSavePointsFile.setStyleSheet('color:black')

            if self.lneSavePolyFile.text() == '':
                self.lblSavePolyFile.setStyleSheet('color:red')
                errorList.append(self.tr("Please enter an output polygon filename"))
            elif not os.path.exists(os.path.dirname(self.lneSavePolyFile.text())):
                self.lneSavePolyFile.setStyleSheet('color:red')
                errorList.append(self.tr("Output polygon folder does not exist!"))
            else:
                self.lblSavePolyFile.setStyleSheet('color:black')
                self.lneSavePolyFile.setStyleSheet('color:black')

            if self.outQgsCRS is None:
                self.lblOutCRSTitle.setStyleSheet('color:red')
                self.lblOutCRS.setStyleSheet('color:red')
                errorList.append(self.tr("Select output projected coordinate system"))
            else:
                if self.outQgsCRS.geographicFlag():
                    self.lblOutCRSTitle.setStyleSheet('color:red')
                    self.lblOutCRS.setStyleSheet('color:red')
                    errorList.append(self.tr("Select output projected coordinate system (not geographic)"))
                else:
                    self.lblOutCRSTitle.setStyleSheet('color:black')
                    self.lblOutCRS.setStyleSheet('color:black')

            if len(errorList) > 0:
                raise ValueError(errorList)

        except ValueError as e:
            self.cleanMessageBars(True)
            if len(errorList) > 0:
                for i, ea in enumerate(errorList):
                    self.send_to_messagebar(unicode(ea), level=QgsMessageBar.WARNING, duration=(i + 1) * 5)
                return False
        return True

    def setFileEncoding(self, file_name):
        """Describe a CSV File and set class properties
                Sources:
                    https://chrisalbon.com/python/pandas_dataframe_importing_csv.html
                    https://pandas.pydata.org/pandas-docs/stable/generated/pandas.read_csv.html
                    https://www.nesono.com/node/414

                    Use sniffer to determine csv delimiters, quote characters etc.
                           see: http://www.programcreek.com/python/example/4089/csv.Sniffer
                    Sniffer requires a string, not a list of lines. so find the length of first line *100
                    to get multiple lines and use that.
                """
        detector = chardet.UniversalDetector()
        with open(file_name, 'rb') as eaop:
            for line in eaop.readlines(100):
                detector.feed(line)
                if detector.done:
                    break
            detector.close()

        self.file_encoding = detector.result['encoding']

    def accept(self, *args, **kwargs):
        if not self.validate():
            return False

        try:
            # disable form via a frame, this will still allow interaction with the message bar
            self.fraMain.setDisabled(True)
            self.cleanMessageBars(True)

            QtGui.qApp.setOverrideCursor(QtGui.QCursor(QtCore.Qt.WaitCursor))

            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))

            # Close the form before processing
            self.send_to_messagebar("Please wait. QGIS will be locked. See log panel for progress.", "Processing",
                                    level=QgsMessageBar.WARNING, duration=0, addToLog=False, showLogPanel=True)

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            if self.cgbFromFile.isChecked():
                settingsStr += '\n    {:30}\t{}'.format('File:', self.lneInCSVFile.text())
                settingsStr += '\n    {:30}\t{}, {}'.format('Geometry Fields:', self.xField(), self.yField())
                settingsStr += '\n    {:30}\t{}'.format('Coordinate System:', self.lneInCRS.text())
            else:
                if self.chkUseSelected.isChecked():
                    settingsStr += '\n    {:30}\t{} with {} selected features' \
                                   ''.format('Layer:', self.mcboTargetLayer.currentLayer().name(),
                                             len(self.mcboTargetLayer.currentLayer().selectedFeatures()))
                else:
                    settingsStr += '\n    {:30}\t{}'.format('Layer:', self.mcboTargetLayer.currentLayer().name())
                settingsStr += '\n    {:30}\t{}'.format('Coordinate System:', self.lneInCRS.text())

            if self.chkSavePointsFile.isChecked():
                settingsStr += '\n    {:30}\t{}'.format('Output Points File:', self.lneSavePointsFile.text())

            settingsStr += '\n    {:30}\t{}m'.format('Thinning Distance:', self.dsbThinDist.value())
            settingsStr += '\n    {:30}\t{}m'.format("Aggregate Distance", self.dsbAggregateDist.value())
            settingsStr += '\n    {:30}\t{}m'.format("Buffer Distance", self.dsbBufferDist.value())
            settingsStr += '\n    {:30}\t{}m'.format("Shrink Distance", self.dsbShrinkDist.value())

            settingsStr += '\n    {:30}\t{}'.format('Output Polygon File:', self.lneSavePolyFile.text())
            settingsStr += '\n    {:30}\t{}\n\n'.format('Output Projected Coordinate System:', self.lblOutCRS.text())

            LOGGER.info(settingsStr)
            layerPts = None
            gdfPoints = None
            stepTime = time.time()
            if self.cgbFromFile.isChecked():
                if not self.writeVrt():
                    return False

                if os.path.splitext(self.currentFile)[-1] == '.csv':
                    gdfPoints, gdfPtsCrs = convert.convert_csv_to_points(self.currentFile,
                                                                         coord_columns=[self.xField(), self.yField()],
                                                                         coord_columns_epsg=int(
                                                                             self.inQgsCRS.authid().replace('EPSG:',
                                                                                                            '')))

                elif os.path.splitext(self.currentFile)[-1] in ['.xls', '.xlsx', '.ods']:
                    xls_file = pd.ExcelFile(self.currentFile)
                    pdfxls = xls_file.parse(self.sheet(), skiprows=self.linesToIgnore() - 1)
                    del xls_file

                    gdfPoints, gdfPtsCrs = convert.add_point_geometry_to_dataframe(pdfxls,
                                                                                   coord_columns=[self.xField,
                                                                                                  self.yField],
                                                                                   coord_columns_epsg=int(
                                                                                       self.inQgsCRS.authid().replace(
                                                                                           'EPSG:', '')))
                    del pdfxls

                stepTime = time.time()

                if self.DISP_TEMP_LAYERS or self.DEBUG:
                    filePoints = os.path.join(TEMPDIR, os.path.basename(
                        self.lneSavePolyFile.text().replace('.shp', '_table2pts.shp')))
                    describe.save_geopandas_tofile(gdfPoints, filePoints, file_encoding=self.file_encoding)
                    LOGGER.info('{:<30} {:<15} {}'.format('Save To file',
                                                          datetime.timedelta(seconds=time.time() - stepTime),
                                                          filePoints))
                    stepTime = time.time()
                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoints, layer_name=os.path.basename(filePoints),
                                            group_layer_name='DEBUG', atTop=True)

            elif self.cgbFromLayer.isChecked():
                layerPts = self.mcboTargetLayer.currentLayer()

                if layerPts.providerType() == 'delimitedtext' or os.path.splitext(layerPts.source())[-1] == '.vrt' or \
                        self.chkUseSelected.isChecked() or self.cgbFromFile.isChecked():

                    filePoints = os.path.join(TEMPDIR, "{}_lyr2pts.shp".format(self.layerName()))

                    if self.chkUseSelected.isChecked():
                        filePoints = os.path.join(TEMPDIR, "{}_sel2pts.shp".format(self.layerName()))

                    if os.path.exists(filePoints):
                        removeFileFromQGIS(filePoints)

                    ptsLayer = copyLayerToMemory(layerPts, self.layerName() + "_memory", bAddUFI=True,
                                                 bOnlySelectedFeat=self.chkUseSelected.isChecked())

                    _writer = QgsVectorFileWriter.writeAsVectorFormat(ptsLayer, filePoints, "utf-8", self.inQgsCRS,
                                                                      "ESRI Shapefile")

                    LOGGER.info('{:<30} {:<15} {}'.format('Save layer/selection to file',
                                                          datetime.timedelta(seconds=time.time() - stepTime),
                                                          filePoints))
                    stepTime = time.time()

                    del ptsLayer

                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoints, group_layer_name='DEBUG', atTop=True)

                else:
                    filePoints = layerPts.source()

            if gdfPoints is None:
                ptsDesc = describe.VectorDescribe(filePoints)
                gdfPtsCrs = ptsDesc.crs
                gdfPoints = ptsDesc.open_geo_dataframe()

            if self.inQgsCRS.authid() != self.outQgsCRS.authid():
                epsgOut = int(self.outQgsCRS.authid().replace('EPSG:', ''))
                gdfPoints = gdfPoints.to_crs(epsg=epsgOut)
                gdfPtsCrs = pyprecag_crs.crs()
                gdfPtsCrs.getFromEPSG(epsgOut)
                LOGGER.info('{:<30} {d:<15} {}'.format('Reproject points', '',
                                                       d=datetime.timedelta(seconds=time.time() - stepTime)))
                stepTime = time.time()

                if self.chkSavePointsFile.isChecked():
                    filePoints = self.lneSavePointsFile.text()
                else:
                    filePoints = os.path.join(TEMPDIR, os.path.basename(
                        self.lneSavePolyFile.text().replace('.shp', '_ptsprj.shp')))

                if self.DISP_TEMP_LAYERS and self.DEBUG or self.chkSavePointsFile.isChecked():
                    removeFileFromQGIS(filePoints)
                    describe.save_geopandas_tofile(gdfPoints, filePoints)
                    LOGGER.info('{:<30} {:<15} {}'.format('Save to file',
                                                          datetime.timedelta(seconds=time.time() - stepTime),
                                                          filePoints))
                    stepTime = time.time()

                    if self.DISP_TEMP_LAYERS:
                        if self.DEBUG:
                            addVectorFileToQGIS(filePoints, group_layer_name='DEBUG', atTop=True)
                        else:
                            addVectorFileToQGIS(filePoints, atTop=True)

            # secondly create boundary from points.
            removeFileFromQGIS(self.lneSavePolyFile.text())

            result = processing.create_polygon_from_point_trail(gdfPoints, gdfPtsCrs,
                                                                out_filename=self.lneSavePolyFile.text(),
                                                                thin_dist_m=self.dsbThinDist.value(),
                                                                aggregate_dist_m=self.dsbAggregateDist.value(),
                                                                buffer_dist_m=self.dsbBufferDist.value(),
                                                                shrink_dist_m=self.dsbShrinkDist.value())

            addVectorFileToQGIS(self.lneSavePolyFile.text(), atTop=True)

            self.cleanMessageBars(True)
            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            if result is not None:
                self.fraMain.setDisabled(False)
                self.send_to_messagebar(result, level=QgsMessageBar.WARNING, duration=0, addToLog=False)
                return False  # leave dialog open

            return super(PointTrailToPolygonDialog, self).accept(*args, **kwargs)

        except Exception as err:
            QtGui.qApp.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=QgsMessageBar.CRITICAL, duration=0, addToLog=True,
                                    showLogPanel=True, exc_info=sys.exc_info())

            return False  # leave dialog open
