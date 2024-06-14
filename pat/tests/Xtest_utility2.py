# Experimental Work By Mike Birchall to Implement a Test for the rasterSymbiology_dialog

import unittest
import os


from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtCore import Qt, QEvent, QPoint, QTimer
from qgis.PyQt.QtWidgets import QPushButton, QDialogButtonBox, QMessageBox, QApplication
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent
from qgis.core import QgsProject, QgsCoordinateReferenceSystem, QgsRectangle, QgsVectorLayer, QgsFeature, QgsFeatureIterator

from .utilities import get_qgis_app

# 1. Get all relevant QGIS objects
CANVAS: QgsMapCanvas
QGISAPP, CANVAS, IFACE, PARENT = get_qgis_app()

class TestFlow(unittest.TestCase):

    def test_experimental(self):
        """Experimental Test of rasterSymbiology_dialog"""
        print ("Experimental Test")
        print("     QGISAPP=",QGISAPP)
        print("     CANVAS =",CANVAS)
        print("     IFACE  =",IFACE)
        print("     PARENT =",PARENT )
        
         # 2. need to import here "the dialog under test" so that there's already an initialized QGIS app
        from  pat.gui.rasterSymbology_dialog import RasterSymbologyDialog
        
        #from pat.gui.rasterSymbiology_dialog import  RasterSymbologyDialog
        #from quick_api.gui.quick_api_dialog import QuickApiDialog
                
        
        # 3. first set up a project
        project = QgsProject.instance()
        
        dlst = ["C:\\","Users","bir122","workspace","PAT","data_dir","projs","mnbP3.qgz"]
        p=""
        for str in dlst: p=os.path.join(p,str)
        print("File exists:",os.path.exists(p))
        
        
        project.read(p)
        print("Project Filename = ", project.fileName())
        

        # 4. Create and open the dialog
        dlg = RasterSymbologyDialog(IFACE)
        dlg.open()
        print("Is dialog visible?:",dlg.isVisible())
        # Assert test for visibility
        self.assertTrue(dlg.isVisible())
        
        print("AVAILABLE TYPES:")
        for i in range(dlg.cboType.count()):
            print(i,dlg.cboType.itemText(i))
       
        # Select Index 2      
        dlg.cboType.setCurrentIndex(2)       
        print ("Selected:", dlg.cboType.currentText(), "Index",dlg.cboType.currentIndex())
             
        print("AVAILABLE LAYERS:")    
        for i in range(dlg.mcboTargetLayer.count()):
            print(i,dlg.mcboTargetLayer.itemText(i))
        print ("Selected:", dlg.mcboTargetLayer.currentText(), "Index",dlg.mcboTargetLayer.currentIndex())
        
        #cancel_button: QPushButton = dlg.button_box.Apply
        #QTest.mouseClick(dlg.button_box.Apply, Qt.LeftButton)
        #QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Cancel), Qt.LeftButton)
        # Click the Apply Button
        print("Clicking on the Cancel Button")
        QTest.mouseClick(dlg.button_box.button(QDialogButtonBox.Cancel), Qt.LeftButton)
        print("Done Clicking The Cancel Button")
        #lst=dlg.c.cboType.addItems()
     

        # 5. Click the cancel button which should close the dialog
     #   cancel_button: QPushButton = dlg.map_button
     #   QTest.mouseClick(map_button, Qt.LeftButton)
     #   self.assertFalse(dlg.isVisible())
     #   self.assertIsInstance(CANVAS.mapTool(), PointTool)


