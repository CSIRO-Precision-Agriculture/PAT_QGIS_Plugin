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

from datetime import datetime
from . import resources  # import resources like icons for the plugin

import qgis
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
    start_time = datetime.now()
    
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

    if read_setting(PLUGIN_NAME + "/DEBUG", bool):
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                           'Logger Setup ',
                                           start_time.strftime("%H:%M:%S.%f"),
                                           datetime.now().strftime("%H:%M:%S.%f"),
                                           dur=datetime.now() - start_time))
    
    step_time = datetime.now() 
    # try:
    #     from .pat_toolbar import pat_toolbar
    #
    #     import rasterio
    #     import geopandas
    #     from pyprecag import crs
    #
    #     from pyprecag import config
    #     config.set_debug_mode(read_setting(PLUGIN_NAME + "/DEBUG", bool))
    #     dep_met = True
    # except ImportError:
    #     # this will catch any import issues within the plugin or within pyprecag and force an update if available.
    #     dep_met = False
    # if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
    #     LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
    #                                     'Import Test',
    #                                     step_time.strftime("%H:%M:%S.%f"),
    #                                        datetime.now().strftime("%H:%M:%S.%f"),
    #                                        dur=datetime.now() - step_time))
    #
    # step_time = datetime.now()
    #write_setting(PLUGIN_NAME + '/STATUS/DEPENDENCIES_MET', dep_met)

    next_check = read_setting(PLUGIN_NAME + "/STATUS/NEXT_CHECK", object_type=QDateTime)
    
    if next_check.isNull():   
        check_online = True
    else:
        check_online = QDateTime.currentDateTime() > next_check
    
    if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                        'Prep',
                                        step_time.strftime("%H:%M:%S.%f"),
                                           datetime.now().strftime("%H:%M:%S.%f"),
                                           dur=datetime.now() - step_time))
        
    step_time = datetime.now()
    
    from .util.check_dependencies import plugin_status
    
    if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                        'import plugin_status',
                                        step_time.strftime("%H:%M:%S.%f"),
                                           datetime.now().strftime("%H:%M:%S.%f"),
                                           dur=datetime.now() - step_time))
        
    step_time = datetime.now()
    
    _ = plugin_status(level='basic', check_for_updates=check_online)
                   
    if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                        'Checking Dependencies',
                                        step_time.strftime("%H:%M:%S.%f"),
                                           datetime.now().strftime("%H:%M:%S.%f"),
                                           dur=datetime.now() - step_time))
    step_time = datetime.now()

    if  read_setting(PLUGIN_NAME + '/STATUS/INSTALL_PENDING', object_type=bool, default=False):
        #qgis.utils.unloadPlugin('pat')
               
        if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
                LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                        'PAT Pending Install',  
                                        start_time.strftime("%H:%M:%S.%f"),
                                        datetime.now().strftime("%H:%M:%S.%f"),
                                        dur=datetime.now() - start_time))
        
        sys.exit('Please install dependencies to use PAT')   
    else:
        # if we get here, then plugin should be imported and ready to go so set new check date.
        if QDateTime.currentDateTime() > read_setting(PLUGIN_NAME + "/STATUS/NEXT_CHECK", object_type=QDateTime):
            write_setting(PLUGIN_NAME + '/STATUS/NEXT_CHECK', QDateTime.currentDateTime().addDays(30))
        
        #qgis.utils.reloadPlugin('pat')
        step_time = datetime.now()
        from .pat_toolbar import pat_toolbar
        if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
            LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                    'ImportToolbar',  
                                    step_time.strftime("%H:%M:%S.%f"),
                                    datetime.now().strftime("%H:%M:%S.%f"),
                                    dur=datetime.now() - start_time))
            
            LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(
                                    'PAT Loaded successfully',  
                                    start_time.strftime("%H:%M:%S.%f"),
                                    datetime.now().strftime("%H:%M:%S.%f"),
                                    dur=datetime.now() - start_time))
        
        from .util.check_dependencies import check_pat_symbols
        check_pat_symbols()
                
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

