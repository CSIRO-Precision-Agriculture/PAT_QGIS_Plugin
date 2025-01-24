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
from __future__ import print_function

import re

import glob
import logging
import os
import shutil

import pandas as pd
from pathlib import Path
import platform
import subprocess
import pythoncom
import sys
import tempfile
import traceback
from builtins import str
from datetime import date, datetime, timedelta

import requests
from packaging.version import parse as parse_version

import osgeo.gdal
import qgis
from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import QDateTime, QFileInfo
from qgis.PyQt.QtWidgets import QMessageBox, QApplication
from qgis.core import Qgis, QgsApplication, QgsStyle

if platform.system() == 'Windows':
    import win32api
    from win32com.shell import shell, shellcon
    from winreg import ConnectRegistry, OpenKey, QueryValueEx, HKEY_LOCAL_MACHINE

import struct

from pat import LOGGER_NAME, PLUGIN_NAME, PLUGIN_DIR
from util.settings import read_setting, write_setting, remove_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


def check_pat_symbols():
    pat_xml = os.path.join(PLUGIN_DIR, 'PAT_Symbols.xml')
    if not os.path.exists(pat_xml):
        return
    
    loaded_date = read_setting(PLUGIN_NAME + "/PAT_SYMBOLOGY", object_type=QDateTime)
    xml_date = QFileInfo(pat_xml).lastModified()
    
    new = False
    if loaded_date.isNull() or  xml_date > loaded_date:
        new = True
    
    styles = QgsStyle().defaultStyle()

    if 'PAT' not in styles.tags() or new:
        if styles.isXmlStyleFile(pat_xml):
            if styles.importXml(pat_xml):
                LOGGER.info('Loaded PAT Symbology')
                write_setting(PLUGIN_NAME + '/SETUP/NEXT_CHECK', xml_date)
            else:
                LOGGER.warning('Loading PAT Symbology failed')
        else:
            LOGGER.debug('Could not open file {}'.format(pat_xml))

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
            mess = ('R is not installed or not configured for QGIS.\n '
                    'See "Configuring QGIS to use R" in help documentation')
            return

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

    files = glob.glob(os.path.join(PLUGIN_DIR, "R-Scripts", "Whole*.rsx"))

    for src_file in files:
        dest_file = os.path.join(r_scripts_fold, os.path.basename(src_file))

        # copy file if destination is older by more than a second, or does not exist
        if not os.path.exists(dest_file) or os.stat(src_file).st_mtime - os.stat(dest_file).st_mtime > 120:
            shutil.copy2(src_file, dest_file)
            LOGGER.info('Installing or Updating Whole-of-block analysis tool.')
    return True


