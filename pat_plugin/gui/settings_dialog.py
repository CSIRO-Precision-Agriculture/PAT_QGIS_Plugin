# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 SettingsDialog - Dialog used for setting default paths for use with PAT.
        These will only get used on first run. Each separate tool will then
        store it's own sets of defaults.
           -------------------
        begin      : 2018-03-13
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

import configparser
import qgis

from pat_plugin import PLUGIN_NAME
from PyQt4 import uic
from PyQt4.QtGui import QMessageBox
from qgis.PyQt import QtCore, QtGui

from pyprecag import config

from pat_plugin import PLUGIN_NAME, TEMPDIR, PLUGIN_DIR
from pat_plugin.util.check_dependencies import check_vesper_dependency
from pat_plugin.util.custom_logging import stop_logging, setup_logger
from pat_plugin.util.settings import read_setting, write_setting

pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(
    os.path.join(pluginPath, 'gui', 'settings_dialog_base.ui'))

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


class SettingsDialog(BASE, WIDGET):
    """Dialog for managing plugin settings."""

    def __init__(self, parent=None):

        super(SettingsDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.lneInDataDirectory.setText(read_setting(PLUGIN_NAME + '/BASE_IN_FOLDER'))
        self.lneOutDataDirectory.setText(read_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER'))
        self.chkDisplayTempLayers.setChecked(read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool))
        
        self.chkDebug.setChecked(read_setting(PLUGIN_NAME + '/DEBUG', bool))
        
        self.vesper_exe = check_vesper_dependency()
        if not os.path.exists(self.vesper_exe):
            self.vesper_exe = read_setting(PLUGIN_NAME + '/VESPER_EXE')

        self.lneVesperExe.setText(self.vesper_exe)

        # Add text to plain text box ------------
        self.pteVersions.setOpenExternalLinks(True)
        self.get_plugin_state()
    
    @QtCore.pyqtSlot(int)
    def on_chkDisplayTempLayers_stateChanged(self, state):
        if read_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', bool) != self.chkDisplayTempLayers.isChecked():
            write_setting(PLUGIN_NAME + '/DISP_TEMP_LAYERS', self.chkDisplayTempLayers.isChecked())


    @QtCore.pyqtSlot(int)
    def on_chkDebug_stateChanged(self, state):
        if config.get_debug_mode() != self.chkDebug.isChecked():
            write_setting(PLUGIN_NAME + '/DEBUG',  self.chkDebug.isChecked())
            config.set_debug_mode( self.chkDebug.isChecked())
            

    @QtCore.pyqtSlot(name='on_cmdInBrowse_clicked')
    def on_cmdInBrowse_clicked(self):
        s = QtGui.QFileDialog.getExistingDirectory(self, self.tr("Open Source Data From"),
                                                   self.lneInDataDirectory.text(),
                                                   QtGui.QFileDialog.ShowDirsOnly)

        if s == '':
            return

        s = os.path.normpath(s)

        self.lneInDataDirectory.setText(s)
        write_setting(PLUGIN_NAME + '/BASE_IN_FOLDER', s)

    @QtCore.pyqtSlot(name='on_cmdOutBrowse_clicked')
    def on_cmdOutBrowse_clicked(self):
        s = QtGui.QFileDialog.getExistingDirectory(self, self.tr("Save Output Data To"),
                                                   self.lneOutDataDirectory.text(),
                                                   QtGui.QFileDialog.ShowDirsOnly)

        if s == '':
            return

        s = os.path.normpath(s)

        self.lneOutDataDirectory.setText(s)
        write_setting(PLUGIN_NAME + '/BASE_OUT_FOLDER', s)

    @QtCore.pyqtSlot(name='on_cmdVesperExe_clicked')
    def on_cmdVesperExe_clicked(self):
        default_dir = os.path.dirname(self.lneVesperExe.text())
        if default_dir == '' or default_dir is None:
            default_dir = r'C:\Program Files (x86)'
        s = QtGui.QFileDialog.getOpenFileName(self, self.tr("Select Vesper Executable"),
                                              directory=default_dir,
                                              filter=self.tr("Vesper Executable") + " (Vesper*.exe);;"
                                                     + self.tr("All Exe Files") + " (*.exe);;")

        if s == '':  # ie nothing entered
            return
        s = os.path.normpath(s)
        self.lneVesperExe.setText(s)
        try:
            config.set_config_key('vesperEXE', s)
        except:
            LOGGER.warning('Could not write to config.json')

        self.vesper_exe = s
        write_setting(PLUGIN_NAME + '/VESPER_EXE', s)

    def get_plugin_state(self):
        # Retrieve values from the plugin metadata file
        cfg = configparser.SafeConfigParser()
        cfg.read(os.path.join(pluginPath, 'metadata.txt'))
        version = cfg.get('general', 'version')

        from pat_plugin.util.check_dependencies import check_package
        packCheck = {}
        # Check for the listed modules.
        for argCheck in ['geopandas', 'fiona', 'rasterio', 'pyprecag']:
            packCheck[argCheck] = check_package(argCheck)
        
        """TODO: Make the paths clickable links to open folder
        def create_path_link(path):
            path = os.path.normpath(path)
            #"<a href={}>Open Project Folder</a>".format("`C:/Progra~1/needed"`)
            return '<a href= file:///"`{0}"`>{0}</a>'.format(path)
        """
        
        self.pteVersions.setText( 'QGIS Environment:')
        self.pteVersions.append('    {:20}\t{}'.format('QGIS :', qgis.utils.QGis.QGIS_VERSION))
        self.pteVersions.append('    {:20}\t{}'.format('Python :',  sys.version))
        self.pteVersions.append('    {:20}\t{}'.format('GDAL :', os.environ.get('GDAL_VERSION', None)))

        self.pteVersions.append('    {:20}\t{}'.format('User Path:', os.path.normpath(os.path.expanduser('~'))))
        self.pteVersions.append('    {:20}\t{}'.format('Plugin Dir:',  os.path.normpath(PLUGIN_DIR)))
        self.pteVersions.append('    {:20}\t{}'.format('Temp Folder:',  os.path.normpath(TEMPDIR)))
        
        self.pteVersions.append('\nPAT Version:')
        self.pteVersions.append('    {:20}\t{}'.format('PAT:', version))
        self.pteVersions.append('    {:20}\t{}'.format('pyPrecAg:', packCheck['pyprecag']['Version']))
        self.pteVersions.append('    {:20}\t{}'.format('GeoPandas:', packCheck['geopandas']['Version']))
        self.pteVersions.append('    {:20}\t{}'.format('RasterIO:', packCheck['rasterio']['Version']))
        self.pteVersions.append('    {:20}\t{}'.format('Fiona:', packCheck['fiona']['Version']))

        self.pteVersions.append('\nR Configuration')
        self.pteVersions.append('    {:20}\t{}'.format('R Active :', read_setting('Processing/Configuration/ACTIVATE_R')))
        self.pteVersions.append('    {:20}\t{}'.format('R Install Folder :', read_setting('Processing/Configuration/R_FOLDER')))
#                 
#         return plugin_state

    def accept(self, *args, **kwargs):
        # Stop and start logging to setup the new log level
        stop_logging('pyprecag')
        setup_logger('pyprecag')

        return super(SettingsDialog, self).accept(*args, **kwargs)
