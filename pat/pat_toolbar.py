# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 pat_toolbar - The PrecisionAg Toolbar and Menu setup & functionality
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


try:
    import ConfigParser as configparser
except ImportError:
    import configparser

import datetime
import logging
import os.path
import shutil
import sys
import time
import traceback
import webbrowser
from functools import partial
from pkg_resources import parse_version

from PyQt4.Qt import QLabel
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, QTimer, QProcess, Qt
from PyQt4.QtGui import QAction, QIcon, QMenu, QDockWidget, QToolButton, QMessageBox, QPushButton
from qgis.core import QgsMapLayerRegistry, QgsMessageLog
from qgis.gui import QgsMessageBar

from processing.core.Processing import Processing
from processing.tools import general
from processing.gui.CommanderWindow import CommanderWindow

from . import PLUGIN_DIR, PLUGIN_NAME, PLUGIN_SHORT, LOGGER_NAME, TEMPDIR
from gui.about_dialog import AboutDialog
from gui.settings_dialog import SettingsDialog
from gui.blockGrid_dialog import BlockGridDialog
from gui.cleanTrimPoints_dialog import CleanTrimPointsDialog
from gui.gridExtract_dialog import GridExtractDialog
from gui.pointTrailToPolygon_dialog import PointTrailToPolygonDialog
from gui.postVesper_dialog import PostVesperDialog
from gui.preVesper_dialog import PreVesperDialog
from gui.randomPixelSelection_dialog import RandomPixelSelectionDialog
from gui.rescaleNormalise_dialog import RescaleNormaliseDialog
from gui.calcImageIndices_dialog import CalculateImageIndicesDialog
from gui.resampleImageToBlock_dialog import ResampleImageToBlockDialog
from gui.kMeansCluster_dialog import KMeansClusterDialog
from gui.stripTrialPoints_dialog import StripTrialPointsDialog
from gui.tTestAnalysis_dialog import tTestAnalysisDialog
from gui.persistor_dialog import PersistorDialog
from util.check_dependencies import check_vesper_dependency, check_R_dependency
from util.custom_logging import stop_logging
from util.qgis_common import addRasterFileToQGIS, removeFileFromQGIS
from util.settings import read_setting, write_setting
from util.processing_alg_logging import ProcessingAlgMessages
from util.qgis_symbology import raster_apply_unique_value_renderer

import pyprecag
from pyprecag import config
from pyprecag.kriging_ops import vesper_text_to_raster

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


