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

from builtins import next
from builtins import str
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
from packaging.version import Version, parse as parse_version

from qgis.PyQt.QtWidgets import QMessageBox
import qgis
from qgis.gui import QgsMessageBar
from qgis.core import Qgis, QgsApplication, QgsStyle, QgsSymbolLayerUtils

from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtCore import QFile, QIODevice

import osgeo.gdal
import pythoncom

if platform.system() == 'Windows':
    import win32api
    from win32com.shell import shell, shellcon
    from winreg import ConnectRegistry, OpenKey, QueryValueEx, HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER

import struct

from pat import LOGGER_NAME, PLUGIN_NAME, PLUGIN_DIR
from util.settings import read_setting, write_setting

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())  # logging.StreamHandler()


def check_pat_symbols():
    pat_xml = os.path.join(PLUGIN_DIR, 'PAT_Symbols.xml')
    if not os.path.exists(pat_xml):
        return

    loaded_date = read_setting(PLUGIN_NAME + "/PAT_SYMBOLOGY")
    if loaded_date is not None:
        loaded_date = datetime.strptime(loaded_date, '%Y-%m-%d %H:%M:%S')

    xml_date = datetime.fromtimestamp(os.path.getmtime(pat_xml)).replace(microsecond=0)

    styles = QgsStyle().defaultStyle()

    if 'PAT' not in styles.tags() or (loaded_date is None or xml_date > loaded_date):
        if styles.isXmlStyleFile(pat_xml):
            if styles.importXml(pat_xml):
                LOGGER.info('Loaded PAT Symbology')
                write_setting(PLUGIN_NAME + '/PAT_SYMBOLOGY', xml_date.strftime('%Y-%m-%d %H:%M:%S'))
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

    files = glob.glob(os.path.join(PLUGIN_DIR, "R-Scripts", "Whole*.rsx"))

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
            iface.messageBar().pushMessage("WARNING", message, level=Qgis.Warning,
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

    try:
        pack_dict = {'Action': 'None', 'Version': get_distribution(package).version}
    except DistributionNotFound:
        pack_dict = {'Action': 'Install', 'Version': ''}

    return pack_dict


def check_pip_for_update(package):
    """ Check a package against online pip via json get the most current release
    version number

    source: https://stackoverflow.com/a/40745656
    """

    # only check once a month for pyprecag updates.
    last_pip_check = read_setting(PLUGIN_NAME + "/LAST_PIP_CHECK")
    if last_pip_check is not None:
        last_pip_check = datetime.strptime(last_pip_check, '%Y-%m-%d')

    if last_pip_check is None or (datetime.now() - last_pip_check).days > 30:
        url = 'https://pypi.python.org/pypi/{}/json'.format(package)
        try:
            releases = requests.get(url).json()['releases']
            current_version = sorted(releases, key=parse_version, reverse=True)[0]

            write_setting(PLUGIN_NAME + '/LAST_PIP_CHECK', datetime.now().strftime('%Y-%m-%d'))

            return current_version
        except requests.ConnectionError:
            LOGGER.info('Skipping pyprecag version check. Cannot reach {}'.format(url))
    return


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
        # comes from metadata.txt
        from qgis.utils import pluginMetadata
        meta_version= {'version':pluginMetadata('pat', 'version'), 'date':pluginMetadata('pat', 'release_date')}
        settings_version = read_setting(PLUGIN_NAME + "/PAT_VERSION")

        if settings_version is not None:
            settings_version = settings_version.strip()
            settings_version= {'version':settings_version.split(' ')[0], 'date':settings_version.split(' ')[1]}
        # # get the list of wheels matching the gdal version
        # if not os.environ.get('GDAL_VERSION', None):
        #     gdal_ver = osgeo.gdal.__version__
        #     LOGGER.warning(
        #         'Environment Variable GDAL_VERSION does not exist. Setting to {}'.format(gdal_ver))
        #     os.environ['GDAL_VERSION'] = gdal_ver

        # the name of the install file.
        title = 'Install_PAT3_Extras'
        if platform.system() == 'Windows':
            user_path = os.path.join(os.path.expanduser('~'))
            desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, 0, 0)
            shortcutPath = os.path.join(desktop, title.replace('_', ' ') + '.lnk')
            
            osgeo_path = os.path.abspath(win32api.GetLongPathName(os.environ['OSGEO4W_ROOT']))

            if os.path.exists(shortcutPath):
                # Copy logs into PAT plugin folder
                pass
        else:
            osgeo_path = os.path.abspath(os.environ['OSGEO4W_ROOT'])

        qgis_prefix_path = os.path.abspath(QgsApplication.prefixPath())

        if 'LTR' in os.path.basename(qgis_prefix_path).upper():
            qgis_version = 'LTR {}'.format(Qgis.QGIS_VERSION)
        else:
            qgis_version = Qgis.QGIS_VERSION

        packCheck = {}
        pip_packs = []
        osgeo_packs = []
        OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/v2'

        if 'LTR' in qgis_version :
            if Qgis.QGIS_VERSION_INT < 31609:
                OSGeo4W_site ='http://download.osgeo.org/osgeo4w/'
        else:
            if Qgis.QGIS_VERSION_INT < 32000:
                OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/'

        # if Qgis.QGIS_VERSION_INT < 31800:
        #     packCheck['gdal300dll']={'Action': '', 'Version': ''}
        #     if not os.path.exists(os.path.join(osgeo_path,'bin','gdal300.dll')):
        #         packCheck['gdal300dll']={'Action': 'Install', 'Version': ''}
        #         osgeo_packs += ['gdal300dll']
        
        # Check for the listed modules.
        for argCheck in ['fiona', 'geopandas', 'rasterio']:
            packCheck[argCheck] = check_package(argCheck)
            if packCheck[argCheck]['Action'] == 'Install':
                osgeo_packs += [argCheck]

        packCheck['pyprecag'] = check_package('pyprecag')
        cur_pyprecag_ver = check_pip_for_update('pyprecag')
        if cur_pyprecag_ver is not None:
            if parse_version(packCheck['pyprecag']['Version']) < parse_version(cur_pyprecag_ver):
                packCheck['pyprecag']['Action'] = 'Upgrade'

        if packCheck['fiona']['Action'] == 'Install':
            message = ''

            if 'LTR' in qgis_version:
                if Qgis.QGIS_VERSION_INT < 31011:
                    message = 'PAT is no longer supported by QGIS LTR {}\nPlease upgrade to the current QGIS release.'.format(Qgis.QGIS_VERSION)
              
            elif Qgis.QGIS_VERSION_INT < 31600:
                message = 'PAT is no longer supported by QGIS {}\nPlease upgrade to the current QGIS release.'.format(Qgis.QGIS_VERSION)

            if message != '':
                iface.messageBar().pushMessage(message, level=Qgis.Critical, duration=30)
                LOGGER.info(message)
                QMessageBox.critical(None, 'QGIS Upgrade required', message)
                return(message)
        
        # Install via a tar wheel file prior to publishing via pip to test pyprecag bug fixes
        # otherwise just use a standard pip install.
        local_wheel = glob.glob1(os.path.join(plugin_path, 'install_files'), "pyprecag*")
        if len(local_wheel) == 1 and 'installed' not in local_wheel[0]:
            packCheck['pyprecag']['Action'] = 'Upgrade'
            pip_packs += [local_wheel[0]]
        elif packCheck['pyprecag']['Action'] in ['Install', 'Upgrade']:
            pip_packs += ['{}'.format('pyprecag')]

        failDependencyCheck = [key for key, val in packCheck.items() if val['Action'] in ['Install', 'Upgrade']]

        osgeo_packs = ['-P ' + p if 'gdal' in p else '-P python3-' + p for p in osgeo_packs]
        
        # create a dictionary to use with the template file.
        d = {'dependency_log': os.path.join(plugin_path, 'install_files',
                                            'dependency_{}.log'.format(date.today().strftime("%Y-%m-%d"))),
             'QGIS_PATH': osgeo_path,
             'QGIS_VERSION': qgis_version,
             'osgeo_message': 'Installing {}'.format(', '.join(osgeo_packs)),
             'site': OSGeo4W_site,
             'osgeo_packs': '' if len(osgeo_packs) == 0 else ' '.join(osgeo_packs),
             'pip_func': 'install',
             'pip_packs': '' if len(pip_packs) == 0 else ' '.join(pip_packs),
             'py_version': struct.calcsize("P") * 8}  # this will return 64 or 32

        # 'osgeo_uninst': ' -x python3-'.join(['fiona', 'geopandas', 'rasterio'])
        temp_file = os.path.join(plugin_path, 'util', 'Install_PAT3_Extras.template')
        if 'LTR' in qgis_version:
            install_file = os.path.join(plugin_path, 'install_files', '{}_4_qgis-LTR-{}.bat'.format(title, str(Qgis.QGIS_VERSION_INT)[:-2]))
            uninstall_file = os.path.join(plugin_path, 'install_files', 'Un{}_4_qgis-LTR-{}.bat'.format(title, str(Qgis.QGIS_VERSION_INT)[:-2]))
        else:
            install_file = os.path.join(plugin_path, 'install_files', '{}_4_qgis-{}.bat'.format(title, str(Qgis.QGIS_VERSION_INT)[:-2]))
            uninstall_file = os.path.join(plugin_path, 'install_files', 'Un{}_4_qgis-{}.bat'.format(title, str(Qgis.QGIS_VERSION_INT)[:-2]))

        python_version = struct.calcsize("P") * 8  # this will return 64 or 32

        if not os.path.exists(os.path.dirname(install_file)):
            os.mkdir(os.path.dirname(install_file))

        if len(failDependencyCheck) > 0:

            create_file_from_template(temp_file, d, install_file)

            # Create a shortcut on desktop with admin privileges.
            if platform.system() == 'Windows':
                LOGGER.critical("Failed Dependency Check. Please run the shortcut {} "
                                "or the following bat file as administrator {}".format(shortcutPath,
                                                                                       install_file))

                create_link(shortcutPath, install_file, "Install setup for QGIS PAT Plugin",
                            user_path, True)

            message = 'Installation or updates are required for {}.\n\nPlease quit QGIS and run {} ' \
                      'located on your desktop.'.format(', '.join(failDependencyCheck), title)

            iface.messageBar().pushMessage("ERROR Failed Dependency Check", message,
                                           level=Qgis.Critical,duration=0)

            QMessageBox.critical(None, 'Failed Dependency Check', message)
            return(message)
        else:


            if settings_version is None:
                LOGGER.info('Successfully installed and setup PAT {}'.format(meta_version))
            else:
                if parse_version(meta_version['version']) > parse_version(settings_version['version']):
                    LOGGER.info('Successfully upgraded and setup PAT from {} to {})'.format(settings_version, meta_version))

                elif parse_version(meta_version['version']) < parse_version(settings_version['version']):
                    LOGGER.info('Successfully downgraded and setup PAT from {} to {})'.format(settings_version, meta_version))

            write_setting(PLUGIN_NAME + '/PAT_VERSION', f'{meta_version["version"]} {meta_version["date"]}')

            if os.path.exists(shortcutPath):
                os.remove(shortcutPath)

            if len(osgeo_packs) == 0:
                osgeo_packs = ['geopandas', 'rasterio']

            if len(pip_packs) == 0:
                pip_packs = ["pyprecag"]

            d.update({'osgeo_message': 'Installing {}'.format(', '.join(osgeo_packs)),
                      'osgeo_packs': '' if len(osgeo_packs) == 0 else '-P python3-' + ' -P python3-'.join(osgeo_packs),
                      'pip_packs': '' if len(pip_packs) == 0 else ' '.join(pip_packs),
                      })

            # Create master un&install files
            create_file_from_template(temp_file, d, install_file)

            d.update({'osgeo_message': 'Uninstalling {}'.format(', '.join(osgeo_packs)),
                      'site': OSGeo4W_site,
                      'osgeo_packs': '-o -x python3-' + ' -x python3-'.join(osgeo_packs),
                      'pip_func': 'uninstall'})

            create_file_from_template(temp_file, d, uninstall_file)

    except Exception as err:
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


