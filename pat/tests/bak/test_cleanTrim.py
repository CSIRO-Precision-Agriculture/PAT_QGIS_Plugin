import shutil
import tempfile
import traceback
import unittest
import warnings
from pathlib import Path

from qgis.PyQt import QtCore
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialogButtonBox
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsRectangle

from pat.tests.utilities import get_qgis_app  #, warn_with_traceback
warnings.resetwarnings()
QGISAPP, CANVAS, IFACE, PARENT = get_qgis_app()

TEMP_FOLD = Path(tempfile.gettempdir()).joinpath(Path(__file__).stem)

class TestCleanTrim(unittest.TestCase):
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
        """Test default settings """

        # Load a project
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        # Create and open the dialog
        from pat.gui.cleanTrimPoints_wizard import CleanTrimPointsDialog
        dlg = CleanTrimPointsDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        pts_lyr = self.project.mapLayersByName('Yield')[0]
        ply_lyr = self.project.mapLayersByName('Polygons')[0]

        dlg.mcboTargetLayer.setLayer(pts_lyr)

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertFalse(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter tool parameters
        dlg.mcboClipPolyLayer.setLayer(ply_lyr)

        dlg.cboProcessField.setCurrentIndex(dlg.cboProcessField.findText('Yield', QtCore.Qt.MatchFixedString))

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertTrue(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter output parameters
        self.assertEqual('EPSG:28354', dlg.mCRSoutput.crs().authid(), "auto crs detection test failed")

        out_csv = str(TEMP_FOLD.joinpath(f'clean_norm_trimmed.csv'))
        dlg.lneSaveCSVFile.setText(out_csv)

        QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Ok), Qt.LeftButton)

        self.assertTrue(Path(out_csv).exists(), f"File does not exist - {out_csv}")

    def test_reproject_selection(self):
        """Test reproject selected points to csv + shapefile"""

        # Load a project
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        # Create and open the dialog
        from pat.gui.cleanTrimPoints_wizard import CleanTrimPointsDialog
        dlg = CleanTrimPointsDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        pts_lyr = self.project.mapLayersByName('Yield')[0]
        pts_lyr.selectByExpression('"DateStamp" in (\'17/03/2024\', \'20/03/2024\', \'21/03/2024\')')
        self.assertEqual(8229, pts_lyr.selectedFeatureCount())

        dlg.mcboTargetLayer.setLayer(pts_lyr)
        dlg.chkUseSelected.setChecked(True)

        # test back and next buttons
        self.assertFalse(dlg.cmdBack.isVisible())
        self.assertEqual('pgeSource', dlg.stackedWidget.currentWidget().objectName())

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)   # go forwards to parameters

        self.assertTrue(dlg.cmdBack.isVisible())
        self.assertTrue(dlg.cmdNext.isVisible())
        self.assertFalse(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        QTest.mouseClick(dlg.cmdBack, Qt.LeftButton)  # go backwards to source
        self.assertTrue(dlg.cmdNext.isVisible())
        self.assertFalse(dlg.cmdBack.isVisible())

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)  # go forwards to parameters
        self.assertEqual('pgeParameters', dlg.stackedWidget.currentWidget().objectName())

        # - enter tool parameters
        dlg.chkReproject.setChecked(True)

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertTrue(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter output parameters
        # user coordinate system
        dlg.mCRSoutput.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(28355))

        # check auto crs detection
        self.assertEqual('EPSG:28355', dlg.mCRSoutput.crs().authid())

        out_csv = str(TEMP_FOLD.joinpath(f'reproject.csv'))
        dlg.lneSaveCSVFile.setText(out_csv)

        out_shp = str(TEMP_FOLD.joinpath(f'reproject.shp'))
        dlg.lneSavePointsFile.setText(out_shp)

        QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Ok), Qt.LeftButton)

        self.assertTrue(Path(out_csv).exists(), f"File does not exist - {out_csv}")
        self.assertTrue(Path(out_shp).exists(), f"File does not exist - {out_shp}")

        import pandas as pd
        df = pd.read_csv(out_csv)
        self.assertEqual(8229,len(df))

        layer = self.project.mapLayersByName('reproject')
        self.assertEqual(1, len(layer), "Layer 'reproject' Not Loaded")
        layer = layer[0]

        self.assertEqual('EPSG:28355', layer.crs().authid(), 'EPSG does not match')
        self.assertEqual(8229,layer.featureCount(), 'Feature count does not match')

    def test_polygon_selections(self):
        """Test poly + point selection to shapefile and change other settings """

        # Load a project
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        # Create and open the dialog
        from pat.gui.cleanTrimPoints_wizard import CleanTrimPointsDialog
        dlg = CleanTrimPointsDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        pts_lyr = self.project.mapLayersByName('Yield')[0]
        dlg.mcboTargetLayer.setLayer(pts_lyr)

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertFalse(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter tool parameters
        ply_lyr = self.project.mapLayersByName('Polygons')[0]
        ply_lyr.selectByExpression('"Id" = 1')
        self.assertEqual(1, ply_lyr.selectedFeatureCount())

        dlg.mcboClipPolyLayer.setLayer(ply_lyr)
        dlg.chkUseSelected_ClipPoly.setChecked(True)

        dlg.cboProcessField.setCurrentIndex(dlg.cboProcessField.findText('Yield', QtCore.Qt.MatchFixedString))
        dlg.chkRemoveZero.setChecked(True)
        dlg.dsbStdCount.setValue(2)

        dlg.chkIterate.setChecked(True)
        dlg.dsbThinDist.setValue(0.8)

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertTrue(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter output parameters
        # check auto crs detection
        self.assertEqual('EPSG:28354', dlg.mCRSoutput.crs().authid())
        out_csv = str(TEMP_FOLD.joinpath(f'clean_normtrimmed.csv'))
        dlg.lneSaveCSVFile.setText(out_csv)

        out_shp = str(TEMP_FOLD.joinpath(f'clean_normtrimmed.shp'))
        dlg.lneSavePointsFile.setText(out_shp)

        QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Ok), Qt.LeftButton)

        self.assertTrue(Path(out_csv).exists(), f"File does not exist - {out_csv}")
        self.assertTrue(Path(out_shp).exists(), f"File does not exist - {out_shp}")

        layer = self.project.mapLayersByName('clean_normtrimmed')
        self.assertEqual(1, len(layer), "Layer 'clean_normtrimmed' Not Loaded")
        layer = layer[0]

        self.assertEqual('EPSG:28354', layer.crs().authid(), 'EPSG does not match')
        self.assertEqual(921,layer.featureCount(), 'Feature count does not match')

        points_remove_shp = out_shp.replace('_normtrimmed', '_removedpts')

        self.assertTrue(Path(points_remove_shp).exists(), f"File does not exist - {points_remove_shp}")

        layer = self.project.mapLayersByName('clean_removedpts')
        self.assertEqual(1, len(layer), "Layer 'clean_removedpts' Not Loaded")
        layer = layer[0]

        self.assertEqual('EPSG:28354', layer.crs().authid(), 'EPSG does not match')
        self.assertEqual(13835,layer.featureCount(), 'Feature count does not match')

    def test_csv(self):
        """Test default settings """

        # Load a project
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        # Create and open the dialog
        from pat.gui.cleanTrimPoints_wizard import CleanTrimPointsDialog
        dlg = CleanTrimPointsDialog(IFACE)
        dlg.open()
        self.assertTrue(dlg.isVisible())

        csv_file = str(Path(__file__).resolve().parent.joinpath('data', 'area1_yield_ascii_wgs84.csv'))
        dlg.optFile.setChecked(True)
        dlg.lneInCSVFile.setText(csv_file)

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertEqual('pgeFromFile',dlg.stackedWidget.currentWidget().objectName())

        dlg.lblXField.setText('Lon')
        dlg.lblYField.setText('Lat')
        dlg.mCRScsv.setCrs(QgsCoordinateReferenceSystem().fromEpsgId(4326))
        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)

        ply_lyr = self.project.mapLayersByName('Polygons')[0]

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertFalse(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter tool parameters
        dlg.mcboClipPolyLayer.setLayer(ply_lyr)

        dlg.cboProcessField.setCurrentIndex(dlg.cboProcessField.findText('Yield', QtCore.Qt.MatchFixedString))

        QTest.mouseClick(dlg.cmdNext, Qt.LeftButton)
        self.assertTrue(dlg.button_box.button(QDialogButtonBox.Ok).isVisible())

        # - enter output parameters
        self.assertEqual('EPSG:28354', dlg.mCRSoutput.crs().authid(), "auto crs detection test failed")

        out_csv = str(TEMP_FOLD.joinpath(f'clean_norm_trimmed.csv'))
        dlg.lneSaveCSVFile.setText(out_csv)

        QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Ok), Qt.LeftButton)

        self.assertTrue(Path(out_csv).exists(), f"File does not exist - {out_csv}")

if __name__ == "__main__":
    suite = unittest.makeSuite(TestCleanTrim)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)