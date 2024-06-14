import shutil
import tempfile
import traceback
import unittest
import warnings
from pathlib import Path
from unittest import TestCase

#from pat.tests.utilities import get_qgis_app  # , warn_with_traceback
from qgisTestingUtils.utilities import get_qgis_app 

from pat.util.qgis_common import *

QGISAPP, CANVAS, IFACE, PARENT = get_qgis_app()

TEMP_FOLD = Path(tempfile.gettempdir()).joinpath(Path(__file__).stem)


class TestQGISCommon(unittest.TestCase):
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

    def test_removeFileFromQGIS(self):
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        test_file = str(Path(__file__).resolve().parent.joinpath('data', 'PolyMZ_wgs84_MixedPartFieldsTypes.shp'))

        removeFileFromQGIS(test_file)

        self.assertEqual(0, len(self.project.mapLayersByName('Polygons')))

    def test_add_vector_file_to_qgis(self):
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        shp_file = str(Path(__file__).resolve().parent.joinpath('data', 'PolyMZ_wgs84_MixedPartFieldsTypes.shp'))
        vLayer = addVectorFileToQGIS(shp_file, 'new layer')

        self.assertEqual(vLayer.name(), 'new layer')
        self.assertEqual(1, len(self.project.mapLayersByName('new layer')))

        vLayer = addVectorFileToQGIS(shp_file, 'new layer top', atTop=True)

        root = QgsProject.instance().layerTreeRoot()
        layer_node = root.findLayer(vLayer)  # layer is a QgsMapLayer
        parent_group = layer_node.parent()
        idx = parent_group.children().index(layer_node)
        self.assertEqual(0, idx)

        vLayer = addVectorFileToQGIS(shp_file, 'new layer group', group_layer_name='My Group')
        root = QgsProject.instance().layerTreeRoot()
        layer_node = root.findLayer(vLayer)  # layer is a QgsMapLayer
        self.assertEqual('My Group', layer_node.parent().name())

    def test_save_selection(self):
        # initialized QGIS app via import

        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        ply_lyr = self.project.mapLayersByName('Polygons')[0]
        ply_lyr.selectByExpression('"Id" = 0')
        self.assertEqual(1, ply_lyr.selectedFeatureCount())

        out_file = str(TEMP_FOLD.joinpath(f'save_selection.shp'))

        layer = save_layer_to_shapefile(ply_lyr, out_file, onlySelected=True)
        self.assertTrue(Path(out_file).exists())

        self.assertEqual(1, layer.featureCount(), 'Selected Feature count does not match')
        del layer

        pts_lyr = self.project.mapLayersByName('Yield')[0]
        pts_lyr.selectByExpression('"DateStamp" in (\'17/03/2024\', \'20/03/2024\', \'21/03/2024\')')
        self.assertEqual(8229, pts_lyr.selectedFeatureCount(), 'Saved Feature count does not match')

        layer = save_layer_to_shapefile(pts_lyr, out_file, onlySelected=True)
        self.assertEqual(8229, layer.featureCount(), 'Feature count does not match')
        del layer

    def test_user_chosen_crs(self):
        # initialized QGIS app via import

        # Load a project
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        # Create and open the dialog
        ply_lyr = self.project.mapLayersByName('Polygons')[0]

        target_crs = QgsCoordinateReferenceSystem().fromEpsgId(28355)

        out_file = str(TEMP_FOLD.joinpath(f'save_crs.shp'))
        layer = save_layer_to_shapefile(ply_lyr, out_file, target_crs=target_crs)

        self.assertTrue(Path(out_file).exists())

        # check auto crs detection
        self.assertEqual(target_crs, layer.crs())

    def test_vlayer_to_gdf(self):
        # convert selection to GeodataFrame

        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))

        layer = self.project.mapLayersByName('Polygons')[0]
        gdf = vectorlayer_to_geodataframe(layer, bOnlySelectedFeatures=False)

        self.assertEqual(2, len(gdf))
        self.assertEqual(layer.crs().authid(), f'EPSG:{gdf.crs.to_epsg()}')

        layer.selectByExpression('"Id" = 1')
        self.assertEqual(1, layer.selectedFeatureCount())

        gdf = vectorlayer_to_geodataframe(layer, bOnlySelectedFeatures=True)

        self.assertEqual(1, len(gdf))
        self.assertEqual(layer.crs().authid(), f'EPSG:{gdf.crs.to_epsg()}')

        layer = self.project.mapLayersByName('Yield')[0]
        gdf = vectorlayer_to_geodataframe(layer, bOnlySelectedFeatures=True)
        self.assertEqual(14756, len(gdf), 'Feature count does not match')

        layer.selectByExpression('"FID" < 10')
        self.assertEqual(10, layer.selectedFeatureCount(), 'Selected Feature count does not match')
        gdf = vectorlayer_to_geodataframe(layer, bOnlySelectedFeatures=True)
        self.assertEqual(10, len(gdf), 'Feature count does not match')
        del layer, gdf

    def test_build_layer_table(self):
        self.project = QgsProject.instance()
        gdf = build_layer_table()
        self.assertTrue(isinstance(gdf, gpd.GeoDataFrame))
        #self.assertEqual(0, len(gdf))
        self.assertEqual(4, len(gdf))
        print("<=========================HERE")
        print(gdf)

        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))
        gdf = build_layer_table()
        #self.assertEqual(2, len(gdf))
        self.assertEqual(4, len(gdf))
        self.assertTrue(isinstance(gdf, gpd.GeoDataFrame))

    def test_get_layer_source(self):
        self.project.read(str(Path(__file__).resolve().parent.joinpath('data', 'testing.qgz')))
        for layer in self.project.mapLayers().values():
            src = get_layer_source(layer)
            print(layer.source())
            self.assertNotIn('|', src)
            self.assertNotIn('=', src)

if __name__ == "__main__":
    suite = unittest.makeSuite(TestQGISCommon)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

