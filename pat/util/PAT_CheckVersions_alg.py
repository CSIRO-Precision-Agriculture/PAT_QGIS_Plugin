"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterBoolean,QgsProject,
                       QgsVectorLayer)
from qgis import processing
from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProject, QgsVectorLayer,QgsApplication, Qgis, QgsSettings)

import sys, os
import tempfile
import requests
import importlib
import platform

from packaging.version import parse as parse_version

from pathlib import Path
import pandas as pd

from datetime import datetime

PLUGIN_NAME = 'pat'
PLUGIN_DIR = ''

level = 'Basic'   # Basic or Full or Advanced

class PATVersionsAlgorithm(QgsProcessingAlgorithm):
    """
    This is an example algorithm that takes a vector layer and
    creates a new identical one.

    It is meant to be used as an example of how to create your own
    algorithms and explain methods and variables used to do it. An
    algorithm like this will be available in all elements, and there
    is not need for additional work.

    All Processing algorithms should extend the QgsProcessingAlgorithm
    class.
    """

    # Constants used to refer to parameters and Outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    # Basic is bare minimum, 
    # Advanced includes more dependencies and settings, 
    # Expert includes all dependencies and settings.
    LEVEL = 'LEVEL'
    LEVEL_LIST = ['Basic','Advanced','Expert']
    
    #CHECK_ONLINE = 'CHECK_ONLINE'
    DELETE_PAT_SETTINGS = 'DELETE_PAT_SETTINGS'
    OUTPUT = 'OUTPUT'
    APPEND_TO_EXISTING = 'APPEND_TO_EXISTING'
    
    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PATVersionsAlgorithm()

    def name(self):
        """
        Returns the algorithm name, used for identifying the algorithm. This
        string should be fixed for the algorithm, and must not be localised.
        The name should be unique within each provider. Names should contain
        lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'pat_versions2'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Check python versions for PAT (2026)')

    def group(self):
        """
        Returns the name of the group this algorithm belongs to. This string
        should be localised.
        """
        return self.tr(self.groupId())

    def groupId(self):
        """
        Returns the unique ID of the group this algorithm belongs to. This
        string should be fixed for the algorithm, and must not be localised.
        The group id should be unique within each provider. Group id should
        contain lowercase alphanumeric characters only and no spaces or other
        formatting characters.
        """
        return 'PAT'

    def shortHelpString(self):
        """
        Returns a localised short helper string for the algorithm. This string
        should provide a basic description about what the algorithm does and the
        parameters and Outputs associated with it..
        """
        return self.tr("Check python versions for PAT (2026)")

    def initAlgorithm(self, config=None):
        """
        Here we define the inputs and self.OUTPUT of the algorithm, along
        with some other properties.
        """

        self.addParameter(QgsProcessingParameterEnum(self.LEVEL, ('Level'),
                                                     options=self.LEVEL_LIST,
                                                     defaultValue=0,
                                                     optional=False)  )

        # self.addParameter( QgsProcessingParameterBoolean(name=self.CHECK_ONLINE,
        #                                   description=self.tr('Check for updates'),
        #                                   defaultValue=False ) )
        
        self.addParameter( QgsProcessingParameterBoolean(name=self.DELETE_PAT_SETTINGS,
                                          description=self.tr('Delete All PAT Settings'),
                                          defaultValue=False ) )


        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT, 
                            self.tr('Output File'), 
                            'CSV files (*.csv)'))
            
        self.addParameter( QgsProcessingParameterBoolean(name=self.APPEND_TO_EXISTING,
                                          description=self.tr('Append to existing file'),
                                          defaultValue=False ) )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        self.context = context
        self.feedback = feedback
        #self.CHECK_ONLINE = self.parameterAsBoolean(parameters, self.CHECK_ONLINE,self.context)
        
        self.LEVEL = self.LEVEL_LIST[self.parameterAsInt(parameters, self.LEVEL, self.context)]
        
        self.DELETE_PAT_SETTINGS= self.parameterAsBoolean(parameters, self.DELETE_PAT_SETTINGS,self.context)
        
        self.OUTPUT = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        self.APPEND_TO_EXISTING= self.parameterAsBoolean(parameters, self.APPEND_TO_EXISTING,self.context)
                
        settings = QgsSettings()
        pat_settings = {ea:settings.value(ea) for ea in settings.allKeys()if  ea.startswith('PAT')}
        df_set = pd.DataFrame.from_dict({'name':pat_settings.keys(),'value':pat_settings.values()})
                        

        if self.DELETE_PAT_SETTINGS:
            df_set['current'] = 'deleted'
            self.feedback.pushInfo(f'Deleting PAT Settings...')                
            settings.remove('PAT')
        
        
        self.feedback.pushInfo(f'\n')
                
        settings = QgsSettings()
        pat_settings = {ea:settings.value(ea) for ea in settings.allKeys()if  ea.startswith('PAT')}

        for k,v in pat_settings.items():
            if isinstance(v, QDateTime):
                pat_settings[k] = v.toString("yyyy-MM-dd HH:mm:ss")
            
        df_set = pd.DataFrame.from_dict({'name':pat_settings.keys(),'value':pat_settings.values()})

        if self.DELETE_PAT_SETTINGS:
            df_set['current'] = 'deleted'
            self.feedback.pushInfo(f'Deleting PAT Settings...')                
            settings.remove('PAT')

        qgis_prefix = str(Path(QgsApplication.prefixPath()).resolve())
        qgis_version = '{}-{}'.format(Path(QgsApplication.prefixPath()).stem, Qgis.version())

        # v_dict['PAT'] = qgis.utils.pluginMetadata('pat', 'version')
        df = pd.DataFrame({'PC Name': os.getenv('COMPUTERNAME'),
                            'Date': datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                            'QGIS': qgis_version,
                            'QGIS_prefix': qgis_prefix,
                            'Python': sys.version,
                            'Temp': tempfile.gettempdir() } ,
                            index=[0] )

        # df_dep = pd.DataFrame([{    'current': qgis_version,
        #                             'value': qgis_prefix,}], index=['QGIS'])

        # df_dep.index.name = 'name'

        # df_dep.loc['Temp', 'value'] = [ tempfile.gettempdir()]
        # df_dep.loc['Python', 'current'] = [ sys.version]


        import pyplugin_installer
        p = pyplugin_installer.installer_data.plugins.all()

        if 'pat' in p.keys() :
            p = p['pat']
            inst_ver = parse_version(p['version_installed']) if p['version_installed'] else None
            # Add a column to df called 'pat' and set its value to inst_ver
            df['pat'] = inst_ver
            
            # self.feedback.pushInfo(f'{"PAT":.<25} {inst_ver}')
            # if CHECK_ONLINE :
            #     pyplugin_installer.instance().fetchAvailablePlugins(False)
            #     p = pyplugin_installer.installer_data.plugins.all()['pat']
            #     df_dep.loc['PAT', 'available'] = parse_version(p['version_available'])  # needs further testing

        if self.LEVEL.lower() == 'basic':
            df_py = pd.DataFrame(['geopandas', 'rasterio', 'pyprecag','fiona','osgeo.gdal'], columns=['name'])
        else:
            df_py = pd.DataFrame(['geopandas', 'rasterio', 'pandas', 'shapely', 'fiona', 'pyproj', 'unidecode', 'pint',
                                'numpy', 'scipy', 'chardet', 'pyprecag', 'osgeo.gdal','gdal311-runtime'], columns=['name'])

        # df_py = pd.DataFrame(['rasterio','fiona', 'geopandas'], columns=['name'])

        df_py[['package', 'current', 'available','error', 'file', 'source']] = df_py['name'].apply(self.check_python_dependencies, online=False)

        # convert version object to string
        df_py[['current', 'available']] = df_py[['current', 'available']].astype('string')
        mask = df_py['error'].notnull()
        df_py.loc[mask, 'current'] = (df_py.loc[mask, 'current'].fillna('') + ' ' + df_py.loc[mask, 'error'].astype(str)).str.strip()

        df_py.drop(columns='package',inplace=True)
        df_py.dropna(axis=1, how='all',inplace=True)

        tmp = df_py.set_index('name')[['current']].T.reset_index(drop=True)
        if self.LEVEL.lower() == 'expert':
            df_set = df_set.set_index('name').T.reset_index(drop=True)
        else:
            df_set = df_set.loc[df_set['name'].str.contains('PAT/SETUP')].set_index('name').T.reset_index(drop=True)

        if not df_set.empty:
            df_new = pd.concat([df, df_set], axis=1)

        df_new = pd.concat([df_new, tmp], axis=1)
        
        df_newT = df_new.T
        # Calculate max index width
        index_width = df_newT.index.astype(str).map(len).max() *2

        # Pad index with dots
        df_newT.index = df_newT.index.astype(str).str.pad(index_width, fillchar='.', side='right')       
       
        self.feedback.pushInfo(df_newT.to_string(index=True,header=False) + '\n\n')
        
        if self.APPEND_TO_EXISTING and Path(self.OUTPUT).exists() :
            if '.csv' == Path(self.OUTPUT).suffix:
                df_existing = pd.read_csv(self.OUTPUT,header=None)
            else:
                df_existing = pd.read_excel(self.OUTPUT, header=None)
                
            df_existingT = df_existing.set_index(0).T.set_index(['PC Name','QGIS_prefix'],drop=True)
            df_new.set_index(['PC Name','QGIS_prefix'], inplace=True)

            df_combined = pd.concat([df_existingT, df_new], axis=0)
            df_new = df_combined[~df_combined.index.duplicated(keep='last')]
            df_new.reset_index(inplace=True,drop=False)

        if '.csv' == Path(self.OUTPUT).suffix:
            df_new.T.to_csv(self.OUTPUT, header=False)
        elif '.xlsx' == Path(self.OUTPUT).suffix:
            df_new.T.to_excel(self.OUTPUT, header=False)

            # reply = QMessageBox.question(
            #         None,
            #         "Open self.OUTPUT File",
            #         f"Do you want to open the self.OUTPUT file?\n\n{self.OUTPUT}",
            #         QMessageBox.Yes | QMessageBox.No,
            #         QMessageBox.Yes
            #     )

            # if reply == QMessageBox.Yes:
            #     os.startfile(self.OUTPUT)
            

        # if self.LEVEL.lower() == 'advanced':
        #     df_dep = pd.concat([df_dep, df_set.set_index('name')],ignore_index=False)

        # if 'csv' in self.OUTPUT:
        #     df_dep.to_csv(self.OUTPUT, header=True)
        # else:
        #     df_dep.to_excel(self.OUTPUT, header=True)

            
        vl = QgsVectorLayer(path=self.OUTPUT, baseName=f"PAT_Depencencies", providerLib="ogr")
        QgsProject.instance().addMapLayer(vl, True)

        # df_dep.index = df_dep.index.str.pad(50,fillchar='.',side='right')
        # df_dep = df_dep.fillna('.')
        # df_dep['current']= df_dep['current'].str.pad(12,fillchar='.',side='right')
        return {self.OUTPUT: vl}
        
    def check_python_dependencies(self, package_name, online=False):
        """Check to see if a python package is installed and what version it is with an option to check online for updates.
        Args:
            package_name (str): the name of the package
            online (bool): Check online for updates with priority for osgeo4w over pip.
        """
        
        # NOTE: importlib.metadata.version has issues if there are dist-info for a package
        # and will return the first it finds and most likely the older version.
        pack_status = {'package': package_name,
                    'current': '0.0.0',
                    'available': '0.0.0',
                    'error': None,
                    'value': None,
                    'source': None}

        if 'runtime' in package_name:
            dll_file = Path(QgsApplication.applicationDirPath()).joinpath(package_name.split('-')[0] +'.dll')
            dll_files = [e.stem for e in list(Path(QgsApplication.applicationDirPath()).glob('gdal*.dll'))]

            if dll_file.exists():
                if platform.system() == 'Windows':
                    from win32api import GetFileVersionInfo, LOWORD, HIWORD
                    info = GetFileVersionInfo (str(dll_file), "\\")
                    ms = info['FileVersionMS']
                    ls = info['FileVersionLS']
                    inst_ver = f'{HIWORD(ms)}.{LOWORD(ms)}.{HIWORD(ls)}'  #.{LOWORD (ls)}'
                    pack_status['current'] = inst_ver 
            elif len(dll_files)> 0:
                pack_status['error'] = 'Installed GDAL DLLs: ' + ', '.join(dll_files)

        else:
            try:
                module = importlib.import_module(package_name)
                version = getattr(module, "__version__", '0.0.0')
                pack_status['current'] = version 
            except ImportError as err:
                if package_name != err.name:
                    pack_status['error'] = 'Install Error - ' + str(err)
                # elif package_name==err.name:
                    # pack_status['error'] = 'Not Installed'
                # self.feedback.pushInfo('**',package_name,' - ',err.name,'-', err)
                pass
        
        module = importlib.import_module('numpy')
        np_version = getattr(module, "__version__", '0.0.0')

        
        if (pack_status['current'] == '0.0.0' and package_name in ['geopandas','rasterio','fiona']) or np_version.major < 2:
            ver_file = Path(PLUGIN_DIR).joinpath( 'util','versions_table.csv')
            if ver_file.exists():
                df_ver = pd.read_csv(ver_file,index_col='qgis_version')

                # convert all columns to version numbers
                # for col in df_ver.filter(regex='version').columns:
                #     df_ver[col] = df_ver[col].dropna().apply(parse_version)
                
                # check if this is a ltr version
                qgis_prefix = str(Path(QgsApplication.prefixPath()).resolve())
                qgis_col = 'qgis_version' 
                
                # Find the latest snapshot for each version of QGIS
                # df_ver = df_ver.filter(regex=(f'snap|{qgis_col}') ,axis=1).drop_duplicates(qgis_col,keep='last').set_index(qgis_col)

                qgis_version = Qgis.version().split('-')[0]

                # if 'LTR' in qgis_version:
                #     if Qgis.QGIS_VERSION_INT < 31609:
                #         OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/'
                # else:
                #     if Qgis.QGIS_VERSION_INT < 32000:
                #         OSGeo4W_site = 'http://download.osgeo.org/osgeo4w/'

                if qgis_version not in df_ver.index:
                    pack_status['value']='http://download.osgeo.org/osgeo4w/v2'
                else:
                    snap = df_ver.loc[[qgis_version],'snapshot'].values[0]
                    pack_status['value'] = f'https://download.osgeo.org/osgeo4w/v2/snapshots/{snap}/'
                
                pack_status['source'] = 'osgeo4w'

        if package_name == 'pyprecag':
            if online:
                try:
                    url = 'https://pypi.python.org/pypi/{}/json'.format(package_name)
                    # self.feedback.pushInfo(f'Searching pip for {package},  {url}', end='\t')
                    available_ver = requests.get(url)
                    available_ver.raise_for_status()
                    available_ver = available_ver.json()['info']['version']
                    pack_status['source'] = 'pip'
                    pack_status['available'] = available_ver
                    # self.feedback.pushInfo(f'found {available_ver}')    
                except (requests.ConnectionError, requests.exceptions.HTTPError) as err:
                    available_ver = None
                    # self.feedback.pushInfo(f'Skipping {package}. {err.args[0]}')
            elif pack_status['current'] == '0.0.0' :
                pack_status['source'] = 'pip'

            local_files = [p for p in Path(PLUGIN_DIR).joinpath('install_files').rglob(f'{package_name}*') if
                        p.suffix in ['.gz', '.whl']]

            if len(local_files) > 0:
                for i, ea in enumerate(local_files):
                    loc_pack, loc_ver = ea.stem.split('-')
                    loc_ver = Path(loc_ver).stem

                    if parse_version(loc_ver) < parse_version(inst_ver):
                        continue  # installed version is new than wheel

                    package_name = loc_pack
                    pack_status['package'] = loc_pack
                    pack_status['source'] = 'pip_whl'
                    pack_status['value'] = ea.name

                    if (parse_version(loc_ver) > parse_version(inst_ver)) or (
                            available_ver is not None and parse_version(loc_ver) > parse_version(available_ver)):
                        pack_status['available'] = loc_ver
                # self.feedback.pushInfo(f'Found {len(local_files)} local wheel files, newest version is {available_ver} ')

        pack_status['current'] = parse_version(pack_status['current']) if pack_status['current'] != '0.0.0' else None
        pack_status['available']=  parse_version(pack_status['available']) if pack_status['available'] != '0.0.0' else None

        #self.feedback.pushInfof'{package_name:.<25} {pack_status["current"]}')

        return pd.Series(pack_status)
