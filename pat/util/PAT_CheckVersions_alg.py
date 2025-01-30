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

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsFeatureSink,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterBoolean,QgsProject,
                       QgsVectorLayer)
from qgis import processing
import re
import sys
import tempfile
import requests
from importlib.metadata import version
from packaging.version import parse as parse_version
from pathlib import Path
import pandas as pd
from qgis.core import QgsApplication, Qgis


PLUGIN_NAME = 'pat'
PLUGIN_DIR = ''
level = 'Full'


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

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    LEVEL = 'LEVEL'
    CHECK_ONLINE = 'CHECK_ONLINE'
    LEVEL_LIST = ['Basic','Full']
    OUTPUT = 'OUTPUT'

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
        return 'pat_versions'

    def displayName(self):
        """
        Returns the translated algorithm name, which should be used for any
        user-visible display of the algorithm name.
        """
        return self.tr('Check python versions for PAT')

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
        parameters and outputs associated with it..
        """
        return self.tr("Check python versions for PAT")

    def initAlgorithm(self, config=None):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """


        self.addParameter(QgsProcessingParameterEnum(self.LEVEL, ('Level'),
                                                     options=self.LEVEL_LIST,
                                                     defaultValue=1,
                                                     optional=False)  )

        self.addParameter( QgsProcessingParameterBoolean(name=self.CHECK_ONLINE,
                                          description=self.tr('Check for updates'),
                                          defaultValue=False ) )

        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT, 
                            self.tr('Output File'), 
                            'CSV files (*.csv)'))
        
    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        self.context = context
        self.feedback = feedback
        self.CHECK_ONLINE = self.parameterAsBoolean(parameters, self.CHECK_ONLINE,self.context)
        self.LEVEL = self.LEVEL_LIST[self.parameterAsInt(parameters, self.LEVEL, self.context)]
        
        self.OUTPUT = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        
        qgis_prefix = str(Path(QgsApplication.prefixPath()).resolve())
        
        qgis_version = f'{Qgis.QGIS_VERSION} (LTR)' if 'ltr' in Path(qgis_prefix).name.lower() else Qgis.QGIS_VERSION
        
        self.feedback.pushInfo(f'{"QGIS":.<25} {qgis_version}')
                
        df_dep = pd.DataFrame([{'current': qgis_version}], index=['QGIS'])

        df_dep.index.name = 'name'

        df_dep.loc['Temp', 'current'] = tempfile.gettempdir()
        self.feedback.pushInfo(f'{"Temp":.<25} {tempfile.gettempdir()}')
        
        df_dep.loc['Python','current'] = sys.version
        self.feedback.pushInfo(f'{"Python":.<25} {sys.version}')
        
        import pyplugin_installer
        p = pyplugin_installer.installer_data.plugins.all()

        if 'pat' in p.keys() :
            p = p['pat']
            inst_ver = parse_version(p['version_installed']) if p['version_installed'] else None
            df_dep.loc['PAT', 'current'] = inst_ver

            self.feedback.pushInfo(f'{"PAT":.<25} {inst_ver}')
            if self.CHECK_ONLINE :
                pyplugin_installer.instance().fetchAvailablePlugins(False)
                p = pyplugin_installer.installer_data.plugins.all()['pat']
                df_dep.loc['PAT', 'available'] = parse_version(p['version_available'])  # needs further testing

        if level.lower() == 'basic':
            df_py = pd.DataFrame(['geopandas', 'rasterio', 'pyprecag','gdal308-runtime'], columns=['name'])
        else:
            df_py = pd.DataFrame(['geopandas', 'rasterio', 'pandas', 'shapely', 'fiona', 'pyproj', 'unidecode', 'pint',
                                  'numpy', 'scipy', 'chardet', 'pyprecag', 'gdal','gdal308-runtime'], columns=['name'])

        df_py[['name', 'current', 'available', 'source']] = df_py['name'].apply(self.check_python_dependencies,
                                                                                        args=(self.CHECK_ONLINE ,))
        # df_py['type'] = 'Python'

        df_py = df_py.set_index('name')

        df_dep = pd.concat([df_dep, df_py])

        # convert version object to string
        df_dep[['current', 'available']] = df_dep[['current', 'available']].astype('string')
        df_dep.dropna(axis=1, how='all',inplace=True)

        if 'csv' in self.OUTPUT:
            df_dep.to_csv(self.OUTPUT, header=True)
        else:
            df_dep.to_excel(self.OUTPUT, header=True)
        
        
        # for ea in ['name','current']:
        #     strlen = df_dep[ea].str.len().max()
        #     df_dep[ea]='| '+df_dep[ea].str.pad(width=strlen,side='right', fillchar=' ') +' |'
            
        vl = QgsVectorLayer(path=self.OUTPUT, baseName=f"PAT_Depencancies", providerLib="ogr")
        QgsProject.instance().addMapLayer(vl, True)

        
        return {self.OUTPUT: vl}

    def check_python_dependencies(self, package, online=False):
        """Check to see if a python package is installed and what version it is with an option to check online for updates.
        Args:
            package (str): the name of the package
            online (bool): Check online for updates with priority for osgeo4w over pip.
        """
        
        #https://stackoverflow.com/a/29770964
        inst_ver = '0.0.0'
        if package in sys.modules:
            module = sys.modules[package]
            if hasattr(module, '__version__'): 
                inst_ver = sys.modules[package].__version__
        elif package == 'gdal':
            inst_ver = sys.modules['osgeo'].__version__
        
        elif 'runtime' in package:
            
            dll_file = Path(QgsApplication.applicationDirPath()).joinpath(package.split('-')[0] +'.dll')
            if dll_file.exists():
                inst_ver=dll_file.name
            
        available_ver = '0.0.0'
        file = None
        source = None

        if online:
            #self.feedback.pushInfo(f'Checking online ...... {package}')
            if 'osgeo4w_packs' not in globals():
                urls = ['http://download.osgeo.org/osgeo4w/v2/x86_64/release/python3/',
                        'http://download.osgeo.org/osgeo4w/v2/x86_64/release/gdal/']

                osgeo4w_packs = pd.DataFrame()
                for url in urls:
                    ut = pd.read_html(url, header=0, skiprows=[1])[0]
                    ut.rename(columns=lambda c: re.sub('[^a-zA-Z0-9 ]', '', c).strip(), inplace=True)
                    ut = ut[ut['File Name'].str.endswith('/')]
                    ut['url'] = url + ut['File Name']
                    ut['File Name'] = ut['File Name'].str.rstrip("/")
                    ut.insert(0, 'package', ut['File Name'].str.split('-', n=1).str[-1])
                    ut.set_index('package', inplace=True)
                    osgeo4w_packs = pd.concat([osgeo4w_packs, ut], axis=0)

            if package in osgeo4w_packs.index:
                url = osgeo4w_packs.loc[package, 'url']
                # print(f'Searching osgeo4w for {package},  {url}', end='\t')
                table = pd.read_html(url, header=0, skiprows=[1])[0]
                table.rename(columns=lambda c: re.sub('[^a-zA-Z0-9 ]', '', c).strip(), inplace=True)
                table['Date'] = pd.to_datetime(table['Date'], yearfirst=True, format='mixed')
                table = table.loc[table['File Name'].str.startswith('python3')]
                newest = table.loc[table['Date'].argmax()]['File Name']
                available_ver = newest.split('-')[2]
                # print(f'found {available_ver}')
                source = 'osgeo4w'
                    
            else:

                try:
                    url = 'https://pypi.python.org/pypi/{}/json'.format(package)
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
        local_files = [p for p in Path(PLUGIN_DIR).joinpath('install_files').rglob(f'{package}*') if
                       p.suffix in ['.gz', '.whl']]

        if len(local_files) > 0:
            for i, ea in enumerate(local_files):
                loc_pack, loc_ver = ea.stem.split('-')
                loc_ver = Path(loc_ver).stem

                if parse_version(loc_ver) < parse_version(inst_ver): continue  # installed version is new than wheel

                package = loc_pack
                source = 'pip_whl'
                loc_whl = ea.name

                if (parse_version(loc_ver) > parse_version(inst_ver)) or (
                        available_ver is not None and parse_version(loc_ver) > parse_version(available_ver)):
                    available_ver = loc_ver
                #self.feedback.pushInfo(f'{package} current: {loc_ver}')
                # print(f'Found {len(local_files)} local wheel files, newest version is {available_ver} ')
        
        self.feedback.pushInfo(f'{package:.<25} {inst_ver if inst_ver != "0.0.0" else None}')
        r = pd.Series({'name': package,
                       'current': inst_ver if inst_ver != '0.0.0' else None,
                       'available': available_ver if available_ver != '0.0.0' else None,
                       'source': source})
        
        return r