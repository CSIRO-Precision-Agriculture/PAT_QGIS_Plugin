##PAT Experimentation=group
##Input_Points_Layer=vector point
##Easting=Field Input_Points_Layer
##Northing=Field Input_Points_Layer
##Treatment_Column=Field Input_Points_Layer
##Data_Column=Field Input_Points_Layer
##Input_Block_Grid= raster #vector
##Model=selection Global; Local
##Covariance_Model=selection Exponential; Spherical; Gaussian
##User_Defined_Neighbourhood_for_Local_CoKriging=boolean FALSE
##Input_Neighbourhood_Size_in_Metre=number 30
##Save_Output=folder

#source(paste0("C:/Users/",Sys.info()['user'],"/.qgis2/python/plugins/pat_plugin/R-Scripts/_cokrige_Whole_of_Block_Analysis.R"))
source(paste0(Sys.getenv("USERPROFILE"),"/.qgis2/python/plugins/pat_plugin/R-Scripts/_cokrige_Whole_of_Block_Analysis.R"))
if(dirname(Save_Output)!=""){
path <- paste0(dirname(Save_Output),"/",basename(Save_Output),"/")
}
if(dirname(Save_Output)==""){
stop("Error: Please Select the Output Folder \n")
}
run_fnc()
