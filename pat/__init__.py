# -*- coding: utf-8 -*-
"""
/***************************************************************************
  CSIRO Precision Agriculture Tools (PAT) Plugin
  pat - This script initializes the plugin, making it known to QGIS.
           -------------------
        begin      : 2017-05-25
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

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

import os
import sys
import site
import platform
import tempfile
import osgeo.gdal
import logging
import resources  # import resources like icons for the plugin
import qgis.utils
from qgis.gui import QgsMessageBar
from PyQt4.QtGui import QMessageBox

PLUGIN_DIR = os.path.abspath( os.path.dirname(__file__))
PLUGIN_NAME = "PAT"
PLUGIN_SHORT= "PAT"
LOGGER_NAME = 'pyprecag'

# This matches the folder pyprecag uses.
TEMPDIR = os.path.join(tempfile.gettempdir(), 'PrecisionAg')

''' Adds the path to the external libraries to the sys.path if not already added'''
if PLUGIN_DIR not in sys.path:
    sys.path.append(PLUGIN_DIR)

# if os.path.join(PLUGIN_DIR, 'ext-libs') not in sys.path:
#     site.addsitedir(os.path.join(PLUGIN_DIR, 'ext-libs'))


def classFactory(iface):
    """Load pat_toolbar class from file pat_toolbar.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    if platform.system() != 'Windows':
        message = 'PAT is only available for Windows'

        iface.messageBar().pushMessage("ERROR", message,
                                       level=QgsMessageBar.CRITICAL,
                                       duration=0)

        QMessageBox.critical(None, 'Error', message)
        sys.exit(message)

    if not os.path.exists(TEMPDIR):
        os.mkdir(TEMPDIR)

    from util.settings import read_setting, write_setting
    if read_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS") is None:
        write_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", False)

    if read_setting(PLUGIN_NAME + "/DEBUG") is None:
        write_setting(PLUGIN_NAME + "/DEBUG", False)

    try:
        from pyprecag import config
        config.set_debug_mode(read_setting(PLUGIN_NAME + "/DEBUG",bool))
    except ImportError:
        # pyprecag is not yet installed
        pass

    # the custom logging import requires qgis_config so leave it here
    from util.custom_logging import setup_logger

    # Call the logger pyprecag so it picks up the module debugging as well.
    setup_logger(LOGGER_NAME)
    LOGGER = logging.getLogger(LOGGER_NAME)
    LOGGER.addHandler( logging.NullHandler())   # logging.StreamHandler()

    #from util.check_dependencies import check_gdal_dependency

    #if 'util.check_dependencies' not in sys.modules:

    import util.check_dependencies
    import imp
    try:
        #Qgis doesn't alway unload imported modules before uninstalling, upgrading or reinstalling
        #causing errors to occur if check_dependencies has change. The workaround is to reload
        #it prior to running any of its functions.
        imp.reload(util.check_dependencies)
    except:
        pass

    util.check_dependencies.check_R_dependency()

    gdal_ver, check_gdal = util.check_dependencies.check_gdal_dependency()

    if not check_gdal:
        LOGGER.critical('QGIS Version {} and GDAL {} is are not currently supported.'.format(qgis.utils.QGis.QGIS_VERSION, gdal_ver))

        message = 'QGIS Version {} and GDAL {}  are not currently supported. Downgrade QGIS to an earlier version. If required email PAT@csiro.au for assistance.'.format(qgis.utils.QGis.QGIS_VERSION, gdal_ver)

        iface.messageBar().pushMessage("ERROR Failed Dependency Check", message, level=QgsMessageBar.CRITICAL,
                                       duration=0)
        QMessageBox.critical(None, 'Failed Dependency Check', message)
        sys.exit(message)

    #from util.check_dependencies import check_python_dependencies, check_vesper_dependency

    util.check_dependencies.check_python_dependencies(PLUGIN_DIR, iface)

    vesper_exe = util.check_dependencies.check_vesper_dependency()
    util.check_dependencies.check_pat_symbols()

    # Retrieve values from the plugin metadata file
    cfg = configparser.SafeConfigParser()
    cfg.read(os.path.join(PLUGIN_DIR, 'metadata.txt'))
    version = cfg.get('general', 'version')

    plugin_state = 'PAT Plugin State:\n'
    plugin_state += '    {:20}\t{}\n'.format('QGIS Version:', qgis.utils.QGis.QGIS_VERSION)
    plugin_state += '    {:20}\t{}\n'.format('Python Version:',  sys.version)
    plugin_state += '    {:20}\t{}\n'.format('PAT Version:', version)

    LOGGER.info(plugin_state)
    from pat_toolbar import pat_toolbar

    return pat_toolbar(iface)