def get_plugin_state(level='full'):
    from qgis.utils import pluginMetadata

    """TODO: Make the paths clickable links to open folder
        def create_path_link(path):
            path = os.path.normpath(path)
            #"<a href={}>Open Project Folder</a>".format("`C:/Progra~1/needed"`)
            return '<a href= file:///"`{0}"`>{0}</a>'.format(path)
        """
    plug_state = 'QGIS Environment :\n'
    qgis_prefix = qgis.core.QgsApplication.prefixPath()
    if 'LTR' in os.path.basename(qgis_prefix).upper():
        plug_state += '    {:20}\t{}\n'.format('QGIS LTR:', Qgis.QGIS_VERSION)
    else:
        plug_state += '    {:20}\t{}\n'.format('QGIS :', Qgis.QGIS_VERSION)

    if level == 'full':
        if platform.system() == 'Windows':
            qgis_prefix = os.path.abspath(win32api.GetLongPathName(qgis_prefix))
         
        plug_state += '    {:20}\t{}\n'.format('Install Path : ', qgis_prefix)

        plug_state += '    {:20}\t{}\n'.format('Plugin Dir :', os.path.normpath(PLUGIN_DIR))
        plug_state += '    {:20}\t{}\n'.format('Temp Folder :', os.path.normpath(tempfile.gettempdir()))

    plug_state += '    {:20}\t{}\n'.format('Python :', sys.version)
    plug_state += '    {:20}\t{}\n'.format('GDAL :', os.environ.get('GDAL_VERSION', None))
    
    if level == 'full':
        plug_state += '\nPAT Version :\n'
    
    plug_state += '    {:20}\t{} {}\n'.format('PAT :', pluginMetadata('pat', 'version'),
                                                    pluginMetadata('pat', 'release_date'))
    
    plug_state += '    {:20}\t{}\n'.format('Log File :', read_setting(PLUGIN_NAME + '/LOG_FILE'))

    if level == 'full':
        plug_state += '    {:20}\t{}\n'.format('pyPrecAg :', get_distribution('pyprecag').version)
        plug_state += '    {:20}\t{}\n'.format('Geopandas :', get_distribution('geopandas').version)
        plug_state += '    {:20}\t{}\n'.format('Rasterio :', get_distribution('rasterio').version)
        plug_state += '    {:20}\t{}\n'.format('Fiona :', get_distribution('fiona').version)
        plug_state += '    {:20}\t{}\n'.format('Pandas :', get_distribution('pandas').version)
    
        plug_state += '\nR Configuration :\n'
        plug_state += '    {:20}\t{}\n'.format('R Active :', read_setting('Processing/Configuration/ACTIVATE_R'))
        plug_state += '    {:20}\t{}\n'.format('R Install Folder :', read_setting('Processing/Configuration/R_FOLDER'))
    return plug_state