class pat_toolbar:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        Args:
            iface (QgsInterface): An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        """

        # Save reference to the QGIS interface
        self.iface = iface

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(self.plugin_dir, 'i18n', 'pat_plugin_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        self.actions = []

        # Look for the existing menu
        self.menuPrecAg = self.iface.mainWindow().findChild(QMenu, 'm{}Menu'.format(PLUGIN_SHORT))

        # If the menu does not exist, create it!
        if not self.menuPrecAg:
            self.menuPrecAg = QMenu('{}'.format(PLUGIN_SHORT), self.iface.mainWindow().menuBar())
            self.menuPrecAg.setObjectName('m{}Menu'.format(PLUGIN_SHORT))
            actions = self.iface.mainWindow().menuBar().actions()
            lastAction = actions[-1]
            self.iface.mainWindow().menuBar().insertMenu(lastAction, self.menuPrecAg)

        # create a toolbar
        self.toolbar = self.iface.addToolBar(u'{} Toolbar'.format(PLUGIN_SHORT))
        self.toolbar.setObjectName(u'm{}ToolBar'.format(PLUGIN_SHORT))

        # Load Defaults settings for First time...
        for eaKey in ['BASE_IN_FOLDER', 'BASE_OUT_FOLDER']:
            sFolder = read_setting(PLUGIN_NAME + '/' + eaKey)
            if sFolder is None or not os.path.exists(sFolder):
                sFolder = os.path.join(os.path.expanduser('~'), PLUGIN_NAME)

                if not os.path.exists(sFolder):
                    os.mkdir(sFolder)

                write_setting(PLUGIN_NAME + '/' + eaKey, os.path.join(os.path.expanduser('~'), PLUGIN_NAME))

        self.DEBUG = config.get_debug_mode()
        self.vesper_queue = []
        self.vesper_queue_showing = False
        self.processVesper = None
        self.vesper_exe = check_vesper_dependency(iface)

        if not os.path.exists(TEMPDIR):
            os.mkdir(TEMPDIR)

    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        Args:
            message (str, QString): String for translation.

        Returns:
            QString: Translated version of message.
        """

        return QCoreApplication.translate('pat', message)

    def add_action(self, icon_path, text, callback, enabled_flag=True, add_to_menu=True, add_to_toolbar=True,
                   tool_tip=None, status_tip=None, whats_this=None, parent=None):
        """Add a toolbar icon to the toolbar.

                Args:
                    icon_path (str): Path to the icon for this action. Can be a resource
                         path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
                    text (str): Text that should be shown in menu items for this action.
                    callback (function): Function to be called when the action is triggered.
                    enabled_flag (bool): A flag indicating if the action should be enabled
                             by default. Defaults to True.
                    add_to_menu (bool): Flag indicating whether the action should also
                            be added to the menu. Defaults to True.
                    add_to_toolbar (bool): Flag indicating whether the action should also
                            be added to the toolbar. Defaults to True.
                    tool_tip (str):  Optional text to show in a popup when mouse pointer
                            hovers over the action.
                    status_tip (str):  Optional text to show in the status bar when mouse pointer
                            hovers over the action.
                    whats_this (QWidget): Parent widget for the new action. Defaults None.
                    parent (): Optional text to show in the status bar when the
                            mouse pointer hovers over the action.
                Returns:
                    QAction: The action that was created. Note that the action is also
                            added to self.actions list.
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if tool_tip is not None:
            action.setToolTip(tool_tip)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.menuPrecAg.addAction(action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        '''Create new menu item
            source:https://gis.stackexchange.com/questions/169869/adding-multiple-plugins-to-custom-pluginMenu-in-qgis/169880#169880
                  https://gis.stackexchange.com/questions/127150/how-to-customize-the-qgis-gui-using-python '''

        # Finally, add your action to the menu and toolbar
        self.add_action(
            icon_path=':/plugins/pat/icons/icon_blockGrid.svg',
            text=self.tr(u'Create block grid'),
            tool_tip=self.tr(u'Create raster and VESPER grids for block polygons.'),
            status_tip=self.tr(u'Create raster and VESPER grids for block polygons.'),
            callback=self.run_blockGrid,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_cleanTrimPoints.svg',
            text=self.tr(u'Clean, trim and normalise data points'),
            tool_tip=self.tr(u'Clean, trim and normalise data points'),
            status_tip=self.tr(u'Clean, trim and normalise data points'),
            callback=self.run_cleanTrimPoints,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_vesperKriging.svg',
            text=self.tr(u'Run kriging using VESPER'),
            tool_tip=self.tr(u'Run kriging using VESPER'),
            status_tip=self.tr(u'Run kriging using VESPER'),
            callback=self.run_preVesper,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_importVesperKriging.svg',
            text=self.tr(u'Import VESPER results'),
            tool_tip=self.tr(u'Import VESPER results'),
            status_tip=self.tr(u'Import VESPER results'),
            add_to_toolbar=False,
            callback=self.run_postVesper,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_pointTrailToPolygon.svg',
            text=self.tr(u'Create polygons from on-the-go GPS point trail'),
            tool_tip=self.tr(u'Create polygons from on-the-go GPS point trail'),
            status_tip=self.tr(u'Create polygons from on-the-go GPS point trail'),
            add_to_toolbar=False,
            callback=self.run_pointTrailToPolygon,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_rescaleNormalise.svg',
            text=self.tr(u'Rescale or normalise raster'),
            tool_tip=self.tr(u'Rescale or normalise raster'),
            status_tip=self.tr(u'Rescale or normalise raster'),
            add_to_toolbar=False,
            callback=self.run_rescaleNormalise,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_randomPixel.svg',
            text=self.tr(u'Generate random pixel selection'),
            tool_tip=self.tr(u'Generate random pixel selection'),
            status_tip=self.tr(u'Generate random pixel selection'),
            add_to_toolbar=True,
            callback=self.run_generateRandomPixels,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_gridExtract.svg',
            text=self.tr(u'Extract raster pixel statistics for points'),
            tool_tip=self.tr(u'Extract raster pixel statistics for points'),
            status_tip=self.tr(u'Extract raster pixel statistics for points'),
            add_to_toolbar=True,
            callback=self.run_gridExtract,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_calcImgIndices.svg',
            text=self.tr(u'Calculate image indices for blocks'),
            tool_tip=self.tr(u'Calculate image indices for blocks'),
            status_tip=self.tr(u'Calculate image indices for blocks'),
            add_to_toolbar=True,
            callback=self.run_calculateImageIndices,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_resampleToBlock.svg',
            text=self.tr(u'Resample image band to blocks'),
            tool_tip=self.tr(u'Resample image band to blocks'),
            status_tip=self.tr(u'Resample image band to blocks'),
            add_to_toolbar=True,
            callback=self.run_resampleImage2Block,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_kMeansCluster.svg',
            text=self.tr(u'Create zones with k-means clustering'),
            tool_tip=self.tr(u'Create zones with k-means clustering'),
            status_tip=self.tr(u'Create zones with k-means clustering'),
            add_to_toolbar=True,
            callback=self.run_kMeansClustering,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_stripTrialPoints.svg',
            text=self.tr(u'Create strip trial points'),
            tool_tip=self.tr(u'Create strip trial points'),
            status_tip=self.tr(u'Create strip trial points'),
            add_to_toolbar=True,
            callback=self.run_stripTrialPoints,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_t-test.svg',
            text=self.tr(u'Run strip trial t-test analysis'),
            tool_tip=self.tr(u'Run strip trial t-test analysis'),
            status_tip=self.tr(u'Run strip trial t-test analysis'),
            add_to_toolbar=True,
            callback=self.run_tTestAnalysis,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_wholeOfBlockExp.svg',
            text=self.tr(u'Whole-of-block analysis'),
            tool_tip=self.tr(u'Whole-of-block analysis using co-kriging'),
            status_tip=self.tr(u'Whole-of-block analysis using co-kriging'),
            add_to_toolbar=True,
            callback=self.run_wholeOfBlockAnalysis,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_persistor.svg',
            text=self.tr(u'Persistor'),
            tool_tip=self.tr(u'Persistence over years'),
            status_tip=self.tr(u'Persistence over years'),
            add_to_toolbar=True,
            callback=self.run_persistor,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_help.svg',
            text=self.tr(u'Help'),
            tool_tip=self.tr(u'Help'),
            status_tip=self.tr(u'Help'),
            callback=self.run_help,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_settings.svg',
            text=self.tr(u'Settings'),
            tool_tip=self.tr(u'Settings'),
            add_to_toolbar=False,
            status_tip=self.tr(u'Settings'),
            callback=self.run_settings,
            parent=self.iface.mainWindow())

        self.add_action(
            icon_path=':/plugins/pat/icons/icon_about.svg',
            text=self.tr(u'About'),
            tool_tip=self.tr(u'About'),
            status_tip=self.tr(u'About'),
            add_to_toolbar=False,
            callback=self.run_about,
            parent=self.iface.mainWindow())

    @staticmethod
    def clear_modules():
        """Unload pyprecag functions and try to return QGIS.
        source: inasafe plugin
        """
        # next lets force remove any pyprecag related modules
        modules = []
        for module in sys.modules:
            if 'pyprecag' in module:
                LOGGER.debug('Removing: %s' % module)
                modules.append(module)

        for module in modules:
            del (sys.modules[module])

        # Lets also clean up all the path additions that were made
        package_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
        LOGGER.debug('Path to remove: %s' % package_path)
        # We use a list comprehension to ensure duplicate entries are removed
        LOGGER.debug(sys.path)
        sys.path = [y for y in sys.path if package_path not in y]
        LOGGER.debug(sys.path)

    def unload(self):
        """Removes the plugin menu/toolbar item and icon from QGIS GUI and clean up temp folder"""

        if len(self.vesper_queue) > 0:
            replyQuit = QMessageBox.information(self.iface.mainWindow(),
                                                "Quit QGIS", "Quitting QGIS with {} tasks in the "
                                                "VESPER queue.\n\t{}".format(len(self.vesper_queue),
                                                '\n\t'.join([ea['control_file'] for ea in self.vesper_queue])),
                                                QMessageBox.Ok)

        stop_logging('pyprecag')

        layermap = QgsMapLayerRegistry.instance().mapLayers()
        RemoveLayers = []
        for name, layer in layermap.iteritems():
            if TEMPDIR in layer.source():
                RemoveLayers.append(layer.id())

        if len(RemoveLayers) > 0:
            QgsMapLayerRegistry.instance().removeMapLayers(RemoveLayers)

        # remove the PrecisionAg Temp Folder.
        try:
            if not self.DEBUG and os.path.exists(TEMPDIR):
                shutil.rmtree(TEMPDIR)

        except Exception as err:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            mess = str(traceback.format_exc())
            print(mess)

        self.menuPrecAg.clear()
        for action in self.actions:
            self.iface.removePluginMenu(u'{}Menu'.format(PLUGIN_SHORT), action)
            self.iface.removeToolBarIcon(action)

        # remove the toolbar
        del self.toolbar
        del self.menuPrecAg
        self.clear_modules()

    def queueAddTo(self, vesp_dict):
        """ Add a control file to the VESPER queue"""

        if next((x for x in self.vesper_queue if x['control_file'] == vesp_dict["control_file"])
                , None) is not None:

            self.iface.messageBar().pushMessage('Control file is already in the VESPER queue. {}'.format(
                vesp_dict['control_file']),level=QgsMessageBar.WARNING, duration=15)

            self.queueDisplay()

        else:
            self.vesper_queue.append(vesp_dict)
            message = 'Added control file to VESPER queue. The queue now contains {} tasks'.format(
                len(self.vesper_queue))
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.INFO, duration=15)

    def queueDisplay(self):
        """display the VESPER queue in the python console"""

        # open the python console
        try:
            pythonConsolePanel = self.iface.mainWindow().findChild(QDockWidget, 'PythonConsole')
            if not pythonConsolePanel.isVisible():
                self.iface.actionShowPythonDialog().trigger()
        except:
            # the above will bail if sitting on RecentProjects empty view.
            self.iface.actionShowPythonDialog().trigger()
            pythonConsolePanel = self.iface.mainWindow().findChild(QDockWidget, 'PythonConsole')

        ctrl_width = len(max([os.path.basename(ea['control_file']) for ea in self.vesper_queue], key=len))
        epsg_width = len(max([str(ea['epsg']) for ea in self.vesper_queue], key=len))

        header = '{:3}\t{:<{cw}}\t{:5}\t{:>{ew}} {}'.format(
            '#', 'Control File', 'Import', 'EPSG', 'Folder', cw=ctrl_width + 10, ew=epsg_width + 10)

        print('\n' + '-' * len(header))
        print(header)
        print('-' * len(header))
        for i, ea in enumerate(self.vesper_queue):
            print('{:3}\t{:<{cw}}\t{:5}\t{:>{ew}}\t{}'.format(
                i + 1, os.path.basename(ea['control_file']), str(bool(ea['epsg'] > 0)), ea['epsg'],
                os.path.dirname(ea['control_file']), cw=ctrl_width + 10, ew=epsg_width + 10))

        print('\n')

    def queueClear(self):
        """Clear the VESPER queue of all pending jobs"""
        # clear all but the one running.
        if self.processVesper is None:
            self.vesper_queue = []
            self.queueStatusBarHide()
        else:
            self.vesper_queue = self.vesper_queue[:1]
            self.lblVesperQueue.setText('{} tasks in VESPER queue'.format(len(self.vesper_queue)))

        self.queueDisplay()

    def queueStatusBarShow(self):
        """Add to QGIS status bar buttons to show and clear the VESPER queue"""
        # source: https://gis.stackexchange.com/a/153170
        # https://github.com/ActiveState/code/blob/master/recipes/Python/578692_QGstartscript_Change_display/recipe-578692.py

        if not self.vesper_queue_showing:  # it is not initiated
            self.iface.mainWindow().statusBar().setSizeGripEnabled(False)
            self.lblVesperQueue = QLabel()
            self.lblVesperQueue.setText('{} tasks in VESPER queue'.format(len(self.vesper_queue)))
            self.iface.mainWindow().statusBar().insertPermanentWidget(1, self.lblVesperQueue)

            self.btnShowQueue = QToolButton()  # QToolButton() takes up less room
            self.btnShowQueue.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.btnShowQueue.setText("Show")
            self.btnShowQueue.clicked.connect(self.queueDisplay)
            self.iface.mainWindow().statusBar().insertPermanentWidget(2, self.btnShowQueue)

            self.btnClearQueue = QToolButton()  # QPushButton()
            self.btnClearQueue.setToolButtonStyle(Qt.ToolButtonTextOnly)
            self.btnClearQueue.setText("Clear")
            self.btnClearQueue.pressed.connect(self.queueClear)
            self.iface.mainWindow().statusBar().insertPermanentWidget(3, self.btnClearQueue)
            self.vesper_queue_showing = True

    def queueStatusBarHide(self):
        """Remove VESPER queue information and buttons from the status bar"""
        for obj in [self.btnClearQueue, self.btnShowQueue, self.lblVesperQueue]:
            self.iface.mainWindow().statusBar().removeWidget(obj)
            del obj

        self.vesper_queue_showing = False

    def processRunVesper(self):
        """Run the next task in the VESPER queue"""

        # Queueing: http://www.qtforum.org/article/32172/qprocess-how-to-run-multiple-processes-in-a-loop.html

        self.vesper_run_time = time.time()
        if self.processVesper is None:
            self.processVesper = QProcess()
            # set a duration variable
            self.processVesper.started.connect(self.processStartedVesper)
            # sets a task for when finished.
            self.processVesper.finished.connect(self.processFinishedVesper)

        self.queueStatusBarShow()

        ctrl_file = self.vesper_queue[0]['control_file']
        self.processVesper.setWorkingDirectory(os.path.dirname(ctrl_file))

        # run and catch when finished: https://gist.github.com/justinfx/5174795     1)QProcess
        QTimer.singleShot(100, partial(self.processVesper.start, self.vesper_exe, [ctrl_file]))

    def processStartedVesper(self):  # connected to process.started slot
        self.vesper_run_time = time.time()

    def processFinishedVesper(self, exitCode, exitStatus):  # connected to process.finished slot
        """When VESPER is complete, import the results to TIFF and QGIS"""
        currentTask = self.vesper_queue[0]

        if exitCode == 0 and exitStatus == QProcess.NormalExit:
            self.processVesper.close()
            self.processVesper = None

            if currentTask['epsg'] > 0:
                try:
                    out_PredTif, out_SETif, out_CITxt = vesper_text_to_raster(currentTask['control_file'],
                                                                              currentTask['epsg'])

                    removeFileFromQGIS(out_PredTif)
                    addRasterFileToQGIS(out_PredTif, atTop=False)
                    removeFileFromQGIS(out_SETif)
                    addRasterFileToQGIS(out_SETif, atTop=False)

                except Exception as err:
                    message = "Could not import from VESPER to raster TIFF possibly due to a " \
                              "VESPER error.\n{}".format(os.path.basename(currentTask['control_file']))

                    LOGGER.error(message)

            message = "Completed VESPER kriging for {}\t Duration H:M:SS - {dur}".format(
                        os.path.basename(currentTask['control_file']),
                        dur=datetime.timedelta(seconds=time.time() - self.vesper_run_time))
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.INFO, duration=15)
            LOGGER.info(message)

        else:
            message = "Error occurred with VESPER kriging for {}".format(currentTask['control_file'])
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.CRITICAL, duration=0)
            LOGGER.error(message)

        self.vesper_queue = self.vesper_queue[1:]  # remove the recently finished one which will always be at position 0

        self.lblVesperQueue.setText('{} tasks in VESPER queue'.format(len(self.vesper_queue)))

        if len(self.vesper_queue) > 0:
            self.vesper_run_time = time.time()
            self.processRunVesper()

        else:
            self.vesper_queue = []
            self.vesper_run_time = ''
            self.queueStatusBarHide()

        return

    def run_persistor(self):
        """Run method for the Calculate Image Indices dialog"""

        if parse_version(pyprecag.__version__) < parse_version('0.3.0'):
            self.iface.messageBar().pushMessage("Create t-test analysis tool is not supported in "
                                                "pyprecag {}. Upgrade to version 0.3.0+".format(
                pyprecag.__version__), level=QgsMessageBar.WARNING, duration=15)
            return

        dlgPersistor = PersistorDialog(self.iface)

        # Show the dialog
        dlgPersistor.show()

        if dlgPersistor.exec_():
            message = 'Persistor completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            # LOGGER.info(message)

        # Close Dialog
        dlgPersistor.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_wholeOfBlockAnalysis(self):
        """Run method for the fit to block grid dialog"""
        # https://gis.stackexchange.com/a/160146

        result = check_R_dependency()
        if result is not True:
            self.iface.messageBar().pushMessage("R configuration", result,
                                                level=QgsMessageBar.WARNING, duration=15)
            return

        proc_alg_mess = ProcessingAlgMessages(self.iface)
        QgsMessageLog.instance().messageReceived.connect(proc_alg_mess.processingCatcher)

        # Then get the algorithm you're interested in (for instance, Join Attributes):
        alg = Processing.getAlgorithm("r:wholeofblockanalysis")
        if alg is None:
            self.iface.messageBar().pushMessage("Whole-of-block analysis algorithm could not"
                                                " be found", level=QgsMessageBar.CRITICAL)
            return
        # Instantiate the commander window and open the algorithm's interface
        cw = CommanderWindow(self.iface.mainWindow(), self.iface.mapCanvas())
        if alg is not None:
            cw.runAlgorithm(alg)

        # if proc_alg_mess.alg_name == '' then cancel was clicked

        if proc_alg_mess.error:
            self.iface.messageBar().pushMessage("Whole-of-block analysis", proc_alg_mess.error_msg,
                                                level=QgsMessageBar.CRITICAL, duration=0)
        elif proc_alg_mess.alg_name != '':
            data_column = proc_alg_mess.parameters['Data_Column']

            # load rasters into qgis as grouped layers.
            for key, val in proc_alg_mess.output_files.items():

                grplyr = os.path.join('Whole-of-block {}'.format(data_column),  val['title'])

                for ea_file in val['files']:
                    removeFileFromQGIS(ea_file)
                    raster_layer = addRasterFileToQGIS(ea_file, group_layer_name=grplyr, atTop=False)
                    if key in ['p_val']:
                        raster_apply_unique_value_renderer(raster_layer)

            self.iface.messageBar().pushMessage("Whole-of-block analysis Completed Successfully!",
                                                level=QgsMessageBar.INFO, duration=15)

        del proc_alg_mess

    def run_stripTrialPoints(self):

        if parse_version(pyprecag.__version__) < parse_version('0.2.0'):
            self.iface.messageBar().pushMessage(
                "Create strip trial points tool is not supported in pyprecag {}. "
                "Upgrade to version 0.2.0+".format(pyprecag.__version__),
                level=QgsMessageBar.WARNING, duration=15)
            return

        """Run method for the Strip trial points dialog"""
        dlgStripTrialPoints = StripTrialPointsDialog(self.iface)

        # Show the dialog
        dlgStripTrialPoints.show()

        if dlgStripTrialPoints.exec_():
            message = 'Strip trial points created successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            # LOGGER.info(message)

        # Close Dialog
        dlgStripTrialPoints.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_tTestAnalysis(self):
        if parse_version(pyprecag.__version__) < parse_version('0.3.0'):
            self.iface.messageBar().pushMessage("Create t-test analysis tool is not supported in "
                                                "pyprecag {}. Upgrade to version 0.3.0+".format(
                pyprecag.__version__), level=QgsMessageBar.WARNING, duration=15)
            return

        """Run method for the Strip trial points dialog"""
        dlg_tTestAnalysis = tTestAnalysisDialog(self.iface)

        # Show the dialog
        dlg_tTestAnalysis.show()

        if dlg_tTestAnalysis.exec_():
            output_folder = dlg_tTestAnalysis.lneOutputFolder.text()
            import webbrowser
            try:
                from urllib import pathname2url         # Python 2.x
            except:
                from urllib.request import pathname2url # Python 3.x

            def open_folder():
                url = 'file:{}'.format(pathname2url(os.path.abspath(output_folder)))
                webbrowser.open(url)

            message = 'Strip trial t-test analysis completed!'

            # Add hyperlink to messagebar - this works but it places the text on the right, not left.
            # variation of QGIS-master\python\plugins\db_manager\db_tree.py
            # msgLabel = QLabel(self.tr('{0} <a href="{1}">{1}</a>'.format(message, output_folder)), self.iface.messageBar())
            # msgLabel.linkActivated.connect(open_folder)
            # self.iface.messageBar().pushWidget(msgLabel,level=QgsMessageBar.SUCCESS, duration=15)

            # so use a button instead
            widget = self.iface.messageBar().createMessage('', message)
            button = QPushButton(widget)
            button.setText('Open Folder')
            button.pressed.connect(open_folder)
            widget.layout().addWidget(button)
            self.iface.messageBar().pushWidget(widget, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlg_tTestAnalysis.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_kMeansClustering(self):
        """Run method for the Calculate Image Indices dialog"""
        dlgKMeansCluster = KMeansClusterDialog(self.iface)

        # Show the dialog
        dlgKMeansCluster.show()

        if dlgKMeansCluster.exec_():
            message = 'Zones with k-means clusters completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            # LOGGER.info(message)

        # Close Dialog
        dlgKMeansCluster.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_calculateImageIndices(self):
        """Run method for the Calculate Image Indices dialog"""
        dlgCalcImgIndices = CalculateImageIndicesDialog(self.iface)

        # Show the dialog
        dlgCalcImgIndices.show()

        if dlgCalcImgIndices.exec_():
            message = 'Image indices calculated successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgCalcImgIndices.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_resampleImage2Block(self):
        """Run method for the Resample image to block grid dialog"""
        dlgResample2Block = ResampleImageToBlockDialog(self.iface)

        # Show the dialog
        dlgResample2Block.show()

        if dlgResample2Block.exec_():
            message = 'Resample to block grid completed Successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgResample2Block.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_gridExtract(self):
        """Run method for the Grid Extract dialog"""
        dlgGridExtract = GridExtractDialog(self.iface)

        # Show the dialog
        dlgGridExtract.show()

        if dlgGridExtract.exec_():
            output_file = dlgGridExtract.lneSaveCSVFile.text()

            import webbrowser
            try:
                from urllib import pathname2url  # Python 2.x
            except:
                from urllib.request import pathname2url  # Python 3.x

            def open_folder():
                url = 'file:{}'.format(pathname2url(os.path.abspath(output_file)))
                webbrowser.open(url)

            message = 'Raster statistics for points extracted successfully !'
            #add a button to open the file outside qgis
            widget = self.iface.messageBar().createMessage('', message)
            button = QPushButton(widget)
            button.setText('Open File')
            button.pressed.connect(open_folder)
            widget.layout().addWidget(button)
            self.iface.messageBar().pushWidget(widget, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgGridExtract.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_generateRandomPixels(self):
        """Run method for the Generate random pixels dialog"""
        dlgGenRandomPixel = RandomPixelSelectionDialog(self.iface)

        # Show the dialog
        dlgGenRandomPixel.show()

        if dlgGenRandomPixel.exec_():
            message = 'Random pixel selection completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgGenRandomPixel.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_rescaleNormalise(self):
        """Run method for the rescale/normalise dialog"""
        dlgRescaleNorm = RescaleNormaliseDialog(self.iface)

        # Show the dialog
        dlgRescaleNorm.show()

        if dlgRescaleNorm.exec_():
            message = 'Rescale/Normalise completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgRescaleNorm.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_preVesper(self):
        """Run method for preVesper dialog"""

        dlgPreVesper = PreVesperDialog(self.iface)

        # show the dialog
        dlgPreVesper.show()

        if dlgPreVesper.exec_():
            if dlgPreVesper.gbRunVesper.isChecked():
                self.queueAddTo(dlgPreVesper.vesp_dict)
                self.processRunVesper()
                if len(self.vesper_queue) > 0:
                    self.lblVesperQueue.setText('{} tasks in VESPER queue'.format(len(self.vesper_queue)))

        # Close Dialog
        dlgPreVesper.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_postVesper(self):
        """Run method for importing VESPER results dialog"""
        dlgPostVesper = PostVesperDialog(self.iface)

        # show the dialog
        dlgPostVesper.show()

        if dlgPostVesper.exec_():
            if dlgPostVesper.chkRunVesper.isChecked():

                self.queueAddTo(dlgPostVesper.vesp_dict)
                # if this is the first in the queue then start the processing.
                self.processRunVesper()

                if len(self.vesper_queue) > 0:
                    self.lblVesperQueue.setText('{} tasks in VESPER queue'.format(len(self.vesper_queue)))

        # Close Dialog
        dlgPostVesper.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_cleanTrimPoints(self):
        """Run method for cleanTrimPoints dialog"""
        dlgCleanTrimPoints = CleanTrimPointsDialog(self.iface)

        # show the dialog
        dlgCleanTrimPoints.show()

        if dlgCleanTrimPoints.exec_():
            message = 'Cleaned and trimmed points successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgCleanTrimPoints.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_blockGrid(self):
        """Run method for the block grid dialog"""
        dlgBlockGrid = BlockGridDialog(self.iface)

        # Show the dialog
        dlgBlockGrid.show()

        if dlgBlockGrid.exec_():
            message = 'Block grid completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgBlockGrid.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_pointTrailToPolygon(self):
        """Run method for pointTrailToPolygon dialog"""
        dlgPointTrailToPolygon = PointTrailToPolygonDialog(self.iface)

        # show the dialog
        dlgPointTrailToPolygon.show()

        if dlgPointTrailToPolygon.exec_():
            message = 'On-the-go point trail to polygon completed successfully !'
            self.iface.messageBar().pushMessage(message, level=QgsMessageBar.SUCCESS, duration=15)
            LOGGER.info(message)

        # Close Dialog
        dlgPointTrailToPolygon.deleteLater()

        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_help(self):
        """Open the help PDF"""
        webbrowser.open_new('file:///' + os.path.join(PLUGIN_DIR, 'PAT_User_Manual.pdf#pagemode=bookmarks'))

    def run_about(self):
        """Run method for the about dialog"""
        dlgAbout = AboutDialog()
        if dlgAbout.exec_():
            pass

        dlgAbout.deleteLater()
        # Refresh QGIS
        QCoreApplication.processEvents()

    def run_settings(self):
        """Run method for the about dialog"""
        dlgSettings = SettingsDialog()
        if dlgSettings.exec_():
            self.vesper_exe = dlgSettings.vesper_exe
            self.DEBUG = config.get_debug_mode()

        dlgSettings.deleteLater()
