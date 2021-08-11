# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin

  ResampleImageBandDialog - Extract statistics from a list of rasters at set locations.
           -------------------
        begin      : 2018-09-24
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

from pat import LOGGER_NAME, PLUGIN_NAME, TEMPDIR
from util.custom_logging import errorCatcher, openLogPanel
from util.qgis_common import save_as_dialog, file_in_use, removeFileFromQGIS, \
    copyLayerToMemory, addVectorFileToQGIS, addRasterFileToQGIS
from util.settings import read_setting, write_setting

from pyprecag import config, crs
from pyprecag.processing import resample_bands_to_block

from qgis.PyQt import QtGui, uic, QtCore, QtWidgets
from qgis.PyQt.QtWidgets import QPushButton, QApplication, QDialog, QFileDialog

from qgis.core import (QgsMapLayer, QgsMessageLog, QgsVectorFileWriter, QgsCoordinateReferenceSystem, QgsApplication,
                       Qgis, QgsMapLayerProxyModel)
from qgis.gui import QgsMessageBar

from util.qgis_common import get_UTM_Coordinate_System, get_layer_source

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'resampleImageToBlock_dialog_base.ui'))

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()  # Handle logging, no logging has been configured


class ResampleImageToBlockDialog(QDialog, FORM_CLASS):
    """Extract statistics from a list of rasters at set locations."""
    toolKey = 'ResampleImageBandDialog'

    def __init__(self, iface, parent=None):

        super(ResampleImageToBlockDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.iface = iface
        self.DISP_TEMP_LAYERS = read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool)
        self.DEBUG = config.get_debug_mode()

        # Catch and redirect python errors directed at the log messages python error tab.
        QgsApplication.messageLog().messageReceived.connect(errorCatcher)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

        # Setup for validation messagebar on gui-----------------------------
        self.messageBar = QgsMessageBar(self)  # leave this message bar for bailouts
        self.validationLayout = QtWidgets.QFormLayout(self)  # new layout to gui

        if isinstance(self.layout(), (QtWidgets.QFormLayout, QtWidgets.QGridLayout)):
            # create a validation layout so multiple messages can be added and cleaned up.
            self.layout().insertRow(0, self.validationLayout)
            self.layout().insertRow(0, self.messageBar)
        else:
            self.layout().insertWidget(0, self.messageBar)  # for use with Vertical/horizontal layout box

        # GUI Runtime Customisation -----------------------------------------------
        self.mcboPolygonLayer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.mcboPolygonLayer.setExcludedProviders(['wms'])
        self.mcboPolygonLayer.setLayer(None)
        
        self.mcboRasterLayer.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.mcboRasterLayer.setExcludedProviders(['wms'])
        
        self.updateRaster()
        
        #https://stackoverflow.com/questions/13422995/set-qlineedit-to-accept-only-numbers
        #https://stackoverflow.com/questions/12643009/regular-expression-for-floating-point-numbers
        regex_validator  = QtGui.QRegExpValidator(QtCore.QRegExp("[-+]?([0-9]*[.])?[0-9]+([eE][-+]?\d+)?"))
        self.lneNoDataVal.setValidator(regex_validator)
        
        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_resampleToBlock.svg'))
        # self.chkAddToDisplay.setChecked(False)
        # self.chkAddToDisplay.hide()

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

    def updateRaster(self):
        if self.mcboRasterLayer.currentLayer() is None: return

        layer = self.mcboRasterLayer.currentLayer()
        provider = layer.dataProvider()
        
        if provider.sourceHasNoDataValue(1):
            self.lneNoDataVal.setText(str(provider.sourceNoDataValue(1)))
        elif len(provider.userNoDataValues(1)) > 0:
            self.lneNoDataVal.setText(str(provider.userNoDataValues(1)[0].min()))
        else:
            self.lneNoDataVal.clear()

        # add a band list to the drop down box
        bandCount = self.mcboRasterLayer.currentLayer().bandCount()
        band_list = ['Band {: >2}'.format(i) for i in range(1, bandCount + 1)]
        self.cboBand.setMaxCount(bandCount + 1)
        self.cboBand.clear()
        self.cboBand.addItems(sorted(band_list))
        
        #set default coordinate system
        rast_crs = layer.crs()
        if rast_crs.authid()== '':
            # Convert from the older style strings
            rast_crs = QgsCoordinateReferenceSystem()
            if not rast_crs.createFromProj(layer.crs().toWkt()):
                rast_crs = layer.crs()
        
        
        rast_crs = get_UTM_Coordinate_System(layer.extent().xMinimum(),
                                                   layer.extent().yMinimum(),
                                                   rast_crs.authid())

        self.mCRSoutput.setCrs(rast_crs)
        

    def on_mcboRasterLayer_layerChanged(self):
        self.updateRaster()

    
    def on_mcboPolygonLayer_layerChanged(self):
        self.chkUseSelected.setChecked(False)

        if self.mcboPolygonLayer.count() == 0:
            return

        self.mFieldComboBox.setLayer(None)

        if self.mcboPolygonLayer.currentLayer() is  None:
            return

        polygon_lyr = self.mcboPolygonLayer.currentLayer()
        self.mFieldComboBox.setLayer(polygon_lyr)

        if len(polygon_lyr.selectedFeatures()) > 0:
            self.chkUseSelected.setText('Use the {} selected feature(s) ?'.format(len(polygon_lyr.selectedFeatures())))
            self.chkUseSelected.setEnabled(True)
        else:
            self.chkUseSelected.setText('No features selected')
            self.chkUseSelected.setEnabled(False)

        # ToDo: QGIS 3 implement QgsMapLayerComboBox.allowEmptyLayer() instead of chkUsePoly checkbox
        # self.chkUsePoly.setChecked(True)


    # @QtCore.pyqtSlot(int)
    # def on_chkUsePoly_stateChanged(self, state):
    #     self.mFieldComboBox.setEnabled(state)
    #     self.lblGroupByField.setEnabled(state)