def check_gdal_dependency():
    # get the list of wheels matching the gdal version
    if not os.environ.get('GDAL_VERSION', None):
        gdal_ver = osgeo.gdal.__version__
        LOGGER.warning(
            'Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
        os.environ['GDAL_VERSION'] = gdal_ver

    gdal_ver = os.environ.get('GDAL_VERSION', None)
    # wheels = None
    # for key, val in sorted(GDAL_WHEELS.items()):
    #     if parse_version(gdal_ver) <= parse_version(key):
    #         wheels = val
    #
    # if wheels is None:
    #     return gdal_ver, False

    return gdal_ver  # , wheels


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
                if vesper_exe == '' or vesper_exe is None:
                    message = 'Vesper*.exe not found. Please install and configure to allow for kriging to occur'
                elif not os.path.exists(vesper_exe):
                    message = (f'Vesper*.exe at "{vesper_exe}" does not exist. Please install and '
                               'configure to allow for kriging to occur')

                vesper_exe = None
            write_setting(PLUGIN_NAME + '/VESPER_EXE', '' if vesper_exe is None else vesper_exe)
    else:
        message = 'VESPER is only supported on Windows.'

    if message != '':
        if iface:
            iface.messageBar().pushMessage("WARNING", message, level=Qgis.Warning,
                                           duration=15)
        else:
            LOGGER.warning(message)

    return vesper_exe


def writeLineToFileS(line, openFileList=[]):
    """Write a single line to multiple files"""

    if len(openFileList) > 0:
        for eafile in openFileList:
            eafile.write(line)


def check_python_dependencies(package_name, online=False):
    """Check to see if a python package is installed and what version it is with an option to check online for updates.
    Args:
        package_name (str): the name of the package
        online (bool): Check online for updates with priority for osgeo4w over pip.
    """
     
    # NOTE: importlib.metadata.version has issues if there are dist-info for a package
    # and will return the first it finds and most likely the older version.
    
    inst_ver = '0.0.0'

    if package_name == 'gdal':
        inst_ver = sys.modules['osgeo'].__version__
    elif 'runtime' in package_name:
        dll_file = Path(QgsApplication.applicationDirPath()).joinpath(package_name.split('-')[0] +'.dll')
        if dll_file.exists():
            if platform.system() == 'Windows':
                from win32api import GetFileVersionInfo, LOWORD, HIWORD
                info = GetFileVersionInfo (str(dll_file), "\\")
                ms = info['FileVersionMS']
                ls = info['FileVersionLS']
                inst_ver = f'{HIWORD(ms)}.{LOWORD(ms)}.{HIWORD(ls)}'  #.{LOWORD (ls)}'
    else:
        try:
            exec(f'import {package_name}')
            module = sys.modules[package_name]
            if hasattr(module, '__version__'): 
                inst_ver = sys.modules[package_name].__version__    
        except ModuleNotFoundError as err:
            pass
            
    package = None    # this will be the osgeo4w string required for install.
    available_ver = '0.0.0'
    source = 'n/a'
    if online:
        if 'osgeo4w_packs' not in globals():
            urls = ['http://download.osgeo.org/osgeo4w/v2/x86_64/release/python3/',
                    'http://download.osgeo.org/osgeo4w/v2/x86_64/release/gdal/']
            global osgeo4w_packs
            osgeo4w_packs = pd.DataFrame()
            for url in urls:
                ut = pd.read_html(url, header=0, skiprows=[1])[0]
                ut.rename(columns=lambda c: re.sub('[^a-zA-Z0-9 ]', '', c).strip(), inplace=True)
                ut = ut[ut['File Name'].str.endswith('/')]
                ut['url'] = url + ut['File Name']
                ut['File Name'] = ut['File Name'].str.rstrip("/")
                ut['package_name'] = ut['File Name'].str.replace('python3-','')
                #ut[['src','package']] = ut['File Name'].str.split('-', n=1,expand=True)
                
                ut.set_index('package_name', inplace=True)
                osgeo4w_packs = pd.concat([osgeo4w_packs, ut], axis=0)

        if package_name in osgeo4w_packs.index:
            url = osgeo4w_packs.loc[package_name, 'url']
            package= osgeo4w_packs.loc[package_name, 'File Name']
            # print(f'Searching osgeo4w for {package_name},  {url}', end='\t')
            table = pd.read_html(url, header=0, skiprows=[1])[0]
            table.rename(columns=lambda c: re.sub('[^a-zA-Z0-9 ]', '', c).strip(), inplace=True)
            table['Date'] = pd.to_datetime(table['Date'], yearfirst=True, format='mixed')
            table = table.loc[table['File Name'].str.endswith('bz2')]
            newest = table.iloc[table['Date'].argmax()]['File Name']
            available_ver = newest.split('-')[2]
            # print(f'found {available_ver}')
                                   
            source = 'osgeo4w'
        else:

            try:
                url = 'https://pypi.python.org/pypi/{}/json'.format(package_name)
                # print(f'Searching pip for {package},  {url}', end='\t')
                available_ver = requests.get(url)
                available_ver.raise_for_status()
                available_ver = available_ver.json()['info']['version']
                source = 'pip'
                # print(f'found {available_ver}')    
            except (requests.ConnectionError, requests.exceptions.HTTPError) as err:
                available_ver = None
                # print(f'Skipping {package}. {err.args[0]}')

    loc_whl = None
    
    local_files = [p for p in Path(PLUGIN_DIR).joinpath('install_files').rglob(f'{package_name}*') if
                   p.suffix in ['.gz', '.whl']]

    if len(local_files) > 0:
        for i, ea in enumerate(local_files):
            loc_pack, loc_ver = ea.stem.split('-')
            loc_ver = Path(loc_ver).stem

            if parse_version(loc_ver) < parse_version(inst_ver):
                continue  # installed version is new than wheel

            package_name = loc_pack
            package = loc_pack
            source = 'pip_whl'
            loc_whl = ea.name

            if (parse_version(loc_ver) > parse_version(inst_ver)) or (
                    available_ver is not None and parse_version(loc_ver) > parse_version(available_ver)):
                available_ver = loc_ver

        # print(f'Found {len(local_files)} local wheel files, newest version is {available_ver} ')

    r = pd.Series({'package': package,
                   'current': parse_version(inst_ver) if inst_ver != '0.0.0' else None,
                   'available': parse_version(available_ver) if available_ver != '0.0.0' else None,
                   'path': loc_whl,
                   'source': source})

    return r


def plugin_status(level='basic', check_for_updates=False, forced_update=False):
    """ Check for extra python modules which the plugin requires.

    If they are not installed, a windows batch file will be created on the users desktop.
    Run this as administrator to install relevant packages

    Args:
         level (): Install, basic or advanced.
         check_for_updates (): Check online for updates.

    Returns (bool): Passed Check or Not.
    """
    
    
    qgis_prefix = str(Path(QgsApplication.prefixPath()).resolve())
    
    func_time = datetime.now()
    func_step = datetime.now()
        
    #copy processing alg to profile for when PAT fails install to assist with debugging.
    dest_file = Path(QgsApplication.qgisSettingsDirPath(), 'processing', 'scripts', "PAT_CheckVersions_alg.py")
        
    src_file = Path(PLUGIN_DIR,'util', "PAT_CheckVersions_alg.py")

    # copy file if destination is older by more than a second, or does not exist
    if not dest_file.exists() or os.stat(src_file).st_mtime - os.stat(dest_file).st_mtime > 120:
        try:
            LOGGER.info(f"Copying {Path(dest_file).stem} to User Profile")
            shutil.copy(src_file, dest_file)
            
        except OSError as e:
            LOGGER.critical("Couldn't copy to '{}'!".format(dest_file))
        
        if QgsApplication.processingRegistry().providerById('script'):
            # Finally, refresh the algorithms for the Processing script provider
            QgsApplication.processingRegistry().providerById("script").refreshAlgorithms()
    
    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-copy_alg',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))
    func_step = datetime.now()
    df_dep = pd.DataFrame([{'type': 'QGIS Environment',
                            'current': f'LTR-{Qgis.QGIS_VERSION}' if 'LTR' in qgis_prefix else Qgis.QGIS_VERSION,
                            'path': qgis_prefix}], index=['QGIS'])

    df_dep.index.name = 'name'

    df_dep.loc['Temp', ['type', 'path']] = ['QGIS Environment', tempfile.gettempdir()]
    df_dep.loc['Python', ['type', 'current']] = ['QGIS Environment', sys.version]
    
    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-qgis_env',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))
    func_step = datetime.now()
    
    
    import pyplugin_installer
    p = pyplugin_installer.installer_data.plugins.all()

    if 'pat' in p.keys():
        p = p['pat']
        df_dep.loc['PAT', ['type', 'current', 'path']] = ['PAT Environment', parse_version(p['version_installed']),
                                                            PLUGIN_DIR]

        # if check_for_updates:
        # pyplugin_installer.instance().fetchAvailablePlugins(False)
        # p = pyplugin_installer.installer_data.plugins.all()['pat']
        # df_dep.loc['PAT', 'available'] = parse_version(p['version_available'])  # needs further testing
    
    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-pat_ver',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))
    func_step = datetime.now()
    
    vesper_exe = read_setting(PLUGIN_NAME + '/VESPER_EXE', str)
    if vesper_exe is None or not Path(vesper_exe).exists():
        vesper_exe = check_vesper_dependency(None)
        write_setting(PLUGIN_NAME + '/VESPER_EXE', vesper_exe)

    df_dep.loc['VESPER', ['type', 'path']] = ['PAT Environment', vesper_exe]
    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-vesp_ver',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))
    func_step = datetime.now()
    
    if level.lower() == 'basic':
        df_py = pd.DataFrame(['geopandas', 'rasterio', 'pyprecag','fiona','gdal308-runtime'], columns=['name'])
    else:
        df_py = pd.DataFrame(['geopandas', 'rasterio', 'pandas', 'shapely', 'fiona', 'pyproj', 'unidecode', 'pint',
                              'numpy', 'scipy', 'chardet', 'pyprecag', 'gdal','gdal308-runtime'], columns=['name'])

    df_py[['package', 'current', 'available', 'file', 'source']] = df_py['name'].apply(check_python_dependencies,
                                                                                    args=(check_for_updates,))
    
    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-pydep_ver',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))
    func_step = datetime.now()
                         
    #if Qgis.QGIS_VERSION_INT < 31800:
    # packCheck['gdal300dll']={'Action': '', 'Version': ''}
    # if not os.path.exists(os.path.join(osgeo_path,'bin','gdal308.dll')):
    #     packCheck['gdal300dll']={'Action': 'Install', 'Version': ''}
    #     osgeo_packs += ['gdal300dll']
    #
    
    df_py['type'] = 'Python'
    df_py['action'] = None
    df_py.loc[df_py['current'].isnull(), 'action'] = 'Install'

    df_py.loc[df_py['current'].notnull() & (df_py['available'] > df_py['current']), 'action'] = 'Upgrade'
    df_py.loc[df_py['current'].notnull() & (df_py['available'] < df_py['current']), 'action'] = 'Downgrade'
    df_py.loc[df_py['current'].notnull() & (df_py['available'] == df_py['current']), 'action'] = 'Keep'

    df_py = df_py.set_index('name')

    df_dep = pd.concat([df_dep, df_py])

    df_updates = df_py.loc[df_py['action'].isin(['Install', 'Upgrade'])]

    df_dep[df_dep.notnull()] = df_dep.astype(str)  # convert parsed version to string
    df_dep.loc[df_dep['file'].notnull(), 'current'] = df_dep['path']  # use tar/whl file

    # are core dependencies installed
    #dep_met = read_setting(PLUGIN_NAME + '/STATUS/DEPENDENCIES_MET', object_type=bool, default=False)
    
    if 'pyprecag' in df_updates.index or forced_update:
        _ = install(df_updates,forced_update)

    if read_setting(PLUGIN_NAME + '/STATUS/LOAD_TIMES', bool):
        LOGGER.info("..{:.<33} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name + '-install',
                                                func_step.strftime("%H:%M:%S.%f"),
                                                datetime.now().strftime("%H:%M:%S.%f"),
                                                dur=datetime.now() - func_step))

    if read_setting(PLUGIN_NAME + "/DEBUG", bool):
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name,
                                                    func_time.strftime("%H:%M:%S.%f"),
                                                    datetime.now().strftime("%H:%M:%S.%f"),
                                                    dur=datetime.now() - func_time))

    return df_dep


