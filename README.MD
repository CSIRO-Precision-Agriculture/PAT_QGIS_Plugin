<img src="/pat/icons/icon.png" width="40" height="48"  align="left"/>Precision Agriculture Tools (PAT) Plugin for QGIS 
-------------------------------------------------

PAT is a QGIS plugin for tools required for processing and analysing precision agriculture data. It
makes use of the CSIRO developed [pyPrecAg](https://github.com/CSIRO-Precision-Agriculture/pyprecag#pyprecag) python module.

|Currently it includes|    |
| :---|:---|
|Create Block Grid | Clean Trim and Normalize Points |
|Run Kriging using VESPER |Import VESPER Results |
|Create Polygon from on-the-go GPS Point Trail Data |Generate Random Pixel Selection |
|Normalise/Rescale Raster |Extract Pixel Statistics for Points |
|Calculate Image Indices for Blocks |Resample Image Band to Blocks |
|Create Zones with <i>k</i>-means Clustering|Whole-of-block Analysis |
|Create Strip Trial Points |Run Strip Trial <i>t</i>-test Analysis |
|Persistor |Apply Raster Symbology |

<img src="pat/icons/CSIRO_Grad_RGB.png" width="70" height="70" style="float" align="left"/>
<img src="pat/icons/WineAustralia_Logo.png" width="90" height="90" style="float" align="right"/>
<blockquote>   The Precision Agriculture Tools (PAT) is developed by the CSIRO Precision Agriculture team.  
   This project is supported by Wine Australia through funding from the Australian Government Department of Agriculture and Water Resources as part of its Rural R&D for Profit program.</blockquote>

Requirements and Installation
------------
PAT is only available using QGIS Long Term Release versions 2.18.21 to 2.18.26 for Windows [32bit](http://download.osgeo.org/qgis/win64/QGIS-OSGeo4W-2.18.26-1-Setup-x86.exe) or [64bit](http://download.osgeo.org/qgis/win64/QGIS-OSGeo4W-2.18.26-1-Setup-x86_64.exe). PAT is not currently available in QGIS 3.

To fully use the on-the-go data workflow, users must also download and install VESPER from https://sydney.edu.au/agriculture/pal/software/vesper.shtml.

Once QGIS is installed follow the PAT installation instructions found in chapter 1 of the [PAT user manual](/pat/PAT_User_Manual.pdf).
