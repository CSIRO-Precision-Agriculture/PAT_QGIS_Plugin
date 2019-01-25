Precision Agriculture Tools (PAT) Plugin for QGIS
-------------------------------------------------

PAT is a QGIS plugin for tools required for processing and analysing precision agriculture data. It
makes use of the CSIRO developed pyPrecAg python module.

Currently it includes: 
1. Create Block Grid
2. Clean Trim and Normalize Points
3. Run Kriging using VESPER
4. Import VESPER Results
5. Create Polygon from on-the-go GPS Point Trail Data
6. Generate Random Pixel Selection
7. Normalise/Rescale(standardise) Raster
8. Extract Pixel Statistics for Points
9. Calculate Image Indices for Blocks
10. Resample Image Band to Blocks
11. Create Zones using <i>k</i>-means Clustering

>   The Precision Agriculture Tools (PAT) is developed by the CSIRO Precision Agriculture team.  
>   This project is supported by Wine Australia through funding from the
>   Australian Government Department of Agriculture and Water Resources as part
>   of its Rural R&D for Profit program.


Installation
------------
PAT is only available for the Windows platform and is not currently available in QGIS 3.

First download and install the QGIS Long Term Release (2.18.14+). From the [QGIS download
page](http://download.qgis.org) scroll down and find the Windows Long term release and download your either the 32bit or 64bit version.

If you would like to use PAT's VESPER Kriging tool, then you will also need to download and install
[VESPER](https://sydney.edu.au/agriculture/pal/software/vesper.shtml).

#### Install the Precision Agriculture Tools (PAT) Plugin.

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