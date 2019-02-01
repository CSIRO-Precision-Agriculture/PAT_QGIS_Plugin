# -*- coding: utf-8 -*-
"""
/***************************************************************************
 CSIRO Precision Agriculture Tools (PAT) Plugin

 pat_processing - The PrecisionAg Toolbar and Menu setup & functionality
            -------------------
        begin      : 2017-05-25
        git sha    : $Format:%H$
        copyright  : (c) 2018, Commonwealth Scientific and Industrial Research Organisation (CSIRO)
        email      : PAT@csiro.au PAT@csiro.au
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the associated CSIRO Open Source Software       *
 *   License Agreement (GPLv3) provided with this plugin.                  *
 *                                                                         *
 ***************************************************************************/
"""

import logging
import os
from collections import OrderedDict
import re
import fnmatch
from PyQt4.Qt import QCoreApplication
from qgis.gui import QgsMessageBar
from qgis.core import QgsMapLayerRegistry, QgsMessageLog
from qgis.utils import iface

from pat_plugin import LOGGER_NAME
from pat_plugin.util.custom_logging import errorCatcher

LOGGER = logging.getLogger(LOGGER_NAME)
LOGGER.addHandler(logging.NullHandler())


class ProcessingAlgMessages:
    def __init__(self,iface):
        self.iface = iface
        self.alg_name = ''
        self.parameters = OrderedDict()
        self.console_output = ''
        self.execution_commands = ''
        self.error_msg = ''
        self.error = False
        self.output_files = OrderedDict()
        self.log_file = ''
        QgsMessageLog.instance().messageReceived.connect(errorCatcher)

    def processingCatcher(self,msg, tag, level):
        """ Catch messages written to the proccessing algorithm's log and report them to the user.

        source:https://gis.stackexchange.com/a/223965

        Args:
            msg (str): The error message usually in the form of a traceback.
            tag (str): The Log Messages Tab the message is directed at.
            level (int): The error level of the message
        """

        try:
            # Only process Processing algorithm tools
            if tag == 'Processing':
                # only need the Whole-of-block messages.
                if '_cokrige_Whole_of_Block_Analysis' in msg:
                    self.alg_name = 'Whole of Block Analysis'
                    if 'R execution commands' in msg.split('\n')[0]:
                        self.execution_commands = msg

                        LOGGER.info('{st}\nProcessing {}'.format(self.alg_name, st='*' * 50))

                        settingsStr = 'Parameters:---------------------------------------'
                        submsg = re.search('Input_Points_Layer(.*?)source',msg,flags=re.S).group()
                        for item in submsg.split("\n"):
                            if '=' in item:
                                key,val = item.split("=",1)
                                key = key.strip()
                                val = val.strip().strip('\'"')

                                """ When a virtual layer (ie csv delimited layer) is used as an input, it is saved to temp as a layer file
                                so there is no way to back engine and select/re-use the input layer or report it's name
                                As it saves to shapefile by default, the field names will also get truncated to 10chars"""

                                self.parameters[key]=val
                                settingsStr += '\n    {:30}\t{}'.format(key.replace('_',' ') + ':',val)

                        LOGGER.info(settingsStr+ '\n')

                    elif 'R execution console output' in msg.split('\n')[0]:
                        self.console_output = msg
                        self.log_file = os.path.join(os.path.normpath(self.parameters[u'Save_Output']),'{}_alg_qgis_log.log'.format(self.parameters[u'Data_Column']))
                        with open(self.log_file,'w') as wf:
                            wf.write("Whole of Block Experimentation--------------------------------------------------------\n")
                            wf.write(self.execution_commands)
                            wf.write("\n\n--------------------------------------------------------------------------------------\n")
                            wf.write(self.console_output)

                        if 'Error in ' in msg:
                            # find the error message
                            # or  re.compile(ur'Error in ([\S\s]*)', re.MULTILINE)[0]
                            submsg = re.search('Error in (.*?)halted',msg,flags=re.S).group(0)

                            self.error =True
                            self.error_msg =submsg.replace('Error in ', "Error in Whole of Block Experimentation\n")

                            LOGGER.error(self.error_msg)

                        if 'Whole of Block Analysis has been Completed Successfully' in msg:
                            submsg = msg[msg.rfind('[1]'):]
                            tifs_txt_file = re.findall(r'"([^"]*)"', submsg)[0]
                            
                            # break down the list file and provide a list of output files 
                            if not os.path.exists(tifs_txt_file ):
                                print ('Could not find file {}'.format(tifs_txt_file))
                                return 
                    
                            with open(tifs_txt_file, mode='r') as opfile:
                                all_lines = opfile.read()
                    
                            # for each line extract the text between the quotes ie the files
                            files = re.findall(r'"([^"]*)"', all_lines)
                    
                            files_dict = OrderedDict( {'tr': {'title': 'Treatment', 'files': ''},
                                                       r'tr_diff': {'title': 'Treatment difference', 'files': ''},
                                                       r'p_val': {'title': 'p values', 'files': ''},
                                                       r'tr_diff_cov': {'title': 'Treatment difference covariance', 'files': ''},
                                                       r'tr__var': {'title': 'Treatment variance', 'files': ''},
                                                       r'z_score': {'title': 'Z score', 'files': ''}})

                            for pat in [r'*p_val*', r'*_z_*', r'*tr_diff*_cov*', r'*tr_diff*', r'*tr_*_var*']:

                                found_files = fnmatch.filter(files, pat)
                                if pat == r'*_z_*':
                                    pat = 'z_score'

                                key = pat.replace('*', '')

                                files_dict[key]['files'] = list(found_files)
                    
                                files = set(files) - set(found_files)

                            # anything left are the co-kriged surfaces
                            files_dict['tr']['files'] = list(files)

                            self.output_files = files_dict

                            settingsStr = 'Derived Parameters:---------------------------------------'
                            settingsStr += '\n    {:30}\t{}'.format('Output File List:', tifs_txt_file)
                            settingsStr += '\n    {:30}\t{}'.format('Output Log File:', self.log_file)
                            LOGGER.info(settingsStr + '\n')
                            LOGGER.info("Whole of Block Experimentation Completed Successfully !!")

        except Exception as err:
            # print str(err)
            pass


