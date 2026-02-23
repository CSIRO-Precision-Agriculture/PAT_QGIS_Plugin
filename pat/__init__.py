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
import traceback
import os
import sys
import platform
import tempfile
from pathlib import Path
import logging
from packaging.version import parse as parse_version
from datetime import datetime

from . import resources  # import resources like icons for the plugin

import qgis
from qgis.core import Qgis,QgsApplication, QgsRuntimeProfiler, QgsSettings
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtCore import QDateTime, QSettings

from pat.util.settings import read_setting, write_setting
from pat.util.check_dependencies import is_folder_writable, post_install_check
from pat.util.constants import PLUGIN_NAME, PLUGIN_SHORT, LOGGER_NAME, QGIS_VERSION, TEMPDIR, PLUGIN_DIR

''' Adds the path to the external libraries to the sys.path if not already added'''
if PLUGIN_DIR not in sys.path:
    sys.path.append(PLUGIN_DIR)

# extra_path = Path(PLUGIN_DIR).joinpath('ext-libs','pyprecag-fork')
# if extra_path.exists() and str(extra_path) not in sys.path:
#     sys.path.append(str(extra_path))

def classFactory(iface):
    """Load pat_toolbar class from file pat_toolbar.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    start_time = datetime.now()
    
    if platform.system() != 'Windows':
        message = 'PAT is only available for Windows'

        QMessageBox.critical(None, 'Error', message)
        sys.exit(message)

    if not Path(TEMPDIR).exists():
        Path(TEMPDIR).mkdir(parents=True, exist_ok=True)

    from .util.settings import read_setting, write_setting, remove_setting
    
    # if read_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", bool) is None:
    #     write_setting(PLUGIN_NAME + "/DISP_TEMP_LAYERS", False)

    # if read_setting(PLUGIN_NAME + "/DEBUG", bool) is None:
    #     write_setting(PLUGIN_NAME + "/DEBUG", False)

    # if read_setting(PLUGIN_NAME + '/USE_PROJECT_NAME', bool) is None:
    #     write_setting(PLUGIN_NAME + '/USE_PROJECT_NAME', False)

    # if read_setting(PLUGIN_NAME + '/PROJECT_LOG', bool) is None:
    #     write_setting(PLUGIN_NAME + '/PROJECT_LOG', False)
    #     write_setting(PLUGIN_NAME + '/LOG_FILE', os.path.normpath(os.path.join(TEMPDIR, 'PAT.log')))

    # the custom logging import requires qgis_config so leave it here
    from .util.custom_logging import set_log_file, setup_logger

    # Call the logger pyprecag so it picks up the module debugging as well.
    log_file = set_log_file()
    
    # make sure the logger file is actually set 
    setup_logger(LOGGER_NAME, log_file)

    LOGGER = logging.getLogger(LOGGER_NAME)
    LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()
    
    
    plugin = None
    
    pending = read_setting(PLUGIN_NAME + '/SETUP/INSTALL_PENDING', object_type=str,default='')
            
    finish_file = Path(PLUGIN_DIR).joinpath('install_files', 'pat-install.finished')

    if pending.endswith('lnk') and Path(finish_file).exists() and QGIS_VERSION in pending:
        Path(pending).unlink(missing_ok=True)
        #finish_file.unlink(missing_ok=True)
        # reset to finished so we know the first part is done.
        write_setting(f'{PLUGIN_NAME}/SETUP/INSTALL_PENDING', 'finished')
        pending = 'finished'
    
    
    from pat.util.check_dependencies import plugin_status
    i_attempt = 0
    while True and i_attempt < 3:
        i_attempt += 1
        print(f'Attempt {i_attempt} for {QGIS_VERSION} - {datetime.now()}')
        print("\n".join([f"{k} = {QgsSettings().value(k)}" for k in sorted(QgsSettings().allKeys()) if k.startswith(f'{PLUGIN_NAME}/SETUP')]))    
    
        try:
            with QgsRuntimeProfiler.profile("Import plugin"): 
                from .pat_toolbar import pat_toolbar
            plugin = pat_toolbar(iface)
            # Remove the choice as its loaded successfully.
            QgsSettings().remove(f'{PLUGIN_NAME}/SETUP/INSTALL_CHOICE')
            QgsSettings().remove(f'{PLUGIN_NAME}/SETUP/INSTALL_PENDING')
            break

        except ModuleNotFoundError  as err:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            mess = str(traceback.format_exc())
            
            # Should be not installed
            print(f'ModuleNotFoundError - {err.name} {err}')
            
            if str(err).startswith('No module named'):
                inst_df = plugin_status(level='basic', check_for_updates=False)
                break
            else:
                print (mess)
                break

        except ImportError  as err:
            if 'DLL load failed' in str(err) and 'rasterio' in err.path and not pending.endswith('lnk') is not None:
                post_check_pack = post_install_check('rasterio')
                if post_check_pack:
                    _=plugin_status(level='basic', extra_packages=post_check_pack)
            else:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                mess = str(traceback.format_exc())
                print(mess)
                break

        except Exception as error:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            mess = str(traceback.format_exc())
            print(mess)

            break

    if plugin is  None:
        plugin = DummyPlugin(iface)
            
    return plugin

class DummyPlugin:
    """Dummy plugin class that does nothing when dependencies aren't met"""
    def __init__(self, iface):
        self.iface = iface

    def initGui(self):
        pass
    
    def unload(self):
        pass

    def _load(self) -> None:
        """Load the plugin resources and initialize components."""
        pass