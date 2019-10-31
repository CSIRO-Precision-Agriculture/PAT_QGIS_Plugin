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


"""DO NOT CHANGE THE IMPORT ORDER OR OPTIMISE. IT WILL INTRODUCE AN ERROR....."""

import os
import traceback
import glob
import platform
import configparser
import subprocess
import tempfile
from distutils import file_util
import shutil
import sys
import logging
from datetime import date, datetime
import requests
from pkg_resources import parse_version, get_distribution, DistributionNotFound

from PyQt4.QtGui import QMessageBox
import qgis
from qgis.gui import QgsMessageBar
from qgis.core import QgsStyleV2, QgsSymbolLayerV2Utils

from PyQt4.QtXml import QDomDocument
from PyQt4.QtCore import QFile, QIODevice

import osgeo.gdal

if platform.system() == 'Windows':
    import win32api
    from win32com.shell import shell, shellcon
    from winreg import ConnectRegistry, OpenKey, QueryValueEx, HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER

import pythoncom
import struct

from pat import LOGGER_NAME, PLUGIN_NAME, PLUGIN_DIR
from util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()

# max version of GDAL supported via the specified wheel.
GDAL_WHEELS = {"2.3.2": {'fiona': 'Fiona-1.8.4-cp27-cp27m',
                         'rasterio': 'rasterio-1.0.13-cp27-cp27m',
                         'pyprecag': 'pyprecag-0.3.0'}}  # this is the minimum version of pyprecag supported by PAT


def check_pat_symbols():
    pat_xml = os.path.join(PLUGIN_DIR, 'PAT_Symbols.xml')
    if not os.path.exists(pat_xml):
        return

    loaded_date = read_setting(PLUGIN_NAME + "/PAT_SYMBOLOGY")
    if loaded_date is not None:
        loaded_date = datetime.strptime(loaded_date,'%Y-%m-%d %H:%M:%S')

    xml_date = datetime.fromtimestamp(os.path.getmtime(pat_xml)).replace(microsecond=0)

    if loaded_date is None or xml_date > loaded_date:
        style = QgsStyleV2.defaultStyle()

        # add a group if it doesn't exist.
        group_id = style.groupId('PAT')
        if group_id == 0:
            group_id = style.addGroup('PAT')

        xml_file = QFile(pat_xml)

        document = QDomDocument()
        if not document.setContent(xml_file):
            LOGGER.debug('Could not open file {}'.format(xml_file))
            return

        xml_file.close()

        document_element = document.documentElement()
        if document_element.tagName() != 'qgis_style':
            LOGGER.debug("File {} doesn't contain qgis styles".format(xml_file))
            return

        # Get all the symbols
        symbols = []
        symbols_element = document_element.firstChildElement('symbols')
        symbol_element = symbols_element.firstChildElement()
        while not symbol_element.isNull():
            if symbol_element.tagName() == 'symbol':
                symbol = QgsSymbolLayerV2Utils.loadSymbol(symbol_element)
                if symbol:
                    symbols.append({
                        'name': symbol_element.attribute('name'),
                        'symbol': symbol
                    })
            symbol_element = symbol_element.nextSiblingElement()

        # Get all the colorramps
        colorramps = []
        ramps_element = document_element.firstChildElement('colorramps')
        ramp_element = ramps_element.firstChildElement()
        while not ramp_element.isNull():
            if ramp_element.tagName() == 'colorramp':
                colorramp = QgsSymbolLayerV2Utils.loadColorRamp(ramp_element)
                if colorramp:
                    colorramps.append({
                        'name': ramp_element.attribute('name'),
                        'colorramp': colorramp
                    })

            ramp_element = ramp_element.nextSiblingElement()

        for symbol in symbols:
            if style.addSymbol(symbol['name'], symbol['symbol'], True):
                style.group(QgsStyleV2.SymbolEntity, symbol['name'], group_id)

        for colorramp in colorramps:
            if style.addColorRamp(colorramp['name'], colorramp['colorramp'], True):
                style.group(QgsStyleV2.ColorrampEntity, colorramp['name'], group_id)

        LOGGER.info(
            'Loaded {} symbols and {} colour ramps into group {}'.format(len(symbols), len(colorramps),
                                                                         style.groupName(group_id)))

        write_setting(PLUGIN_NAME + '/PAT_SYMBOLOGY', xml_date.strftime('%Y-%m-%d %H:%M:%S'))

    return

