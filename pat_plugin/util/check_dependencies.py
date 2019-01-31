# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 check_dependencies -  Functions related to checking VESPER and python dependencies
                       required by the PAT plugin
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
import pkg_resources

"""DO NOT CHANGE THE IMPORT ORDER OR OPTIMISE. IT WILL INTRODUCE AN ERROR....."""

import pkgutil
import os
import platform
import subprocess
import tempfile
import shutil
import sys
import logging
from pkg_resources import parse_version

from PyQt4.QtGui import QMessageBox
from qgis.gui import QgsMessageBar

import osgeo.gdal
import win32api
from win32com.shell import shell, shellcon
import pythoncom
import struct

from pat_plugin import LOGGER_NAME, PLUGIN_NAME
from pat_plugin.util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

# max version of GDAL supported via the specified wheel. 
GDAL_WHEELS = {"2.3.2": {'fiona': 'Fiona-1.8.4-cp27-cp27m',
                         'rasterio': 'rasterio-1.0.13-cp27-cp27m',
                         'pyprecag': 'pyprecag-0.2.1'}}
               
               
def check_gdal_dependency():
        # get the list of wheels matching the gdal version
    if not os.environ.get('GDAL_VERSION', None):
        gdal_ver = osgeo.gdal.__version__
        LOGGER.warning('Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
        os.environ['GDAL_VERSION'] = gdal_ver

    gdal_ver = os.environ.get('GDAL_VERSION', None)
    wheels=None
    for key, val in sorted(GDAL_WHEELS.iteritems()):
        if parse_version(gdal_ver) <= parse_version(key):
            wheels = val
    
    if wheels is None: 
        return gdal_ver, False
    
    return gdal_ver, wheels
    
    
def check_vesper_dependency(iface=None):
    """ Check for the vesper exe as specified in the pyprecag config.json file. If the exe string is invalid, or does
    not exist it will return None.

    It will check in the default installed location for VESPER and notify user if missing. If it is
    missing the user can still use PAT tools but not run the VESPER kriging.

    Args:
        :param iface: A QGIS interface instance.
        :type iface: QgsInterface
    Returns:
        str() : String containing vesper exe.
    
    """

    vesper_exe = read_setting(PLUGIN_NAME + '/VESPER_EXE')
    
    if vesper_exe is None or vesper_exe == '' or not os.path.exists(vesper_exe):
        # Update if Vesper is installed.
        if os.path.exists(r'C:/Program Files (x86)/Vesper/Vesper1.6.exe'):
            vesper_exe = r'C:/Program Files (x86)/Vesper/Vesper1.6.exe'

        else:  # Otherwise report it.
            if vesper_exe == '' or vesper_exe == None:
                message = 'Vesper*.exe not found. Please install and configure to allow for kriging to occur'
            elif not os.path.exists(vesper_exe):
                message = 'Vesper*.exe at "{}" does not exist. Please install and configure to allow for kriging to occur'.format(
                        vesper_exe)

            vesper_exe = ''

            if iface:
                iface.messageBar().pushMessage("WARNING", message, level=QgsMessageBar.WARNING,
                                               duration=15)
            else:
                LOGGER.warn(message)

        write_setting(PLUGIN_NAME + '/VESPER_EXE', vesper_exe)

    return vesper_exe


def writeLineToFileS(line, openFileList=[]):
    """Write a single line to multiple files"""

    if len(openFileList) > 0:
        for eafile in openFileList:
            eafile.write(line)


def check_package(package):
    """Check to see if a package is installed and what version it is.

    If a package is missing, a dictionary of {'Action': 'Install', 'Version': ''} is returned.
    otherwise {'Action': '', 'Version': 'package version'} is returned.

    Args:
        package (str): the name of the package

    Returns {dict}: a dictionary containing actions required, and which version is installed.
    """
    
    _, wheels = check_gdal_dependency()
    
    try:
        pack_dict = pack_dict = {'Action': '','Version': pkg_resources.get_distribution(package).version, 'Wheel':''}
    except pkg_resources.DistributionNotFound:
        if package in wheels:
            pack_dict = pack_dict = {'Action': 'Install', 'Version': '', 'Wheel' : wheels[package]}

    # Check for upgraded packages
    if pack_dict['Action'] != 'Install' and package in wheels:
        # compare version numbers source: https://stackoverflow.com/a/6972866
        if parse_version(pack_dict['Version']) < parse_version(wheels[package].split('-')[1]):
            pack_dict['Action'] = 'Upgrade'
            pack_dict['Wheel'] = wheels[package]

    return pack_dict


def get_pip_version(package):
    """ Find the version of the package using pip
       Note: Running this against all packages is slow so only run when required.

    Args:
        package (str): The name of the package to check

    Returns (str): a string representing the version of the package

    """

    try:
        from subprocess import DEVNULL

    except ImportError:
        DEVNULL = os.open(os.devnull, os.O_RDWR)

    pip_info = subprocess.check_output(['python', '-m', 'pip', 'show', package], shell=True, stdin=DEVNULL,
                                       stderr=DEVNULL)

    # from this extract the version
    ver = next((line.split(":", 1)[1].strip() for line in pip_info.splitlines() if line.startswith("Version")), "")

    return ver


def check_python_dependencies(plugin_path, iface):
    """ Check for extra python modules which the plugin requires.

    If they are not installed, a windows batch file will be created on the users desktop. Run this as administrator
    to install relevant packages

    Args:
         iface (): The QGIs gui interface required to add messagebar too.
         plugin_path (): The path to the users plugin directory.

    Returns (bool): Passed Check or Not.
    """

    # get the list of wheels matching the gdal version
    if not os.environ.get('GDAL_VERSION', None):
        gdal_ver = osgeo.gdal.__version__
        LOGGER.warning('Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
        os.environ['GDAL_VERSION'] = gdal_ver

    packCheck = {}
    # Check for the listed modules.
    for argCheck in ['fiona', 'rasterio', 'pyprecag']:
        packCheck[argCheck] = check_package(argCheck)

    failDependencyCheck = [key for key, val in packCheck.iteritems() if val['Action'] in ['Install', 'Upgrade']]

    # the install needs to be against the QGIS python package, so set the relevant variables in the bat file.
    osgeo_path = os.environ['OSGEO4W_ROOT']
    qgis_prefix_path = win32api.GetLongPathName(os.environ['QGIS_PREFIX_PATH'])

    # check to see if the qgis_customwidgets.py file is in the python folder.
    custWidFile = os.path.join(win32api.GetLongPathName(osgeo_path), 'apps', 'Python27', 'Lib', 'site-packages',
                               'PyQt4', 'uic', 'widget-plugins',
                               'qgis_customwidgets.py')

    tmpDir = os.path.join(tempfile.gettempdir())
    tempPackPath = os.path.join(tmpDir, 'python_packages')

    if not os.path.exists(custWidFile):
        failDependencyCheck.append('qgis_customwidgets')
        print('qgis_customwidgets does not exist')

    if platform.system() != 'Windows': return False

    # get the install file.
    title = 'Install_PAT_Extras'
    uninstall_file = os.path.join(plugin_path, 'python_packages', 'Un{}.bat'.format(title))

    if len(failDependencyCheck) == 0:  # if passes always create the file in plugin path anyway as a reference
        install_file = os.path.join(plugin_path, 'python_packages', title + '.bat')
    else:
        install_file = os.path.join(tempPackPath, title + '.bat')
        # copy python_packages folder to temp
        if os.path.exists(tempPackPath):
            shutil.rmtree(tempPackPath, ignore_errors=True)

        shutil.copytree(os.path.join(plugin_path, 'python_packages'), tempPackPath)

    bat_logfile = os.path.join(plugin_path, 'python_packages', 'dependancy.log')
    user_path = os.path.join(os.path.expanduser('~'))
    shortcutPath = os.path.join(user_path, 'Desktop', title.replace('_', ' ') + '.lnk')
    python_version = struct.calcsize("P") * 8  # this will return 64 or 32

    # write the headers for both files at once.
    with open(uninstall_file, 'w') as wUnFile, open(install_file, 'w') as wInFile:
        # Write to both files.
        writeLineToFileS("@echo off\n", [wUnFile, wInFile])
        writeLineToFileS('cd %~dp0 \n', [wUnFile, wInFile])

        # Check to see if qgis is running before un/installing
        writeLineToFileS(r'tasklist /FI "IMAGENAME eq qgis*" 2>NUL | find /I /N "qgis">NUL' + '\n',
                         [wUnFile, wInFile])
        writeLineToFileS(r'if "%ERRORLEVEL%"=="0" ( ' + '\n', [wUnFile, wInFile])
        writeLineToFileS('   echo QGIS is Currently Running. Please save your work and close \n   pause\n',
                         [wUnFile, wInFile])
        writeLineToFileS(r'   tasklist /FI "IMAGENAME eq qgis*" 2>NUL | find /I /N "qgis">NUL' + '\n',
                         [wUnFile, wInFile])
        writeLineToFileS(
            '   if "%ERRORLEVEL%"=="0" (\n   ECHO QGIS is Still taskkill /FI "IMAGENAME eq qgis* Running. Proceeding to Kill QGIS without saving.\n',
            [wUnFile, wInFile])
        writeLineToFileS(r'      taskkill /FI "IMAGENAME eq qgis*" /F' + '\n        ) \n    )\n\n',
                         [wUnFile, wInFile])

        # this will write to console.
        wUnFile.write('ECHO. & ECHO Uninstalling dependencies for QGIS PAT Plugin .... Please Wait\n')
        wInFile.write('ECHO. & ECHO Installing dependencies for QGIS PAT Plugin .... Please Wait\n')
        writeLineToFileS('ECHO Dependencies Log:{}\n'.format(bat_logfile), [wUnFile, wInFile])
        writeLineToFileS(
            'ECHO. & ECHO ----------------------------------------------------------------------------\n\n',
            [wUnFile, wInFile])

        # Create an empty file to log to....
        writeLineToFileS('type NUL > {}\n'.format(bat_logfile), [wUnFile, wInFile])
        writeLineToFileS('CALL :PROCESS > {}\n'.format(bat_logfile), [wUnFile, wInFile])
        writeLineToFileS('GOTO :END \n', [wUnFile, wInFile])
        writeLineToFileS('\n\n', [wUnFile, wInFile])

        writeLineToFileS(':PROCESS\n', [wUnFile, wInFile])
        # this will add it to the dependencies log
        wUnFile.write('ECHO Uninstalling dependencies for QGIS PAT Plugin\n\n')
        wInFile.write('ECHO Installing dependencies for QGIS PAT Plugin\n\n')

        writeLineToFileS("   SET OSGEO4W_ROOT={}\n".format(osgeo_path), [wUnFile, wInFile])
        if not os.environ.get('GDAL_VERSION', None):
            writeLineToFileS("   SET GDAL_VERSION={}\n".format(gdal_ver), [wUnFile, wInFile])

        # any line containing a path needs to be a raw string, and the end-of-line added separately
        writeLineToFileS(r'   call "%OSGEO4W_ROOT%"\bin\o4w_env.bat' + '\n', [wUnFile, wInFile])
        writeLineToFileS(r"   set QGIS_PREFIX_PATH={}".format(qgis_prefix_path) + '\n', [wUnFile, wInFile])
        writeLineToFileS(r"   path %PATH%;%QGIS_PREFIX_PATH%\bin" + '\n', [wUnFile, wInFile])
        writeLineToFileS(r"   set PYTHONPATH=%PYTHONPATH%;%QGIS_PREFIX_PATH%\python" + '\n', [wUnFile, wInFile])
        writeLineToFileS(r"   set PYTHONPATH=%PYTHONPATH%;%OSGEO4W_ROOT%\apps\Python27\Lib\site-packages" + '\n\n',
                         [wUnFile, wInFile])

        wUnFile.write('   ECHO Y|python -m pip uninstall pyprecag  --disable-pip-version-check\n')
        wUnFile.write('   ECHO Y|python -m pip uninstall rasterio  --disable-pip-version-check\n')
        wUnFile.write('   ECHO Y|python -m pip uninstall fiona  --disable-pip-version-check\n')
        
        wUnFile.write('\n:END \n')
        wUnFile.write('   type {} \n'.format(bat_logfile))
        wUnFile.write('   goto:eof')
        wUnFile.close()

        if not os.path.exists(custWidFile) or len(failDependencyCheck) == 0:
            if len(failDependencyCheck) > 0: LOGGER.warning('Missing Dependency: {} '.format(custWidFile))
            wInFile.write('   ECHO Missing Dependency: {} \n'.format(custWidFile))
            wInFile.write('   ECHO Copying qgis_customwidgets.py \n')
            wInFile.write(
                r'   ECHO F|xcopy "%QGIS_PREFIX_PATH%\python\PyQt4\uic\widget-plugins\qgis_customwidgets.py" "'
                + custWidFile + '" /y \n')

        wInFile.write(
            '\n   ECHO. & ECHO ----------------------------------------------------------------------------\n')

        for ea_pack in ['fiona','rasterio', 'pyprecag']:
            
            if ea_pack in failDependencyCheck or len(failDependencyCheck) == 0:
                wInFile.write(
                    '\n\n   ECHO. & ECHO ----------------------------------------------------------------------------\n')
                wInFile.write('   ECHO {} {}bit {} and dependencies\n'.format(packCheck[ea_pack]['Action'] ,
                                                                                      python_version,ea_pack))
                if ea_pack == 'pyprecag':
                    if packCheck[ea_pack]['Action'] == 'Upgrade':
                        whl_file = 'pyprecag --upgrade'
                    else: 
                        whl_file = 'pyprecag'
                else:
                    if python_version == 32:
                        whl_file = os.path.join(ea_pack, packCheck[ea_pack]['Wheel'] + '-win32.whl')
                    else:
                        whl_file = os.path.join(ea_pack, packCheck[ea_pack]['Wheel'] + '-win_amd64.whl')

                wInFile.write(r'   python -m pip install {} --disable-pip-version-check'.format(whl_file) + '\n')

        wInFile.write(
            '\n   ECHO. & ECHO ----------------------------------------------------------------------------\n')
        wInFile.write('\n' + r'   EXIT /B' + '\n')  # will return to the position where you used CALL

        wInFile.write('\n:END \n')
        wInFile.write('   cls\n')  # clear the cmd window of all text
        wInFile.write('   type {} \n'.format(bat_logfile))  # then print the logfile to screen

        wInFile.write(
            '\n   ECHO. & ECHO ----------------------------------------------------------------------------\n')

        wInFile.write('   ECHO.\n')
        wInFile.write('   ECHO All files and folders used in this install will self destruct.\n')
        wInFile.write('   ECHO.\n')
        wInFile.write('   ECHO ** Please restart QGIS to complete installation.\n')
        wInFile.write(
            '   ECHO You may have to reinstall or activate the PAT Plugin through the plugin manager.\n')
        wInFile.write('   ECHO.\n')
        wInFile.write('   pause\n')
        wInFile.write('   ECHO.\n')

        if len(failDependencyCheck) > 0:
            wInFile.write('   ECHO Deleting desktop shortcut\n')
            wInFile.write('   DEL "{}"\n'.format(shortcutPath))
            wInFile.write('   ECHO Deleting {}\n'.format(tempPackPath))
            wInFile.write('   (goto) 2>nul & rmdir /S /Q "{}"\n'.format(tempPackPath))

        wInFile.write('   goto:eof')

    # Create a shortcut on desktop with admin privileges.
    # Source:https://stackoverflow.com/questions/37049108/create-windows-explorer-shortcut-with-run-as-administrator
    if len(failDependencyCheck) > 0:
        # TODO: Implement running the BAT file from within QGIS see https://jira.csiro.au/browse/PA-67
        LOGGER.critical(
            "Failed Dependency Check. Please run the shortcut {} or the following bat file as administrator {}".format(
                shortcutPath, install_file))

        create_link(shortcutPath, install_file, "Install setup for QGIS PAT Plugin", user_path, True)

        message = 'Please quit QGIS and run {} located on your desktop to install ' \
                  'dependencies. Dependencies not met are {}'.format(title, ', '.join(failDependencyCheck))
        iface.messageBar().pushMessage("ERROR Failed Dependency Check", message, level=QgsMessageBar.CRITICAL,
                                       duration=0)
        QMessageBox.critical(None, 'Failed Dependency Check', message)
        sys.exit(message)

    return failDependencyCheck


def create_link(link_path, target_path, description=None, directory=None,
                run_as_admin=False):
    """Create a shortcut to the target path and assign run as administrator flags.

    Args:
        link_path (str): The path and name of the link (shortcut) destination file
        target_path (str): Create Shortcut for this file
        description (str): A brief description
        directory (str):  The start folder for the shortcut
        run_as_admin (bool): Set to Run As Administrator

    """
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(target_path)
    if description is not None:
        link.SetDescription(description)
    if directory is not None:
        link.SetWorkingDirectory(directory)
    if run_as_admin:
        link_data = link.QueryInterface(shell.IID_IShellLinkDataList)
        link_data.SetFlags(link_data.GetFlags() | shellcon.SLDF_RUNAS_USER)
    file_link = link.QueryInterface(pythoncom.IID_IPersistFile)
    file_link.Save(link_path, 0)
