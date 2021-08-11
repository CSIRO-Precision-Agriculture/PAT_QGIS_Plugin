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
from __future__ import absolute_import

from future import standard_library
standard_library.install_aliases()

import configparser

import os
import sys
import site
import platform
import tempfile
import osgeo.gdal
import logging
from . import resources  # import resources like icons for the plugin

from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsMessageBar
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import pluginMetadata
 
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
                                       level=Qgis.Critical,
                                       duration=0)

        QMessageBox.critical(None, 'Error', message)
        sys.exit(message)

    if not os.path.exists(TEMPDIR):
        os.mkdir(TEMPDIR)

    from .util.settings import read_setting, write_setting
    if read_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS") is None:
        write_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", False)

    if read_setting(PLUGIN_NAME + "/DEBUG") is None:
        write_setting(PLUGIN_NAME + "/DEBUG", False)

    if read_setting(PLUGIN_NAME + '/PROJECT_LOG', bool) is None:
        write_setting(PLUGIN_NAME + '/PROJECT_LOG',False)
        write_setting(PLUGIN_NAME + '/LOG_FILE',os.path.normpath(os.path.join(TEMPDIR,'PAT.log')))

    try:
        from pyprecag import config
        config.set_debug_mode(read_setting(PLUGIN_NAME + "/DEBUG",bool))
    except ImportError:
        # pyprecag is not yet installed
        pass

    # the custom logging import requires qgis_config so leave it here
    from .util.custom_logging import set_log_file, setup_logger

    # Call the logger pyprecag so it picks up the module debugging as well.
    log_file = set_log_file()
    
    # make sure the logger file is actually set 
    setup_logger(LOGGER_NAME, log_file)

    LOGGER = logging.getLogger(LOGGER_NAME)
    LOGGER.addHandler(logging.NullHandler())   # logging.StreamHandler()

    from .util.check_dependencies import (check_pat_symbols, check_R_dependency, check_gdal_dependency,
                                          check_python_dependencies, get_plugin_state)

    meta_version = pluginMetadata('pat','version')
    plugin_state = get_plugin_state('basic')

    LOGGER.info(plugin_state)

    gdal_ver = check_gdal_dependency()
    
    check_py = check_python_dependencies(PLUGIN_DIR, iface)
    if len(check_py) > 0:
        sys.exit(check_py)
    
    check_pat_symbols()

    from .pat_toolbar import pat_toolbar
    return pat_toolbar(iface)