def check_R_dependency():
    updated = False
    r_installfold = read_setting('Processing/Configuration/R_FOLDER')
    if platform.system() == 'Windows':
        try:
            aReg = ConnectRegistry(None, HKEY_LOCAL_MACHINE)
            aKey = OpenKey(aReg, r"SOFTWARE\R-core\R")
            aVal = os.path.normpath(QueryValueEx(aKey, "InstallPath")[0])

            if os.path.exists(aVal):
                if r_installfold is not None and r_installfold != aVal:
                    r_installfold = aVal
                    write_setting('Processing/Configuration/R_FOLDER', aVal)
                    LOGGER.info('Setting ... R Install folder: {}'.format(aVal))
            r_installed = True

        except EnvironmentError:
            r_installed = False
            write_setting('Processing/Configuration/R_FOLDER', '')
            write_setting('Processing/Configuration/ACTIVATE_R', False)
            return 'R is not installed or not configured for QGIS.\n See "Configuring QGIS to use R" in help documentation'

    else:
        # Linux/OSX - https://stackoverflow.com/a/25330049
        try:
            subprocess.check_call(['which', 'R'])
        except subprocess.CalledProcessError:
            r_installed = False
        else:
            r_installed = True

    if not r_installed:
        write_setting('Processing/Configuration/R_FOLDER', '')
        write_setting('Processing/Configuration/ACTIVATE_R', False)
        return 'R is not installed or not configured for QGIS.\n See "Configuring QGIS to use R" in help documentation'

    # Get the users R script folder - returns none if not set.
    r_scripts_fold = read_setting('Processing/Configuration/R_SCRIPTS_FOLDER')

    if r_scripts_fold is None:
        return 'R is not installed or not configured for QGIS.\n See "Configuring QGIS to use R" in help documentation'

    files = glob.glob(os.path.join(PLUGIN_DIR, "R-Scripts", "*.rsx"))
    files += glob.glob(os.path.join(PLUGIN_DIR, "R-Scripts", "*.rsx.help"))

    for src_file in files:
        dest_file = os.path.join(r_scripts_fold, os.path.basename(src_file))

        # update flag will only update if file doesnt exist or is newer and returns a tuple of
        # all files with a 1 if the file was copied
        if file_util.copy_file(src_file, dest_file, update=True)[-1]:
            LOGGER.info('Installing or Updating Whole-of-block analysis tool.')

        # # only copy if it doesn't exist or it is newer by 1 second.
        # if not os.path.exists(dest_file) or os.stat(src_file).st_mtime - os.stat(
        #         dest_file).st_mtime > 1:
        #     shutil.copy2(src_file, dest_file)

    return True


