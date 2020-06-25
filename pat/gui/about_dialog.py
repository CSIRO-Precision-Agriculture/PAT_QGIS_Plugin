# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 AboutDialog - GUI displaying PAT version and licensing conditions.
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


from future import standard_library
standard_library.install_aliases()
try:
    import configparser as configparser
except ImportError:
    import configparser

import logging
import os

from qgis.PyQt import QtGui
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QPixmap

pluginPath = os.path.split(os.path.dirname(__file__))[0]
WIDGET, BASE = uic.loadUiType(os.path.join(pluginPath, 'gui', 'about_dialog_base.ui'))

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


class AboutDialog(BASE, WIDGET):
    """Dialog for managing PAT plugin settings. """

    def __init__(self, parent=None):
        super(AboutDialog, self).__init__(parent)

        # Set up the user interface from Designer.
        self.setupUi(self)

        # Retrieve values from the plugin metadata file
        cfg = configparser.ConfigParser()
        cfg.read(os.path.join(pluginPath, 'metadata.txt'))
        version = cfg.get('general', 'version')

        self.lblPATLogo.setPixmap(QPixmap(':/plugins/pat/icons/icon.png'))
        self.lblLogo1.setPixmap(QPixmap(':/plugins/pat/icons/CSIRO_Grad_RGB.png'))
        self.lblLogo2.setPixmap(QPixmap(':/plugins/pat/icons/WineAustralia_Logo.png'))
        self.lblVersion.setText(self.tr('PAT Version: {}'.format(version)))
        self.lblAbout.setText(self.getAboutText())

        licence = os.path.join(pluginPath, 'LICENSE')
        with open(licence, 'r') as oFile:
            self.pteLicence.setPlainText(oFile.read())

        self.setWindowIcon(QtGui.QIcon(':/plugins/pat/icons/icon_about.svg'))

    def getAboutText(self):
        return self.tr(
            '<p>Developed by the CSIRO Precision Agriculture team.'
            '<p>This project was initiated by CSIRO with support from Wine Australia and the Australia Federal Government’s Department of Agriculture as part of its Rural R&D for Profit program. Development of this QGIS 3 compatible version was supported by CSIRO.'
            '</p>')

    def accept(self, *args, **kwargs):
        return super(AboutDialog, self).accept(*args, **kwargs)
