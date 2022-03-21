# coding=utf-8
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 custom_logging -  Provides logging functionality to both a log file, QGIS logging console.

           -------------------
        begin      : 2017-05-25
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au PAT@csiro.au
 ***************************************************************************/

 Modified from: inaSafe QGIS Plugin on 21/08/2017
     https://github.com/inasafe/inasafe/blob/develop/safe/common/custom_logging.py

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the associated CSIRO Open Source Software       *
 *   License Agreement (GPLv3) provided with this plugin.                  *
 *                                                                         *
 ***************************************************************************/
"""
from __future__ import print_function
from builtins import range
import logging
import os

from pat import PLUGIN_NAME, PLUGIN_SHORT, LOGGER_NAME, TEMPDIR

from qgis.PyQt.QtWidgets import QDockWidget, QTabWidget
from qgis.PyQt.Qt import QCoreApplication
from qgis.gui import QgsMessageBar
from qgis.core import QgsMessageLog, QgsProject, Qgis
from qgis.utils import iface

from util.settings import read_setting, write_setting
from util.check_dependencies import get_plugin_state

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

LOG_MAP = {'CRITICAL': {'logging': 50, 'qgis': 2},
           'ERROR': {'logging': 40, 'qgis': 2},
           'WARNING': {'logging': 30, 'qgis': 1},
           'INFO': {'logging': 20, 'qgis': 0},
           'DEBUG': {'logging': 10, 'qgis': 0},
           'NOTSET': {'logging': 0, 'qgis': 0},
           'SUCCESS': {'logging': 0, 'qgis': 0}}


class QgsLogHandler(logging.Handler):
    """A logging handler that will log messages to the QGIS logging console."""

    def __init__(self, level=logging.NOTSET):
        logging.Handler.__init__(self)
        self.lastRec = None

    def emit(self, record):
        """Try to log the message to QGIS if available, otherwise do nothing.

        Args:
            record (): logging record containing whatever info needs to be logged.

        Returns:

        """
        # ToDo:Add the warning/info messages to the form messagebar look at QGIS-master\python\utils.py\showException
        # ??https://gis.stackexchange.com/questions/152730/how-to-add-a-message-bar-to-custom-canvas
        # https://gis.stackexchange.com/questions/135711/why-is-the-display-of-qgsmessagebar-delayed
        # https://gis.stackexchange.com/a/216444
        # Check logging.LogRecord properties for lots of other goodies like line number etc. you can get
        # from the log message.
        try:
            if QgsMessageBar is None:
                return

            if self.lastRec is None or self.lastRec.getMessage() != record.getMessage():
                QgsMessageLog.logMessage(record.getMessage(), PLUGIN_SHORT, LOG_MAP[record.levelname]['qgis'])
                self.lastRec = record
            QCoreApplication.processEvents()

        except MemoryError:
            message = 'Due to memory limitations on this machine, PrecisionAg can not handle the full log'
            print(message)
            QgsMessageLog.logMessage(message, PLUGIN_SHORT, 0)
        except IOError:
            pass
        except AttributeError:
            pass


def stop_logging(logger_name):
    """ Stop and remove all loggers.
    This is used if the users wants to change the log level via the about dialog.

    Args:
        logger_name ():  The name of the logger to stop
    """
    logger = logging.getLogger(logger_name)
    for logger_handler in reversed(logger.handlers):
        logger_handler.close()
        logger.removeHandler(logger_handler)


def add_logging_handler_once(logger, handler):
    """A helper to add a handler to a logger, ensuring there are no duplicates.

    Args:
        logger (logging.logger): Logger that should have a handler added.
        handler (logging.Handler): Handler instance to be added. It will not be added if an
        instance of that Handler subclass already exists.

    Returns (bool) : True if the logging handler was added, otherwise False.
    """

    class_name = handler.__class__.__name__
    for logger_handler in logger.handlers:
        if logger_handler.__class__.__name__ == class_name:
            return False

    logger.addHandler(handler)
    return True


def set_log_file():
    
    old_file = os.path.normpath(read_setting(PLUGIN_NAME + '/LOG_FILE'))

    if not read_setting(PLUGIN_NAME + '/PROJECT_LOG', bool) or \
        QgsProject.instance().absolutePath()=='':
        folder = TEMPDIR
        log_file = os.path.normpath(os.path.join(TEMPDIR, 'PAT.log'))
    else:
        folder = os.path.normpath(os.path.join(QgsProject.instance().absolutePath()))
        
        if read_setting(PLUGIN_NAME + '/USE_PROJECT_NAME',bool):
            log_file = os.path.splitext(QgsProject.instance().fileName())[0] + '_PAT.log'
        else:
            log_file = os.path.normpath(os.path.join(folder, 'PAT.log'))

    #if folder != os.path.dirname(old_file) :
    if os.path.normpath(log_file) != os.path.normpath(old_file):
        # this only get triggered when the setting gets changed or project gets saved
        write_setting(PLUGIN_NAME + '/LOG_FILE', log_file)
    
        # Stop and start logging to setup the new log level
        stop_logging(LOGGER_NAME)
        setup_logger(LOGGER_NAME, log_file)
        
        iface.messageBar().pushMessage("Log File", log_file, level=Qgis.Info,duration=15)
        
        if not os.path.exists(log_file):
            LOGGER.info(get_plugin_state('basic'))
            
    return log_file


class Formatter(logging.Formatter):
    """https://stackoverflow.com/questions/14844970/modifying-logging-message-format-based-on-message-logging-level-in-python3"""
    def format(self, record):
        if record.levelno == logging.INFO:
            self._style._fmt = "%(message)s"
        elif record.levelno == logging.DEBUG:
            self._style._fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(name)-10s %(levelname)-8s  %(message)s", "%Y-%m-%d %H:%M:%S")
        else:
            self._style._fmt = "%(levelname)s: %(message)s"
        return super().format(record)