def check_gdal_dependency():
    # get the list of wheels matching the gdal version
    if not os.environ.get('GDAL_VERSION', None):
        gdal_ver = osgeo.gdal.__version__
        LOGGER.warning(
            'Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
        os.environ['GDAL_VERSION'] = gdal_ver

    gdal_ver = os.environ.get('GDAL_VERSION', None)
    wheels = None
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
    vesper_exe = ''
    message = ''
    if platform.system() == 'Windows':
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
            write_setting(PLUGIN_NAME + '/VESPER_EXE', vesper_exe)
    else:
        message = 'VESPER is only supported on Windows.'

    if message != '':
        if iface:
            iface.messageBar().pushMessage("WARNING", message, level=QgsMessageBar.WARNING,
                                           duration=15)
        else:
            LOGGER.warn(message)

    return vesper_exe


def writeLineToFileS(line, openFileList=[]):
    """Write a single line to multiple files"""

    if len(openFileList) > 0:
        for eafile in openFileList:
            eafile.write(line)


def check_package(package):
    """Check to see if a package is installed and what version it is.

    Returns a dictionary containing:
        Action is Install, Upgrade or None
        Version is the installed version, if not installed will be ''
        Wheel the wheel file or version.
    for each package

    Args:
        package (str): the name of the package

    Returns {dict}: a dictionary containing actions required, and which version is installed.
    """

    _, wheels = check_gdal_dependency()

    try:
        pack_dict = pack_dict = {'Action': 'None',
                                 'Version': get_distribution(package).version,
                                 'Wheel': wheels[package]}
    except DistributionNotFound:
        if package in wheels:
            pack_dict = pack_dict = {'Action': 'Install',
                                     'Version': '',
                                     'Wheel': wheels[package]}

    # Check for upgraded packages
    if pack_dict['Action'] != 'Install' and package in wheels:
        # compare version numbers source: https://stackoverflow.com/a/6972866
        if parse_version(pack_dict['Version']) < parse_version(wheels[package].split('-')[1]):
            pack_dict['Action'] = 'Upgrade'
            pack_dict['Wheel'] = wheels[package]

    return pack_dict


def check_pip_for_update(package):
    """ Check a package against online pip via json get the most current release
    version number

    source: https://stackoverflow.com/a/40745656
    """
    url = 'https://pypi.python.org/pypi/{}/json'.format(package)
    try:
        releases = requests.get(url).json()['releases']
        current_version = sorted(releases, key=parse_version, reverse=True)[0]
        return current_version
    except requests.ConnectionError:
        LOGGER.info('Skipping pyprecag version check. Cannot reach {}'.format(url))
    return

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

    pip_info = subprocess.check_output(['python', '-m', 'pip', 'show', package], shell=True,
                                       stdin=DEVNULL,
                                       stderr=DEVNULL)

    # from this extract the version
    ver = next((line.split(":", 1)[1].strip() for line in pip_info.splitlines() if
                line.startswith("Version")), "")

    return ver


def check_python_dependencies(plugin_path, iface):
    """ Check for extra python modules which the plugin requires.

    If they are not installed, a windows batch file will be created on the users desktop.
    Run this as administrator to install relevant packages

    Args:
         iface (): The QGIs gui interface required to add messagebar too.
         plugin_path (): The path to the users plugin directory.

    Returns (bool): Passed Check or Not.
    """

    try:
        meta_version = get_plugin_version()  # comes from metadata.txt

        # get the list of wheels matching the gdal version
        if not os.environ.get('GDAL_VERSION', None):
            gdal_ver = osgeo.gdal.__version__
            LOGGER.warning(
                'Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
            os.environ['GDAL_VERSION'] = gdal_ver

        # the name of the install file.
        title = 'Install_PAT_Extras'
        if platform.system() == 'Windows':
            tmpDir = os.path.join(tempfile.gettempdir())
            tempPackPath = os.path.join(tmpDir, 'python_packages')

            user_path = os.path.join(os.path.expanduser('~'))
            shortcutPath = os.path.join(user_path, 'Desktop', title.replace('_', ' ') + '.lnk')

            # check to see if it has recently been installed, if so copy the logs to the plugin
            # folder and remove the folder from temp.
            if os.path.exists(tempPackPath):
                log_files = glob.glob(os.path.join(tempPackPath, "*.log"))
                if len(log_files) >= 0:
                    for log_file in log_files:
                        if 'tar.gz' in log_file:
                            bug_fix_fold = os.path.join(plugin_path, 'python_packages',
                                                        'installed_bugfix')
                            if not os.path.exists(bug_fix_fold):
                                os.makedirs(bug_fix_fold)

                            upgrade_file = glob.glob(os.path.join(plugin_path, 'python_packages',
                                                                  'pyprecag' + "*.tar.gz"))
                            if len(upgrade_file) == 1:
                                new_tar = os.path.join(bug_fix_fold,
                                                       os.path.basename(upgrade_file[0]))
                                if os.path.exists(new_tar):
                                    os.remove(new_tar)
                                shutil.move(upgrade_file[0], new_tar)
                        else:
                            new_log = os.path.join(plugin_path, 'python_packages', os.path.basename(log_file))

                            if os.path.exists(new_log):
                                os.remove(new_log)
                            shutil.copy(log_file, new_log)

                shutil.rmtree(tempPackPath, ignore_errors=True)
                if os.path.exists(shortcutPath):
                    os.remove(shortcutPath)


        packCheck = {}
        # Check for the listed modules.
        for argCheck in ['fiona', 'rasterio', 'pyprecag']:
            packCheck[argCheck] = check_package(argCheck)

        # Install via a tar wheel file prior to publishing via pip to test pyprecag bug fixes
        if len(glob.glob1(os.path.join(plugin_path, 'python_packages'), "pyprecag*")) == 1:
            packCheck['pyprecag']['Action'] = 'Upgrade'

        if packCheck['pyprecag']['Action'] != 'Install':
            # check pyprecag against pypi for bug fixes
            cur_pyprecag_ver = check_pip_for_update('pyprecag')
            if cur_pyprecag_ver is not None:
                if parse_version(packCheck['pyprecag']['Version']) < parse_version(cur_pyprecag_ver):
                    packCheck['pyprecag']['Action'] = 'Upgrade'

        failDependencyCheck = [key for key, val in packCheck.iteritems() if
                               val['Action'] in ['Install', 'Upgrade']]

        if platform.system() == 'Windows':
            # the install needs to be against the QGIS python package, so set the relevant
            # variables in the bat file.
            osgeo_path = os.path.abspath(win32api.GetLongPathName(os.environ['OSGEO4W_ROOT']))
            qgis_prefix_path = os.path.abspath(
                win32api.GetLongPathName(os.environ['QGIS_PREFIX_PATH']))

            # check to see if the qgis_customwidgets.py file is in the python folder.
            src_custom_widget = os.path.join(qgis_prefix_path, 'python', 'PyQt4', 'uic',
                                             'widget-plugins',
                                             'qgis_customwidgets.py')

            dst_custom_widget = os.path.join(osgeo_path, 'apps', 'Python27',
                                             'Lib', 'site-packages', 'PyQt4', 'uic',
                                             'widget-plugins',
                                             'qgis_customwidgets.py')

            if not os.path.exists(dst_custom_widget):
                failDependencyCheck.append('qgis_customwidgets')
                print('qgis_customwidgets does not exist')

            uninstall_file = os.path.join(plugin_path, 'python_packages', 'Un{}.bat'.format(title))

            install_file = os.path.join(plugin_path, 'python_packages', title + '.bat')

            bat_logfile = 'dependency_{}.log'.format(date.today().strftime("%Y-%m-%d"))
            pip_logfile = 'pip_uninstall_{}.log'.format(date.today().strftime("%Y-%m-%d"))

            pip_args_uninstall = ' --log "{}" --no-cache-dir --disable-pip-version-check'.format(pip_logfile)
            pip_args_install = ' --log "{}" --no-cache-dir --disable-pip-version-check'.format(pip_logfile.replace('_un', '_'))

            python_version = struct.calcsize("P") * 8  # this will return 64 or 32

            for bat_file, inst in [(uninstall_file, 'Unin'), (install_file, 'In')]:
                #if os.path.exists(bat_file):
                    #os.remove(bat_file)
                    #LOGGER.info('Deleted {}'.format(bat_file))

                # Rules: no spaces at the end of SET lines
                with open(bat_file, 'w') as w_bat_file:
                    w_bat_file.write(
                        ('@echo off {nl}'
                         'cd %~dp0 {nl}'
                         # Check to see if qgis is running before un/installing
                         'tasklist /FI "IMAGENAME eq qgis*" 2>NUL | find /I /N "qgis">NUL {nl}'
                         'if "%ERRORLEVEL%"=="0" ( {nl}'
                         '   echo QGIS is Currently Running. Please save your work and close {nl}'
                         '   pause {nl}{nl}'
                         '   tasklist /FI "IMAGENAME eq qgis*" 2>NUL | find /I /N "qgis">NUL {nl}{nl}'
                         '   if "%ERRORLEVEL%"=="0" (  {nl}'
                         '      ECHO QGIS is Still taskkill /FI "IMAGENAME eq qgis* Running. Proceeding to Kill QGIS without saving.  {nl}'
                         '      taskkill /FI "IMAGENAME eq qgis*" /F {nl}'
                         '   ) {nl}){nl}{nl}'
                         'ECHO. & ECHO {inst}stalling dependencies for QGIS PAT Plugin .... Please Wait  {nl}'

                         'ECHO Dependencies Log: {batlog}  {nl}'
                         'ECHO. & ECHO {divi} {nl}{nl}'
                         # Create an empty file to log to....
                         'type NUL > "{batlog}"   {nl}'
                         'CALL :PROCESS > "{batlog}"   {nl}'
                         'GOTO :END {nl}{nl}'

                         ':PROCESS  {nl}'  # this will add it to the dependencies log
                         '   ECHO {inst}stalling dependencies for QGIS PAT Plugin  {nl}'
                         '   {env} {nl}'
                         # any line containing a path needs to be a raw string
                         '   SET OSGEO4W_ROOT={osgeo}{nl}'
                         r'   call "%OSGEO4W_ROOT%\bin\o4w_env.bat"{nl}'
                         r'   set QGIS_PREFIX_PATH={qgis_pre}{nl}'
                         r'   path %PATH%;"%QGIS_PREFIX_PATH%\bin"{nl}'
                         r'   set PYTHONPATH=%PYTHONPATH%;"%QGIS_PREFIX_PATH%\python"{nl}'
                         r'   set PYTHONPATH=%PYTHONPATH%;"%OSGEO4W_ROOT%\apps\Python27\Lib\site-packages"{nl}{nl}'
                         ).format(nl='\n', divi='-'*70, inst=inst,
                                  logfold=os.path.dirname(bat_logfile),
                                  batlog=bat_logfile,
                                  osgeo=osgeo_path,
                                  env='' if os.environ.get('GDAL_VERSION', None) else
                                  'SET GDAL_VERSION={}'.format(gdal_ver),
                                  qgis_pre=qgis_prefix_path)
                    )

                    if inst.lower() == 'unin':  # add uninstall lines
                        w_bat_file.write(
                            ('   ECHO Y|python -m pip uninstall pyprecag {pip_arg}  {nl}'
                             '   ECHO Y|python -m pip uninstall rasterio {pip_arg}  {nl}'
                             '   ECHO Y|python -m pip uninstall fiona {pip_arg}     {nl}'
                             '   ECHO Y|python -m pip uninstall geopandas {pip_arg} {nl}{nl}'
                             ':END {nl}'
                             '   type "{batlog}" {nl}'
                             '   goto:eof'
                             ).format(nl='\n', divi='-'*70,
                                      pip_arg=pip_args_uninstall,
                                      batlog=bat_logfile))
                    else:
                        if not os.path.exists(dst_custom_widget) or len(failDependencyCheck) == 0:
                            if len(failDependencyCheck) > 0:
                                LOGGER.warning('Missing Dependency: {} '.format(dst_custom_widget))

                            w_bat_file.write(
                                ('   ECHO Missing Dependency: {dst} {nl}'
                                 '   ECHO Copying qgis_customwidgets.py {nl}'
                                 '   ECHO F|xcopy "{src}" "{dst}" /y   {nl}{nl}'
                                 '   ECHO Install Geopandas=0.4.0 {nl}'
                                 '   python -m pip install geopandas==0.4.0 {nl}{nl}'
                                 ).format(nl='\n',divi='-'*70, src=src_custom_widget,
                                          dst=dst_custom_widget))

                        for ea_pack in ['fiona', 'rasterio', 'pyprecag']:
                            if ea_pack in failDependencyCheck or len(failDependencyCheck) == 0:
                                wheel = packCheck[ea_pack]['Wheel']
                                if ea_pack == 'pyprecag':
                                    # Install via a tar wheel file prior to publishing via pip
                                    upgrade_file = glob.glob1(tempPackPath, ea_pack + "*")
                                    if len(upgrade_file) == 1:
                                        whl_file = upgrade_file[0]

                                    elif packCheck[ea_pack]['Action'] == 'Upgrade':
                                        whl_file = '-U pyprecag'
                                    else:
                                        whl_file = 'pyprecag'
                                else:
                                    if python_version == 32:
                                        whl_file = os.path.join(ea_pack, wheel + '-win32.whl')
                                    else:
                                        whl_file = os.path.join(ea_pack, wheel + '-win_amd64.whl')

                                w_bat_file.write(
                                    ('   ECHO. & ECHO {divi} {nl}{nl}'
                                     '   ECHO {act} {bit}bit {pack} and dependencies {nl}'
                                     '   python -m pip install {whl} {piparg}       {nl}'
                                     ).format(nl='\n',divi='-'*70, act=packCheck[ea_pack]['Action'],
                                              bit=python_version,
                                              pack=ea_pack,
                                              whl=whl_file,
                                              piparg=pip_args_install))

                                if ea_pack == 'pyprecag' and len(upgrade_file) == 1:
                                    # after installing, move the file otherwise you will always be prompted to upgrade
                                    # create a flag file and cleanup using python
                                    w_bat_file.write('   echo.>{}.log\n'.format(os.path.basename(upgrade_file[0])))
                                    # w_bat_file.write(r'    move {} {}'.format(os.path.join(plugin_path, 'python_packages',upgrade_file[0]),
                                    #            bug_fix_fold) + '\n')

                        w_bat_file.write(
                            ('{nl}   ECHO. & ECHO {divi}{nl}'
                             r'{nl}   EXIT /B      {nl}'  # will return to the position where you used CALL
                             '{nl}:END     {nl}'
                             # '   cls\n'            # clear the cmd window of all text
                             # then print the logfile to screen
                             '   type "{batlog}"     {nl}'
                             '{nl}   ECHO. & ECHO {divi}{nl}'
                             '   ECHO.    {nl}'
                             # '   ECHO All files and folders used in this install will self destruct.{nl}'
                             # '   ECHO.    {nl}'
                             '   ECHO ** Please restart QGIS to complete installation.{nl}'
                             '   ECHO You may have to reinstall or activate the PAT Plugin through the plugin manager.{nl}'
                             '   ECHO.    {nl}'
                             '   pause    {nl}'
                             '   ECHO.{nl}').format(nl='\n', divi='-'*70, batlog=bat_logfile))

                        # if len(failDependencyCheck) > 0:
                        #     w_bat_file.write(('   ECHO Deleting desktop shortcut\n'
                        #                       '   DEL "{short}"\n'
                        #                       '   ECHO Deleting {tmppack}\n'
                        #                       '   (goto) 2>nul & rmdir /S /Q "{tmppack}"\n'
                        #                       ).format(short=shortcutPath,
                        #                                tmppack=tempPackPath))

                        w_bat_file.write('   goto:eof')

        if len(failDependencyCheck) > 0:
            # copy python_packages folder to temp
            if os.path.exists(tempPackPath):
                # dir_util.remove_tree(tempPackPath)
                shutil.rmtree(tempPackPath, ignore_errors=True)

            # dir_util.copy_tree(os.path.join(plugin_path, 'python_packages'), tempPackPath)
            shutil.copytree(os.path.join(plugin_path, 'python_packages'),
                            tempPackPath, ignore=shutil.ignore_patterns('*.log', 'Unin*.bat'))
            LOGGER.info('Copied python_packages to  {}'.format(
                os.path.join(plugin_path, 'python_packages')))

            install_file = glob.glob(os.path.join(tempPackPath, "Inst*.bat"))[0]
            # install_file = os.path.join(tempPackPath, title + '.bat')

            # Create a shortcut on desktop with admin privileges.
            if platform.system() == 'Windows':
                try:
                    aReg = ConnectRegistry(None, HKEY_CURRENT_USER)
                    aKey = OpenKey(aReg, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
                    aVal = os.path.normpath(QueryValueEx(aKey, "Desktop")[0])
                    LOGGER.info('Desktop path from registry is {}'.format(aVal))
                except:
                    pass

                LOGGER.critical("Failed Dependency Check. Please run the shortcut {} "
                                "or the following bat file as administrator {}".format(shortcutPath,
                                                                                       install_file))

                create_link(shortcutPath, install_file, "Install setup for QGIS PAT Plugin",
                            user_path, True)

            message = 'Installation or updates are required for {}.\n\nPlease quit QGIS and run {} ' \
                      'located on your desktop.'.format(', '.join(failDependencyCheck), title)
            iface.messageBar().pushMessage("ERROR Failed Dependency Check", message,
                                           level=QgsMessageBar.CRITICAL,
                                           duration=0)
            QMessageBox.critical(None, 'Failed Dependency Check', message)

            sys.exit(message)
        else:
            settings_version = read_setting(PLUGIN_NAME + "/PAT_VERSION")
            if settings_version is None:
                LOGGER.info('Successfully installed and setup PAT {})'.format(' ('.join(meta_version)))
            else:
                if ' ' in settings_version:
                    settings_version = settings_version.split(' ')
                else:
                    settings_version = [settings_version]

                if parse_version(meta_version[0]) > parse_version(settings_version[0]):
                    LOGGER.info('Successfully upgraded and setup PAT from {} to {})'
                            .format(' '.join(settings_version),' ('.join(meta_version)))

                elif parse_version(meta_version[0]) < parse_version(settings_version[0]):
                    LOGGER.info(
                        'Successfully downgraded and setup PAT from {} to {})'
                            .format(' '.join(settings_version),' ('.join(meta_version)))

            write_setting(PLUGIN_NAME + '/PAT_VERSION', ' ('.join(meta_version) + ')')

    except Exception, err:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        mess = str(traceback.format_exc())

        setup = get_plugin_state()
        LOGGER.info(setup + '\n\n')
        LOGGER.error('\n' + mess)

        message = ('An error occurred during setup, please report this error to PAT@csiro.au '
                   'and attach the following files \n\t {} \n\t{}'.format(get_logger_file(),
                                                                          install_file))

        QMessageBox.critical(None, 'Failed setup', message)

        sys.exit(message + '\n\n' + mess)

    return failDependencyCheck


def get_logger_file():
    for hand in LOGGER.handlers:
        try:
            if hand.baseFilename != '':
                return hand.baseFilename
        except:
            pass


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
    # Source: https://stackoverflow.com/a/37063259
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
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
    LOGGER.info('Created shortcut {}'.format(link_path))


def get_plugin_version():
    cfg = configparser.SafeConfigParser()
    cfg.read(os.path.join(PLUGIN_DIR, 'metadata.txt'))
    version = cfg.get('general', 'version')
    ver_date = cfg.get('general', 'update_date')
    return (version, ver_date)


def get_plugin_state():
    version = get_plugin_version()

    """TODO: Make the paths clickable links to open folder
        def create_path_link(path):
            path = os.path.normpath(path)
            #"<a href={}>Open Project Folder</a>".format("`C:/Progra~1/needed"`)
            return '<a href= file:///"`{0}"`>{0}</a>'.format(path)
        """
    plug_state = ['QGIS Environment:']

    plug_state.append('    {:20}\t{}'.format('QGIS :', qgis.utils.QGis.QGIS_VERSION))
    if platform.system() == 'Windows':
        plug_state.append('    {:20}\t{}'.format('Install Path : ',
                                                 os.path.abspath(win32api.GetLongPathName(
                                                     os.environ['QGIS_PREFIX_PATH']))))
    else:
        plug_state.append(
            '    {:20}\t{}'.format('Install Path : ', qgis.core.QgsApplication.prefixPath()))

    plug_state.append('    {:20}\t{}'.format('Plugin Dir:', os.path.normpath(PLUGIN_DIR)))
    plug_state.append(
        '    {:20}\t{}'.format('Temp Folder:', os.path.normpath(tempfile.gettempdir())))

    plug_state.append('    {:20}\t{}'.format('Python :', sys.version))
    plug_state.append('    {:20}\t{}'.format('GDAL :', os.environ.get('GDAL_VERSION', None)))

    plug_state.append('\nPAT Version:')
    plug_state.append('    {:20}\t{})'.format('PAT:',' ('.join(version)))
    plug_state.append('    {:20}\t{}'.format('pyPrecAg:', get_distribution('pyprecag').version))
    plug_state.append('    {:20}\t{}'.format('Geopandas:', get_distribution('geopandas').version))
    plug_state.append('    {:20}\t{}'.format('Rasterio:', get_distribution('rasterio').version))
    plug_state.append('    {:20}\t{}'.format('Fiona:', get_distribution('fiona').version))
    plug_state.append('    {:20}\t{}'.format('Pandas:', get_distribution('pandas').version))

    plug_state.append('\nR Configuration')
    plug_state.append(
        '    {:20}\t{}'.format('R Active :', read_setting('Processing/Configuration/ACTIVATE_R')))
    plug_state.append('    {:20}\t{}'.format('R Install Folder :',
                                             read_setting('Processing/Configuration/R_FOLDER')))
    return '\n'.join(plug_state)
