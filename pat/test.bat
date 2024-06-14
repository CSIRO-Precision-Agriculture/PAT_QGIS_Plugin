rem call "C:\Program Files\QGIS 3.36.2\OSGeo4W.bat"
@echo off
call "C:\Program Files\QGIS 3.36.2\bin\o4w_env.bat"
@echo on
pb_tool compile
pb_tool zip
pb_tool deploy --no-confirm
rem pb_tool help
rem cd C:\Users\bir122\workspace\PAT\GitHubSpare\PAT_QGIS_Plugin\pat