#     def on_mFieldComboBox_fieldChanged(self, field):
#         # Problem : after selecting a field, the blank is removed from the pick list.
#         # Solution: Add it again.... but this doesn't work.
#         if self.mFieldComboBox.findText('', QtCore.Qt.MatchFixedString) == -1:
#             # work around for not having a physical blank in the list. Fixed in qgis 3
#             self.mFieldComboBox.addItem(u'')

    # def on_chkUseSelected_stateChanged(self, state):
    #     if self.chkUseSelected.isChecked():
    #         self.chkUsePoly.setChecked(True)

    def on_mCRSoutput_crsChanged(self):
        #self.outQgsCRS = self.mCRSoutput.crs()
        pass


    @QtCore.pyqtSlot(name='on_cmdOutputFolder_clicked')
    def on_cmdOutputFolder_clicked(self):
        self.messageBar.clearWidgets()
        if self.lneOutputFolder.text() is None:
            outFolder = ''
        else:
            outFolder = self.lneOutputFolder.text()

        if outFolder == '':
            outFolder = read_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder")
            if outFolder is None or not os.path.exists(outFolder):
                outFolder = read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER')

        s = QFileDialog.getExistingDirectory(self, self.tr(
            "Save output files to a folder. A sub-folder will be created from the image name"),
                                                   outFolder, QFileDialog.ShowDirsOnly)

        self.cleanMessageBars(self)
        if s == '' or s is None:
            return

        s = os.path.normpath(s)

        self.lblOutputFolder.setStyleSheet('color:black')
        self.lneOutputFolder.setStyleSheet('color:black')
        self.lneOutputFolder.setText(s)
        write_setting(PLUGIN_NAME + "/" + self.toolKey + "/LastOutFolder", s)

    def validate(self):
        """Check to see that all required gui elements have been entered and are valid."""
        self.messageBar.clearWidgets()
        self.cleanMessageBars(AllBars=True)
        try:
            errorList = []

            if self.mcboRasterLayer.currentLayer() is None:
                self.lblRasterLayer.setStyleSheet('color:red')
                errorList.append(self.tr("Input image layer required."))
            else:
                self.lblRasterLayer.setStyleSheet('color:black')

            if self.cboBand.currentText() == '':
                self.lblBand.setStyleSheet('color:red')
                errorList.append(self.tr("Input band selection required."))
            else:
                self.lblBand.setStyleSheet('color:black')

            if self.dsbPixelSize.value() <= 0:
                self.lblPixelSize.setStyleSheet('color:red')
                errorList.append(self.tr("Pixel size must be greater than 0."))
            else:
                self.lblPixelSize.setStyleSheet('color:black')

            try:
                _ = float(self.lneNoDataVal.text())
                self.lblNoDataVal.setStyleSheet("color:black")
            except:
                self.lblNoDataVal.setStyleSheet("color:red")
                errorList.append(self.tr('The raster nodata value must be numeric'))

            if self.mCRSoutput.crs().authid() == '':
                self.lblOutCRSTitle.setStyleSheet('color:red')
                errorList.append(self.tr("Select output projected coordinate system"))
            else:
                if self.mCRSoutput.crs().isGeographic():
                    self.lblOutCRSTitle.setStyleSheet('color:red')
                    errorList.append(self.tr("Output projected coordinate system (not geographic) required"))
                else:
                    self.lblOutCRSTitle.setStyleSheet('color:black')

            if self.lneOutputFolder.text() == '':
                self.lblOutputFolder.setStyleSheet('color:red')
                errorList.append(self.tr("Select output data folder"))
            elif not os.path.exists(self.lneOutputFolder.text()):
                self.lneOutputFolder.setStyleSheet('color:red')
                self.lblOutputFolder.setStyleSheet('color:red')
                errorList.append(self.tr("Output data folder does not exist"))
            else:
                self.lblOutputFolder.setStyleSheet('color:black')
                self.lneOutputFolder.setStyleSheet('color:black')

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
        try:

            if not self.validate():
                return False

            # disable form via a frame, this will still allow interaction with the message bar
            self.fraMain.setDisabled(True)

            # clean gui and Qgis messagebars
            self.cleanMessageBars(True)

            # Change cursor to Wait cursor
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            self.iface.mainWindow().statusBar().showMessage('Processing {}'.format(self.windowTitle()))
            LOGGER.info('{st}\nProcessing {}'.format(self.windowTitle(), st='*' * 50))

            self.send_to_messagebar("Please wait.. QGIS will be locked... See log panel for progress.",
                                    level=Qgis.Warning,
                                    duration=0, addToLog=False, core_QGIS=False, showLogPanel=True)

            # Add settings to log
            settingsStr = 'Parameters:---------------------------------------'
            settingsStr += '\n    {:20}\t{}'.format('Image layer:', self.mcboRasterLayer.currentLayer().name())
            settingsStr += '\n    {:20}\t{}'.format('Image Band:', self.cboBand.currentText())
            settingsStr += '\n    {:20}\t{}'.format('Image nodata value:', self.lneNoDataVal.text())

            if self.mcboPolygonLayer.currentLayer() is not None:
                if self.chkUseSelected.isChecked():
                    settingsStr += '\n    {:20}\t{} with {} selected features'.format(
                                        'Layer:', self.mcboPolygonLayer.currentLayer().name(),
                                                  self.mcboPolygonLayer.currentLayer().selectedFeatureCount())
                else:
                    settingsStr += '\n    {:20}\t{}'.format('Boundary layer:',
                                                            self.mcboPolygonLayer.currentLayer().name())

                if self.mFieldComboBox.currentField():
                    settingsStr += '\n    {:20}\t{}'.format('Block ID field:', self.mFieldComboBox.currentField())
            else:
                settingsStr += '\n    {:20}\t{}'.format('Boundary layer:','')
                settingsStr += '\n    {:20}\t{}'.format('Block ID field:','')

            settingsStr += '\n    {:20}\t{}'.format('Resample pixel size: ', self.dsbPixelSize.value())

            settingsStr += '\n    {:30}\t{} - {}'.format('Output Coordinate System:',
                                                         self.mCRSoutput.crs().authid(),self.mCRSoutput.crs().description())

            settingsStr += '\n    {:30}\t{}\n'.format('Output Folder:', self.lneOutputFolder.text())

            LOGGER.info(settingsStr)

            lyrRaster = self.mcboRasterLayer.currentLayer()

            filePoly = None

            if self.mcboPolygonLayer.currentLayer() is not None:
                lyrBoundary = self.mcboPolygonLayer.currentLayer()

                if self.chkUseSelected.isChecked():
                    savePlyName = lyrBoundary.name() + '_poly.shp'
                    filePoly = os.path.join(TEMPDIR, savePlyName)
                    if os.path.exists(filePoly):  removeFileFromQGIS(filePoly)

                    QgsVectorFileWriter.writeAsVectorFormat(lyrBoundary, filePoly, "utf-8", lyrBoundary.crs(),
                                                            driverName="ESRI Shapefile", onlySelected=True)

                    if self.DISP_TEMP_LAYERS:
                        addVectorFileToQGIS(filePoly, layer_name=os.path.splitext(os.path.basename(filePoly))[0]
                                            , group_layer_name='DEBUG', atTop=True)
                else:
                    filePoly = get_layer_source(lyrBoundary)
            
            # convert string to float or int without knowing which
            x = self.lneNoDataVal.text()
            nodata_val = int(float(x)) if int(float(x)) == float(x) else float(x)
            
            band_num = [int(self.cboBand.currentText().replace('Band ', ''))]
            files = resample_bands_to_block(get_layer_source(lyrRaster),
                                            self.dsbPixelSize.value(),
                                            self.lneOutputFolder.text(),
                                            band_nums=band_num,
                                            image_epsg=int(lyrRaster.crs().authid().replace('EPSG:', '')),
                                            image_nodata=nodata_val,
                                            polygon_shapefile=filePoly,
                                            groupby=self.mFieldComboBox.currentField() if self.mFieldComboBox.currentField() else None,
                                            out_epsg=int(self.mCRSoutput.crs().authid().replace('EPSG:', '')))

            if self.chkAddToDisplay.isChecked():
                for ea_file in files:
                    removeFileFromQGIS(ea_file)
                    group_name =  os.path.basename(os.path.dirname(ea_file))
                    if self.mFieldComboBox.currentField():
                        group_name = os.path.basename(ea_file).split('_')[0] + ' - ' + os.path.basename(os.path.dirname(ea_file))
                    
                    addRasterFileToQGIS(ea_file, group_layer_name=group_name,atTop=False)

            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.iface.mainWindow().statusBar().clearMessage()
            self.iface.messageBar().popWidget()
            QApplication.restoreOverrideCursor()
            return super(ResampleImageToBlockDialog, self).accept(*args, **kwargs)

        except Exception as err:

            QApplication.restoreOverrideCursor()
            self.iface.mainWindow().statusBar().clearMessage()
            self.cleanMessageBars(True)
            self.fraMain.setDisabled(False)

            self.send_to_messagebar(str(err), level=Qgis.Critical,
                                    duration=0, addToLog=True, core_QGIS=False, showLogPanel=True,
                                    exc_info=sys.exc_info())

            return False  # leave dialog open