def setup_logger(logger_name, log_file=None):
    """
    Run once when the module is loaded and enable logging.

    logger_name (str):  The logger name that we want to set up.
    log_file (str): Optional full path to a file to write logs to.

    Borrowed heavily from http://docs.python.org/howto/logging-cookbook.html

    Now to log a message do::
       LOGGER.debug('Some debug message')

    Args:
        logger_name (): The name call the logger
        log_file (): the file to write log messages to.

    """

    if not os.path.exists(TEMPDIR):
        os.mkdir(TEMPDIR)
    
    debug =read_setting(PLUGIN_NAME + "/" + 'DEBUG', bool) 
    
    if debug:
        default_handler_level = logging.DEBUG
    else:
        default_handler_level = logging.INFO

    # Suppress the IOError: [Errno 9] Bad file descriptor when logging.
    # source: https://stackoverflow.com/a/35152695
    logging.raiseExceptions = False

    logger = logging.getLogger(logger_name)
    logger.setLevel(default_handler_level)
    add_logging_handler_once(logger, logging.NullHandler())

    # create formatter that will be added to the handlers
    # if debug:
    #     formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(name)-10s %(levelname)-8s  %(message)s","%Y-%m-%d %H:%M:%S")
    # else:
    #     formatter = logging.Formatter("%(levelname)-8s  %(message)s","%Y-%m-%d %H:%M:%S")

    # create syslog handler which logs even debug messages
    log_path = os.path.join(TEMPDIR, 'PAT.log')

    if log_file is None:
        file_handler = logging.FileHandler(log_path, delay=True)
    else:
        file_handler = logging.FileHandler(log_file, delay=True)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(Formatter())
    add_logging_handler_once(logger, file_handler)

    # create console handler with a higher log level
    # console_handler = logging.StreamHandler()
    # console_handler.setLevel(default_handler_level)
    # console_handler.setFormatter(formatter)
    # add_logging_handler_once(logger, console_handler)

    # create a QGIS handler
    qgis_handler = QgsLogHandler(default_handler_level)
    qgis_handler.setFormatter(Formatter())
    add_logging_handler_once(logger, qgis_handler)


def errorCatcher(msg, tag, level):
    """ Catch errors which are directed to the python errors Log Messages tab, and add them to the log.

    source:https://gis.stackexchange.com/a/223965

    Args:
        msg (str): The error message usually in the form of a traceback.
        tag (str): The Log Messages Tab the message is directed at.
        level (int): The error level of the message
    """

    try:
        if level > 0 and PLUGIN_NAME in msg:
            if tag == 'Python error':
                LOGGER.error(msg)

            elif tag == 'Processing':
                LOGGER.error(msg)

    except Exception as err:
        pass


def openLogPanel():
    logMessagesPanel = iface.mainWindow().findChild(QDockWidget, 'MessageLog')

    # Check to see if it is already open
    if not logMessagesPanel.isVisible():
        logMessagesPanel.setVisible(True)

    # find and set the active tab
    tabWidget = logMessagesPanel.findChildren(QTabWidget)[0]
    for iTab in range(0, tabWidget.count()):
        if tabWidget.tabText(iTab) == PLUGIN_SHORT:
            tabWidget.setCurrentIndex(iTab)
            break

    QCoreApplication.processEvents()


def clearPythonConsole():
    # https://gis.stackexchange.com/a/216444
    from qgis.PyQt.QtWidgets import QDockWidget
    consoleWidget = iface.mainWindow().findChild(QDockWidget, 'PythonConsole')
    consoleWidget.console.shellOut.clearConsole()
