# coding=utf-8
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 settings - functionality used for setting and retrieving Last Value settings for gui's.
 These values are saved in the registry     ie HKEY_CURRENT_USER\Software\QGIS\QGIS2\PrecisionAg

                    -------------------
        begin      : 2017-05-25
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

from pat_plugin import LOGGER_NAME
from PyQt4.QtCore import QSettings

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


def read_setting(key, object_type=str):
    """
    Loads the value from the QSettings specified by the key
    Args:
        key (str): Key from the QSettings maps
        object_type (object_type): Type to return (defaults to str)

    Returns: The value if present; else ""

    """
    setting = QSettings()
    if setting.contains(key):
        return setting.value(key, type=object_type)
    return


def write_setting(key, value):
    """
    Writes the key with the value specified to the QSettings map
    Args:
        key (str): The key in the map to write to
        value (str):  The value to write

    Returns: None

    """

    settings = QSettings()
    settings.setValue(key, value)
