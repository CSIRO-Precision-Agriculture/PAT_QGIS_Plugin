
import os
import tempfile
from pathlib import Path
from qgis.core import Qgis, QgsApplication

PLUGIN_DIR = str(Path(__file__).resolve().parent.parent)

PLUGIN_NAME = "PAT"
PLUGIN_SHORT = "PAT"
LOGGER_NAME = 'pyprecag'
QGIS_VERSION = '{}-{}'.format(Path(QgsApplication.prefixPath()).stem, Qgis.version().split('-')[0])
TEMPDIR = os.path.join(tempfile.gettempdir(), 'PrecisionAg')
