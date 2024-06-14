# Copy of Test Example Given By

import unittest

from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsCoordinateTransform

#from qgis.core.utils import maybe_transform_wgs84

def  maybe_transform_wgs84(point1, point2, point3):
    return None


class TestUtils(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.WGS = QgsCoordinateReferenceSystem.fromEpsgId(4326)
        cls.PSEUDO = QgsCoordinateReferenceSystem.fromEpsgId(3857)

    def test_to_wgs_pseudo(self):
        point = QgsPointXY(1493761.05913532, 6890799.81730105)
        trans_point = maybe_transform_wgs84(point, self.PSEUDO, QgsCoordinateTransform.ForwardTransform)
        self.assertEqual(trans_point, QgsPointXY(13.41868390243822162, 52.49867709045137332))

    def test_to_wgs_same_crs(self):
        point = QgsPointXY(13.41868390243822162, 52.49867709045137332)
        trans_point = maybe_transform_wgs84(point, self.WGS, QgsCoordinateTransform.ForwardTransform)
        self.assertEqual(trans_point, point)