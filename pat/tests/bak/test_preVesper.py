import shutil
import tempfile
import traceback
import unittest
import warnings
from pathlib import Path

import pandas as pd
from qgis.PyQt import QtCore
from qgis.PyQt.QtCore import Qt, QEvent, QPoint, QTimer
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QPushButton, QDialogButtonBox, QMessageBox, QApplication
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsRectangle, QgsVectorLayer, QgsFeature, \
    QgsFeatureIterator

from pat.gui.preVesper_dialog import PreVesperDialog
#from pat.tests.utilities import get_qgis_app  #, warn_with_traceback
from qgisTestingUtils.utilities import get_qgis_app 

from pat.gui.preVesper_dialog import PreVesperDialog

QGISAPP, CANVAS, IFACE, PARENT = get_qgis_app()

TEMP_FOLD = Path(tempfile.gettempdir()).joinpath(Path(__file__).stem)

class TestPreVesper(unittest.TestCase):
    failedTests = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # open up a QGIS instance
        self.project = QgsProject.instance()

    # def tearDown(self) -> None:
    #     """tearDown() is run after every test function"""
    #     project = QgsProject.instance()
    #     project.removeAllMapLayers()

    @classmethod
    def setUpClass(cls) -> None:
        """run once before all its tests are executed"""
        if TEMP_FOLD.exists():
            shutil.rmtree(str(TEMP_FOLD))
        TEMP_FOLD.mkdir()

    @classmethod
    def tearDownClass(cls):
        IFACE.newProject()
        if len(cls.failedTests) == 0:
            print('Tests Passed .. Deleting {}'.format(TEMP_FOLD))
            shutil.rmtree(TEMP_FOLD)

    def test_defaults(self):
        """ poly selection """

        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))
        csv_file = str(Path(__file__).resolve().parent.joinpath('data', 'area1_yield_ascii_wgs84.csv'))
        grd_file = str(Path(__file__).resolve().parent.joinpath('data', 'BlockGrid_v.txt'))

        # need to drop Lat & Lon from cSV so do that first.
        df = pd.read_csv(csv_file)
        df.drop(['Lat','Lon'],axis=1,inplace=True)
        csv_file = str(TEMP_FOLD.joinpath(f'y.csv'))
        df.to_csv(csv_file)

        # Create and open the dialog
        dlg = PreVesperDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        dlg.lneInCSVFile.setText(csv_file)
        dlg.lneInGridFile.setText(grd_file)

        dlg.validate_csv_grid_files(dlg.lneInCSVFile.text(), dlg.lneInGridFile.text())
        dlg.updateCtrlFileName()
        dlg.check_csv(dlg.lneInCSVFile.text())

        dlg.cboKrigColumn.setCurrentIndex(dlg.cboKrigColumn.findText('Yield', QtCore.Qt.MatchFixedString))
        # check auto crs detection
        self.assertEqual('EPSG:28354', dlg.mCRSinput.crs().authid())

        dlg.lneVesperFold.setText(str(TEMP_FOLD))

        self.assertTrue('y_Yield_control.txt', dlg.lneCtrlFile.text())

        # don't know how to unit test the queue so ignore it for now.
        dlg.gbRunVesper.setChecked(False)

        QTest.mouseClick(dlg.buttonBox.button(QDialogButtonBox.Ok), Qt.LeftButton)

        for ea in [ 'y_HD_Yield_control.txt','y_HD_Yield_vesperdata.csv','y_HD_Yield_vespergrid.txt']:
            f = str(TEMP_FOLD.joinpath('Vesper',ea))
            self.assertTrue(Path(f).exists(),f'{ea} does not exist')

    def test_manualCRS(self):
        """ poly selection """

        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))
        csv_file = str(Path(__file__).resolve().parent.joinpath('data', 'area1_yield_ascii_wgs84.csv'))
        grd_file = str(Path(__file__).resolve().parent.joinpath('data', 'BlockGrid_v.txt'))

        # need to drop Lat & Lon from cSV so do that first.
        df = pd.read_csv(csv_file)
        df.drop(['Lat','Lon','EN_EPSG'], axis=1, inplace=True)
        csv_file = str(TEMP_FOLD.joinpath(f'y.csv'))
        df.to_csv(csv_file)

        # Create and open the dialog
        dlg = PreVesperDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        dlg.lneInCSVFile.setText(csv_file)
        dlg.lneInGridFile.setText(grd_file)

        dlg.validate_csv_grid_files(dlg.lneInCSVFile.text(), dlg.lneInGridFile.text())
        dlg.updateCtrlFileName()
        dlg.check_csv(dlg.lneInCSVFile.text())

        dlg.cboKrigColumn.setCurrentIndex(dlg.cboKrigColumn.findText('Yield', QtCore.Qt.MatchFixedString))

        dlg.mCRSinput.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(28354))
        self.assertEqual('EPSG:28354', dlg.mCRSinput.crs().authid())

        dlg.lneVesperFold.setText(str(TEMP_FOLD))

        self.assertTrue('y_Yield_control.txt', dlg.lneCtrlFile.text())

        QTest.mouseClick(dlg.buttonBox.button(QDialogButtonBox.Ok), Qt.LeftButton)

        for ea in [ 'y_HD_Yield_control.txt','y_HD_Yield_vesperdata.csv','y_HD_Yield_vespergrid.txt']:
            f = str(TEMP_FOLD.joinpath('Vesper',ea))
            self.assertTrue(Path(f).exists(),f'{ea} does not exist')

if __name__ == "__main__":
    suite = unittest.makeSuite(TestPreVesper)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)