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
  This project was initiated by CSIRO with support from Wine Australia and the Australia Federal Government’s Department of Agriculture as part of its Rural R&D for Profit program. Development of this QGIS 3 compatible version was supported by CSIRO.”</blockquote>

Requirements and Installation
-----------------------------
PAT is available for QGIS 3.x. The latest release of QGIS can be download from the [Official QGIS site](https://www.qgis.org/en/site/forusers/download.html).

To fully use the on-the-go data workflow, users must also download and install [VESPER](https://precision-agriculture.sydney.edu.au/resources/software/download-vesper).

Once QGIS is installed follow the PAT installation instructions found in chapter 1 of the [PAT user manual](https://nbviewer.jupyter.org/github/CSIRO-Precision-Agriculture/PAT_QGIS_Plugin/blob/master/pat/PAT_User_Manual.pdf#pagemode=bookmarks&view=Fit).

Citation
--------
If you use PAT - Precision Agriculture Tools for any published work, please use the citation below. 

Ratcliff, Christina; Gobbett, David; Bramley, Rob (2020): PAT - Precision Agriculture Tools. v4. CSIRO. 
Software Collection. http://hdl.handle.net/102.100.100/78354
