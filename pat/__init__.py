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

import os
import sys
import platform
import tempfile
from pathlib import Path
import logging
from . import resources  # import resources like icons for the plugin

from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import QDateTime

PLUGIN_DIR = os.path.abspath(os.path.dirname(__file__))
PLUGIN_NAME = "PAT"
PLUGIN_SHORT = "PAT"
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

    from .util.settings import read_setting, write_setting, remove_setting
            
    if read_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", bool) is None:
        write_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", False)

    if read_setting(PLUGIN_NAME + "/DEBUG", bool) is None:
        write_setting(PLUGIN_NAME + "/DEBUG", False)

    if read_setting(PLUGIN_NAME + '/USE_PROJECT_NAME', bool) is None:
        write_setting(PLUGIN_NAME + '/USE_PROJECT_NAME', False)

    if read_setting(PLUGIN_NAME + '/PROJECT_LOG', bool) is None:
        write_setting(PLUGIN_NAME + '/PROJECT_LOG', False)
        write_setting(PLUGIN_NAME + '/LOG_FILE', os.path.normpath(os.path.join(TEMPDIR, 'PAT.log')))
    
    # the custom logging import requires qgis_config so leave it here
    from .util.custom_logging import set_log_file, setup_logger

    # Call the logger pyprecag so it picks up the module debugging as well.
    log_file = set_log_file()
    
    # make sure the logger file is actually set 
    setup_logger(LOGGER_NAME, log_file)

    LOGGER = logging.getLogger(LOGGER_NAME)
    LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

    # pat-install.finished is created when running the install bat file externally to QGIS 
    # so if it exists it means install was attempted.
    done_file = Path(PLUGIN_DIR).joinpath('install_files', 'pat-install.finished')
    if done_file.exists(): 
        done_file.unlink()
        shortcutPath  = read_setting(PLUGIN_NAME + '/STATUS/INSTALL_PENDING', object_type=str,default='')
            
        if shortcutPath != '' and Path(shortcutPath).exists():
             Path(shortcutPath).unlink()
             
        remove_setting(PLUGIN_NAME + '/STATUS/INSTALL_PENDING')

    try:
        from .pat_toolbar import pat_toolbar

        import rasterio
        import geopandas
        from pyprecag import crs

        from pyprecag import config
        config.set_debug_mode(read_setting(PLUGIN_NAME + "/DEBUG", bool))
        dep_met = True
    except ImportError:
        # this will catch any import issues within the plugin or within pyprecag and force an update if available.
        dep_met = False

    write_setting(PLUGIN_NAME + '/STATUS/DEPENDENCIES_MET', dep_met)

    next_check = read_setting(PLUGIN_NAME + "/STATUS/NEXT_CHECK", object_type=QDateTime)
    
    if next_check.isNull() or not dep_met:   
        check_online = True
    else:
        check_online = QDateTime.currentDateTime() > next_check
        
    from .util.check_dependencies import plugin_status
    _ = plugin_status(level='basic', check_for_updates=check_online)
        
    if  read_setting(PLUGIN_NAME + '/STATUS/INSTALL_PENDING', object_type=bool, default=False) and not dep_met:
        sys.exit('Please install dependencies to use PAT')
    else:
        # if we get here, then plugin should be imported and ready to go so set new check date.
        if QDateTime.currentDateTime() > read_setting(PLUGIN_NAME + "/STATUS/NEXT_CHECK", object_type=QDateTime):
            write_setting(PLUGIN_NAME + '/STATUS/NEXT_CHECK', QDateTime.currentDateTime().addDays(30))
        
        from .pat_toolbar import pat_toolbar
        return pat_toolbar(iface)

    # except Exception as err:
    #     if iface.mainWindow():
    #         iface.mainWindow().statusBar().clearMessage()
    #
    #     message =f'Unable to load PAT due to \n {str(err)}'  
    #     iface.messageBar().pushMessage("ERROR", message,
    #                                level=Qgis.Critical,
    #                                duration=20)
    #
    #     #LOGGER.critical(message)
    #     _ =  plugin_status(level='basic', check_for_updates=True)
    #
    #     sys.exit(message)

