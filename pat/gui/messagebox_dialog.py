# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 MessageBoxDialog - GUI displaying PAT version and licensing conditions.
           -------------------
        begin      : 2018-03-13
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

import logging
import os

from qgis.PyQt import QtGui, QtCore
from PyQt4 import uic

from pat import PLUGIN_NAME
from pat.util.settings import write_setting

pluginPath = os.path.split(os.path.dirname(__file__))[0]
FORM_CLASS, _ = uic.loadUiType(os.path.join(pluginPath, 'gui', 'messagebox_dialog_base.ui'))

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


class MessageBoxDialog(QtGui.QDialog, FORM_CLASS):
    """Dialog for managing PAT plugin settings. """

    def __init__(self, parent=None):
        super(MessageBoxDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint)

    def accept(self, *args, **kwargs):
        return super(MessageBoxDialog, self).accept(*args, **kwargs)
