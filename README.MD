Precision Agriculture Tools (PAT) Plugin for QGIS
-------------------------------------------------

PAT is a QGIS plugin for tools required for processing and analysing precision agriculture data. It
makes use of the CSIRO developed pyPrecAg python module.

Currently it includes:<dd> 
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 1. Create Block Grid<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 2. Clean Trim and Normalize Points<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 3. Run Kriging using VESPER<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 4. Import VESPER Results<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 5. Create Polygon from on-the-go GPS Point Trail Data<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 6. Generate Random Pixel Selection<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 7. Normalise/Rescale(standardise) Raster<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 8. Extract Pixel Statistics for Points<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 9. Calculate Image Indices for Blocks<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 10. Resample Image Band to Blocks<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 11. Create Zones using <i>k</i>-means Clustering<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 12. Create Strip Trial Points<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; 13. Whole-of-block Analysis<br> <br> </dd></dt></dl>

>   The Precision Agriculture Tools (PAT) is developed by the CSIRO Precision Agriculture team.  
>   This project is supported by Wine Australia through funding from the
>   Australian Government Department of Agriculture and Water Resources as part
>   of its Rural R&D for Profit program.


Installation
------------
PAT is only available for the Windows platform and is not currently available in QGIS 3.

First download and install QGIS Long Term Release 2.18.26 [32bit](http://download.osgeo.org/qgis/win64/QGIS-OSGeo4W-2.18.26-1-Setup-x86.exe) or 
[64bit](http://download.osgeo.org/qgis/win64/QGIS-OSGeo4W-2.18.26-1-Setup-x86_64.exe).

If you would like to use PAT's VESPER Kriging tool, then you will also need to download and install
[VESPER](https://sydney.edu.au/agriculture/pal/software/vesper.shtml).

If you would like to use PAT's Whole-of-block analysis tool then you will also need to download and install [R](http://r-project.org/)


#### Install the Precision Agriculture Tools (PAT) Plugin.
Once you have downloaded and installed QGIS install PAT as follows:
1.  In QGIS open the plugin manager. (***Plugins Menu → Manage and Install
    Plugins***)
2.  Select the ***All*** or ***Not installed*** Section.
3.  Search for and select **Precision Agriculture Tools (PAT).**
    Click ***Install plugin***.

During installation a dependency check will be undertaken to ensure certain
python packages are installed. If this check fails a message box, and an ***Error
loading plugin*** dialog will appear warning you that the plugin is broken. This
is expected behaviour. Click ***No*** to dismiss this box and ***quit*** QGIS.

You will be provided a shortcut ***Install PrecisionAg Extras*** on your desktop.
**Run the shortcut** to install the missing components. On opening QGIS the
dependency check will be run again to ensure the installation occurred
correctly. If the PAT menu and toolbar are not present then reinstall
and/or check/activate it using the plugin manager. You should then see a PAT menu
and toolbar.