def install(df_updates,forced_update):
    
    if len(df_updates) == 0:
        return True
    
    func_time = datetime.now()
    
    dependencies_met = read_setting(PLUGIN_NAME + '/STATUS/DEPENDENCIES_MET', object_type=bool, default=False)

    packs_mess = ''
    if any(df_updates['source'] == 'osgeo4w'):
        packs_mess += '    osgeo4w:\t{}\n'.format(
            "\n\t".join(df_updates.loc[df_updates['source'] == 'osgeo4w'].index.tolist()))

    if any(df_updates['source'].str.startswith('pip')):
        packs_mess += '    pip:\t{}\n'.format(
            "\n\t".join(df_updates.loc[df_updates['source'].str.startswith('pip')].index.tolist()))

    inst_message = (f'PAT installation/update required for:\n{packs_mess}\n'
                    'WARNING Installation may require administrator access.\n\n')

    QApplication.restoreOverrideCursor()
    msg_box = QMessageBox()
    msg_box.setWindowTitle("PAT Updates available")
    msg_box.setText(inst_message + 'Install now?')
    msg_box.addButton(QMessageBox.Yes)
    msg_box.addButton(QMessageBox.No)

    if dependencies_met:
        msg_box.addButton('Delay for 7 days', QMessageBox.ApplyRole)
    if forced_update:
        msg_box.addButton('Ignore', QMessageBox.RejectRole)
        
    inst_result = msg_box.exec_()

    success = False
    if inst_result == 1:  # Ignore role
        return False
    
    if inst_result == 0:  # apply role or 7 day delay
        write_setting(PLUGIN_NAME + '/STATUS/NEXT_CHECK', QDateTime.currentDateTime().addDays(7))
        # qgis.utils.unloadPlugin('pat')
        return True

    elif inst_result == QMessageBox.Yes:
        from qgis.utils import iface
        if platform.system() == 'Windows':
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            install_bat = create_bat_files(df_updates, run_within_qgis=True)

            # launch BAT file as administrator.
            # https://stackoverflow.com/a/72792517
            from ctypes import windll
            result = windll.shell32.ShellExecuteW(None,  # handle to parent window
                                                  'runas',  # runas: prompt for UAC, None as per normal
                                                  'cmd.exe',  # file on which verb acts
                                                  ' '.join(['/c', install_bat]),  # parameters
                                                  None,  # working directory (default is cwd)
                                                  1,  # show window normally
                                                  )
            success = result > 32

            if success:
                iface.messageBar().pushMessage("PAT", "Installing PAT Dependencies.. Please Wait....",
                                               level=Qgis.Info, duration=15)

            done_file = Path(install_bat).parent.joinpath('pat-install.finished')

            while True:
                if done_file.exists() or not success:
                    break

            # sometimes there is a permissions lock on the file so wait and try again 
            timeout = 0
            while done_file.exists():
                if timeout > 10:
                    break
                try:
                    done_file.unlink()
                    break
                except PermissionError:
                    import time
                    time.sleep(1)
                    timeout += 1
            
            QApplication.restoreOverrideCursor()
            if success:
                _ = plugin_status(level='basic', check_for_updates=False)

                write_setting(PLUGIN_NAME + '/STATUS/NEXT_CHECK', QDateTime.currentDateTime().addDays(30))
                iface.messageBar().clearWidgets()
                iface.messageBar().pushMessage("PAT", "Installing PAT Dependencies completed Successfully.",
                                               level=Qgis.Success, duration=5)
                
                result = success

    if inst_result == QMessageBox.No or not success:
        # Create a shortcut on desktop with admin privileges.
        if platform.system() == 'Windows':
            install_bat = create_bat_files(df_updates, run_within_qgis=False)

            desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, 0, 0)
            shortcutPath = os.path.join(desktop, Path(install_bat).stem.replace('_', ' ') + '.lnk')

            # add shortcut to desktop....
            create_link(shortcutPath, install_bat, "Install setup for QGIS PAT Plugin",
                        os.path.expanduser('~'), True)

            LOGGER.critical(f"To install PAT please run the desktop shortcut {Path(install_bat).stem} "
                            f"or bat file as administrator {install_bat}")

            message = f'To install PAT please quit QGIS and run {Path(install_bat).stem} ' \
                      'located on your desktop.'
            from qgis.utils import iface
            iface.messageBar().pushMessage("PAT Updates available", message,
                                           level=Qgis.Critical, duration=0)

            QMessageBox.critical(None, 'PAT Updates available', message)

            write_setting(PLUGIN_NAME + '/STATUS/INSTALL_PENDING', shortcutPath)



        result = False
    
    if read_setting(PLUGIN_NAME + "/DEBUG", bool): 
        LOGGER.info("{:.<35} {:.<15} -> {:.<15} = {dur}".format(sys._getframe().f_code.co_name,
                                                    func_time.strftime("%H:%M:%S.%f"),
                                                    datetime.now().strftime("%H:%M:%S.%f"),
                                                    dur=datetime.now() - func_time))
                                                                      
    return result 

def create_file_from_template(template_file, arg_dict, write_file):
    # write install file
    from string import Template
    # open the file
    filein = open(template_file)

    # read it
    src = Template(filein.read())

    filein.close()

    # do the substitution and write to file
    w_file = open(write_file, "w")
    w_file.write(src.substitute(arg_dict))
    w_file.close()


def create_bat_files(df, run_within_qgis=True):
    try:
        # the name of the install file.
        title = 'Install_PAT3'
        qgis_prefix_path = os.path.abspath(QgsApplication.prefixPath())

        if 'LTR' in os.path.basename(qgis_prefix_path).upper():
            qgis_version = 'LTR {}'.format(Qgis.QGIS_VERSION)
            title = f'{title}_qgis-LTR-{Qgis.QGIS_VERSION_INT // 100}'
        else:
            qgis_version = Qgis.QGIS_VERSION
            title = f'{title}_qgis-{Qgis.QGIS_VERSION_INT // 100}'

        OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/v2'

        if 'LTR' in qgis_version:
            if Qgis.QGIS_VERSION_INT < 31609:
                OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/'
        else:
            if Qgis.QGIS_VERSION_INT < 32000:
                OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/'

        df = df.reset_index()
        df['inst'] = df['name']
        df.loc[df['source'] == 'pip_whl', 'inst'] = df['file']
        df.loc[df['source'] == 'osgeo4w', 'inst'] = '-P ' + df['package']

        pip_packages = df.loc[df['source'] != 'osgeo4w', 'inst'].unique().tolist()
        osgeo4w_packages = df.loc[df['source'] == 'osgeo4w', 'inst'].unique().tolist()
        osgeo4w_names = df.loc[df['source'] == 'osgeo4w', 'name'].unique().tolist()

        # create a dictionary to use with the template file.
        d = {'dependency_log': os.path.join(PLUGIN_DIR, 'install_files',
                                            'dependency_{}.log'.format(date.today().strftime("%Y-%m-%d"))),
             'QGIS_PATH': str(Path(os.environ['OSGEO4W_ROOT']).resolve()),
             'QGIS_VERSION': Qgis.QGIS_VERSION,
             'osgeo_message': 'Installing {}'.format(', '.join(osgeo4w_names)),
             'site': OSGeo4W_site,
             'osgeo_packs': '' if len(osgeo4w_packages) == 0 else ' '.join(osgeo4w_packages),
             'pip_func': 'install',
             'pip_packs': '' if len(pip_packages) == 0 else ' '.join(pip_packages),
             'py_version': struct.calcsize("P") * 8,
             'run_within': run_within_qgis
             }  # this will return 64 or 32

        # 'osgeo_uninst': ' -x python3-'.join(['fiona', 'geopandas', 'rasterio'])
        temp_file = os.path.join(PLUGIN_DIR, 'util', 'Install_PAT3_Extras.template')
        install_file = os.path.join(PLUGIN_DIR, 'install_files', title + '.bat')
        uninstall_file = os.path.join(PLUGIN_DIR, 'install_files', title + '.bat')

        python_version = struct.calcsize("P") * 8  # this will return 64 or 32

        if not os.path.exists(os.path.dirname(install_file)):
            os.mkdir(os.path.dirname(install_file))

        if len(osgeo4w_packages + pip_packages) > 0:
            create_file_from_template(temp_file, d, install_file)
            return install_file

    except Exception as err:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        mess = str(traceback.format_exc())

        # setup = get_plugin_state()
        # LOGGER.info(setup + '\n\n')
        LOGGER.error('\n' + mess)
        #
        # message = ('An error occurred during setup, please report this error to PAT@csiro.au ')
        #            # 'and attach the following files \n\t {} \n\t{}'.format(get_logger_file(),
        #            #                                                        install_file))
        #
        # QMessageBox.critical(None, 'Failed setup', message)
        sys.exit(mess)


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
