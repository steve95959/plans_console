# #############################################################################
#
#  Plans_console.py - watch a radiolog .csv file that is being written by
#    the full radiolog program, presumably running on a different computer
#    writing to a shared drive that this program can see.  Also, enable the
#    placement of Markers for Teams when at an assignment.
#
#   developed for Nevada County Sheriff's Search and Rescue
#
#
#   Attribution, feedback, bug reports and feature requests are appreciated
#
#  REVISION HISTORY
#-----------------------------------------------------------------------------
#   DATE   |  AUTHOR  |  NOTES
#-----------------------------------------------------------------------------
#  8/7/2020 SDL         Initial release
#
# #############################################################################
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  See included file LICENSE.txt for full license terms, also
#  available at http://opensource.org/licenses/gpl-3.0.html
#
# ############################################################################
#

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from pygtail import Pygtail
import sys
import os
import shutil
import glob
import regex
import time
import io
import traceback
import json
import random

from plans_console_ui import Ui_MainWindow
from datetime import datetime

sartopo_python_min_version="1.1.2"

#import pkg_resources
#sartopo_python_installed_version=pkg_resources.get_distribution("sartopo-python").version
#print("sartopo_python version:"+str(sartopo_python_installed_version))
##if pkg_resources.parse_version(sartopo_python_installed_version)<pkg_resources.parse_version(sartopo_python_min_version):
#    print("ABORTING: installed sartopo_python version "+str(sartopo_python_installed_version)+ \
#          " is less than minimum required version "+sartopo_python_min_version)
#    exit()
    
from sartopo_python import SartopoSession

statusColorDict={}
statusColorDict["At IC"]=["22ff22","000000"]
statusColorDict["Available"]=["00ffff","000000"]
statusColorDict["In Transit"]=["2222ff","eeeeee"]
statusColorDict["Waiting for Transport"]=["2222ff","eeeeee"]

stateColorDict={}
stateColorDict["#ff4444"]="#eeeeee"
stateColorDict["#eeeeee"]="#ff4444"
sys.tracebacklimit = 1000


### handler for intercepting exceptions
def excepthook(excType, excValue, tracebackobj):
    """
    Global function to catch unhandled exceptions.
    
    @param excType exception type
    @param excValue exception value
    @param tracebackobj traceback object
    """
    separator = '-' * 8
    logFile = "simple.log"
    notice = "\n"
    breakz = "\n"
    versionInfo="    0.0.1\n"
    timeString = time.strftime("%Y-%m-%d, %H:%M:%S")
    tbinfofile = io.StringIO()
    traceback.print_tb(tracebackobj, None, tbinfofile)
    tbinfofile.seek(0)
    tbinfo = tbinfofile.read()
    errmsg = '%s: %s' % (str(excType), str(excValue))
    sections = [separator, timeString, breakz, separator, errmsg, breakz, separator, tbinfo]
    msg = ''.join(sections)
    try:
        f = open(logFile, "w")
        f.write(msg)
        f.write(versionInfo)
        f.close()
    except IOError:
        pass
    print("\nMessage: %s" % str(notice)+str(msg)+str(versionInfo))

### replacement of system exception handler
sys.excepthook = excepthook

def sortByTitle(item):
    return item["properties"]["title"]        
   
class MainWindow(QDialog,Ui_MainWindow):
    def __init__(self,parent):
        QDialog.__init__(self)
        self.parent=parent
        self.rcFileName="plans_console.rc"
        self.configFileName="./local/plans_console.cfg"
        self.accountName=""
        self.readConfigFile()
        if not os.path.isdir(self.watchedDir):
            err=QMessageBox(QMessageBox.Critical,"Error","Specified directory to be watched does not exist:\n \n  "+self.watchedDir+"\n \nAborting.",
                            QMessageBox.Close,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            err.show()
            err.raise_()
            err.exec_()
            exit(-1)
    
        self.ui=Ui_MainWindow()   
        self.ui.setupUi(self)
        self.setAttribute(Qt.WA_DeleteOnClose) 
        self.medval = ""
        self.save_mod_date = 0
        self.assignments = []
        self.forceRescan = 0
        self.feature = {}
        self.feature2 = {}
        self.setStyleSheet("background-color:#d6d6d6")
        self.ui.tableWidget.cellClicked.connect(self.tableCellClicked)        
        self.ui.OKbut.clicked.connect(self.assignTab_OK_clicked)
        self.reloaded = 0
        name1, done1 = QtWidgets.QInputDialog.getText(self, 'Input Dialog','Should the session be restored?')
        if "y" in name1.lower():
            self.load_data()
            self.reloaded = 1
        else:    
            name1, done1 = QtWidgets.QInputDialog.getText(self, 'Input Dialog','Enter the map URL, precede with # if at sartopo.com')                                              
            if "#" in name1:
                self.url="sartopo.com/m/"+name1[1:]  # remove the #
            else:    
                self.url="localhost:8080/m/"+name1
        self.folderId=None
        self.sts=None
        self.link=-1
        self.latField = "0.0"
        self.lonField = "0.0"
        self.NCSO = [39.27, -121.026]
        self.sinceFolder=0 # sartopo wants integer milliseconds
        self.sinceMarker=0 # sartopo wants integer milliseconds
        self.markerList=[] # list of all sartopo markers and their ids
        
        # default window geometry; overridden by previous rc file
        
        self.xd=100
        self.yd=100
        self.wd=1600
        self.hd=1000
        self.fontSize=12
        self.grid=[[0]]
        self.setMinimumSize(200,200)
        self.curTeam = ""
        self.curAssign = ""
        self.curType = ""
        self.totalRows = 0
        self.x = self.xd
        self.y = self.yd
        self.w = self.wd
        self.h = self.hd
        self.color = ["#ffff00", "#cccccc"]
                     
        self.loadRcFile()
        self.setGeometry(int(self.x),int(self.y),int(self.w),int(self.h))
        self.scl = min(self.w/self.wd, self.h/self.hd)
        self.fontSize = int(self.fontSize*self.scl)
        print("Scale:"+str(self.scl))
        
        
        self.updateClock()

        self.ui.notYet=QMessageBox(QMessageBox.Information,"Waiting...","No valid radiolog file was found.\nRe-scanning every few seconds...",
                    QMessageBox.Abort,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
        self.ui.notYet.setStyleSheet("background-color: lightgray")
        self.ui.notYet.setModal(False)
        self.ui.notYet.show()
        self.ui.notYet.buttonClicked.connect(self.notYetButtonClicked)
        self.ui.rescanButton.clicked.connect(self.rescanButtonClicked)

        self.rescanTimer=QTimer(self)
        self.rescanTimer.timeout.connect(self.rescan)
        if self.reloaded == 0:
            self.rescanTimer.start(2000)     # do not start rescan timer if this is a reload
        else:
            self.ui.notYet.close()           # we have csv file in reload
                  
        self.refreshTimer=QTimer(self)
        self.refreshTimer.timeout.connect(self.refresh)
        self.refreshTimer.timeout.connect(self.updateClock)
        self.refreshTimer.start(3000)

        self.since={}
        self.since["Folder"]=0
        self.since["Marker"]=0
        
        self.featureListDict={}
        self.featureListDict["Folder"]=[]
        self.featureListDict["Marker"]=[]

        self.createSTS()
        
    def createSTS(self):

            parse=self.url.replace("http://","").replace("https://","").split("/")
            domainAndPort=parse[0]
            mapID=parse[-1]
            print("calling SartopoSession with domainAndPort="+domainAndPort+" mapID="+mapID)
            if 'sartopo.com' in domainAndPort.lower():
                self.sts=SartopoSession(domainAndPort=domainAndPort,mapID=mapID,
                                        configpath="../sts.ini",
                                        account=self.accountName)
            else:
                self.sts=SartopoSession(domainAndPort=domainAndPort,mapID=mapID)
            self.link=self.sts.apiVersion
            if self.link == -1:
               self.urlErrMsgBox=QMessageBox(QMessageBox.Warning,"Error","Invalid URL",
                             QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
               self.urlErrMsgBox.exec_()
               exit(-1)
            print("link status:"+str(self.link))
    
    
    def addMarker(self):
        folders=self.sts.getFeatures("Folder")
        fid=False
        for folder in folders:
            if folder["properties"]["title"]=="aTEAMS":
                fid=folder["id"]
        if not fid:
            fid=self.sts.addFolder("aTEAMS")
        self.folderId=fid
        ## icons
        if self.medval == " X":
            markr = "ncssar-9"     # medical +
            clr = "FF0000"
        elif self.curType == "LE": # law enforcement
            markr = "ncssar-5"     # red dot with blue circle
            clr = "FF0000"           
        else:
            markr = "usar-1"       # default 
            clr = "FFFF00"
        print("In addMarker:"+self.curTeam)    
        rval=self.sts.addMarker(self.latField,self.lonField,self.curTeam, \
                                self.curAssign,clr,markr,None,self.folderId)
    
    def delMarker(self):
        rval = self.sts.getFeatures("Folder",0)     # get Folders
        ##print("Folders:"+json.dumps(rval))
        fid = None
        for self.feature2 in rval:
            if self.feature2['properties'].get("title") == 'aTEAMS':   # find aTeams Match                
                fid=self.feature2.get("id")
                rval2 = self.sts.getFeatures("Marker",0)
                print("title:"+str(fid))
                ##print("Marker:"+json.dumps(rval2))                  
                # get Markers
                for self.feature2 in rval2:
                    if self.feature2['properties'].get('folderId') == fid and \
                        self.feature2['properties'].get('title') == self.curTeam: # both folder and Team match
                            print("Marker ID:"+self.feature2['id']+" of team: "+self.curTeam)
                            rval3 = self.sts.delMarker(self.feature2['id'])
                            break
        ##print("RestDel:"+json.dumps(rval3,indent=2))
              

    def updateFeatureList(self,featureClass,filterFolderId=None):
        # unfiltered feature list should be kept as an object;
        #  filtered feature list (i.e. combobox items) should be recalculated here on each call 
        print("updateFeatureList called: "+featureClass+"  filterFolderId="+str(filterFolderId))
        if self.sts and self.link>0:
            rval=self.sts.getFeatures(featureClass,self.since[featureClass])
            self.since[featureClass]=int(time.time()*1000) # sartopo wants integer milliseconds
            print("At sts check")
            if rval:
                print("rval:"+str(rval))
                for feature in rval:
                    for oldFeature in self.featureListDict[featureClass]:
                        if feature["id"]==oldFeature["id"]:
                            self.featureListDict[featureClass].remove(oldFeature)
                    self.featureListDict[featureClass].append(feature)
                self.featureListDict[featureClass].sort(key=sortByTitle)
                
            # recreate the filtered list regardless of whether there were new features in rval    
            items=[]
            for feature in self.featureListDict[featureClass]:
                id=feature.get("id",0)
                prop=feature.get("properties",{})
                name=prop.get("title","UNNAMED")
                add=True
                if filterFolderId:
                    fid=prop.get("folderId",0)
                    if fid!=filterFolderId:
                        add=False
                        print("      filtering out feature:"+str(id))
                if add:
                    print("    adding feature:"+str(id))
                    if featureClass=="Folder":
                        items.append([name,id])
                    else:
                        items.append([name,[id,prop]])
            else:
                print("no return data, i.e. no new features of this class since the last check")
        else:
            print("No map link has been established yet.  Could not get Folder objects.")
            self.featureListDict[featureClass]=[]
            self.since[featureClass]=0
            items=[]
        print("  unfiltered list:"+str(self.featureListDict[featureClass]))
        print("  filtered list:"+str(items))
        
    def readConfigFile(self):
        # create the file (and its directory) if it doesn't already exist
        dir=os.path.dirname(self.configFileName)
        if not os.path.exists(self.configFileName):
            print("Config file "+self.configFileName+" not found.")
            if not os.path.isdir(dir):
                try:
                    print("Creating config dir "+dir)
                    os.makedirs(dir)
                except:
                    print("ERROR creating directory "+dir+" for config file.  Better luck next time.")
            try:
                defaultConfigFileName=os.path.join(os.path.dirname(os.path.realpath(__file__)),"default.cfg")
                print("Copying default config file "+defaultConfigFileName+" to "+self.configFileName)
                shutil.copyfile(defaultConfigFileName,self.configFileName)
            except:
                print("ERROR copying the config file.  Better luck next time.")
                
        # specify defaults here
        self.watchedDir="Z:\\"
        
        configFile=QFile(self.configFileName)
        if not configFile.open(QFile.ReadOnly|QFile.Text):
            warn=QMessageBox(QMessageBox.Warning,"Error","Cannot read configuration file " + self.configFileName + "; using default settings. "+configFile.errorString(),
                            QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            warn.show()
            warn.raise_()
            warn.exec_()
            return
        inStr=QTextStream(configFile)
        line=inStr.readLine()
        if line!="[Plans_console]":
            warn=QMessageBox(QMessageBox.Warning,"Error","Specified configuration file " + self.configFileName + " is not a valid configuration file; using default settings.",
                            QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            warn.show()
            warn.raise_()
            warn.exec_()
            configFile.close()
            return
        
        while not inStr.atEnd():
            line=inStr.readLine()
            tokens=line.split("=")
            if tokens[0]=="watchedDir":
                self.watchedDir=tokens[1]
                print("watchedDir specification "+self.watchedDir+" parsed from config file.")
        configFile.close()
        
        # validation and post-processing of each item
        configErr=""

        # process any ~ characters
        self.watchedDir=os.path.expanduser(self.watchedDir)             
            
        if configErr:
            self.configErrMsgBox=QMessageBox(QMessageBox.Warning,"Non-fatal Configuration Error(s)","Error(s) encountered in config file "+self.configFileName+":\n\n"+configErr,
                             QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            self.configErrMsgBox.exec_()

    def notYetButtonClicked(btn):
        exit()

    def rescanButtonClicked(self):
        self.forceRescan = 1
        self.rescan()    #force a rescan/refresh
            
    def rescan(self):
        print("scanning "+self.watchedDir+" for latest valid csv file...")
        self.csvFiles=[]
        self.readDir()
        if self.csvFiles!=[]:
            self.rescanTimer.stop()
            self.ui.notYet.close()
            self.watchedFile=self.csvFiles[0][0]
            self.setWindowTitle("Plans_console B - "+os.path.basename(self.watchedFile))
            # remove the pygtail offset file, if any, so pygtail will
            #  read from the beginning even if this file has already
            #  been read by pygtail
            self.offsetFileName=self.watchedFile+".offset"+str(os.getpid())
            if os.path.isfile(self.offsetFileName):
                os.remove(self.offsetFileName)
            print("  found "+self.watchedFile)
            self.refresh()

    # refresh - this is the main radiolog viewing loop
    #  - read any new lines from the log file
    #  - process each new line
    #    - add a row to the appropriate panel's table    
    def refresh(self):
        if self.csvFiles!=[]:
            newEntries=self.readWatchedFile()
            if newEntries:
                ix = 0
                for entry in newEntries:
                    print("In loop: %s"% entry)                   
                    if len(entry)==10:
                        if self.forceRescan == 1:
                            print("AT force rescan")
                            if ix < self.totalRows:
                                ix = ix + 1
                                continue    # skip rows until get to new rows
                        time,tf,callsign,msg,radioLoc,status,epoch,d1,d2,d3=entry
                        self.ui.tableWidget.insertRow(0)
                        self.ui.tableWidget.setItem(0, 0, QtWidgets.QTableWidgetItem(time))
                        self.ui.tableWidget.setItem(0, 1, QtWidgets.QTableWidgetItem(callsign))    
                        self.ui.tableWidget.setItem(0, 2, QtWidgets.QTableWidgetItem(msg))    
                        self.ui.tableWidget.setItem(0, 3, QtWidgets.QTableWidgetItem(status))    
                        prevColor=self.ui.tableWidget.item(0,1).background().color().name()
                        newColor=stateColorDict.get(prevColor,self.color[0])
                        self.setRowColor(self.ui.tableWidget,0,newColor)
                        self.totalRows = self.ui.tableWidget.rowCount()
                        print("status:"+status+"  color:"+statusColorDict.get(status,["eeeeee",""])[0])
## save data
                self.save_data()                

    def save_data(self):
        print("In savedata")
        data1 = {}
        rowx = {}
        rowy = {}
        for itm in range(self.ui.tableWidget.rowCount()):
            data1['time'] = self.ui.tableWidget.item(itm, 0).text()
            data1['callsign'] = self.ui.tableWidget.item(itm, 1).text()
            data1['msg'] = self.ui.tableWidget.item(itm, 2).text()
            data1['status'] = self.ui.tableWidget.item(itm, 3).text()
            data1['color'] = self.ui.tableWidget.item(itm,1).background().color().name()
            rowx['rowA'+str(itm)] = data1.copy()
        for itm2 in range(self.ui.tableWidget_TmAs.rowCount()):
            data1.update({'team': self.ui.tableWidget_TmAs.item(itm2, 0).text()})
            data1.update({'assign': self.ui.tableWidget_TmAs.item(itm2, 1).text()})
            data1.update({'type': self.ui.tableWidget_TmAs.item(itm2, 2).text()})
            data1.update({'med': self.ui.tableWidget_TmAs.item(itm2, 3).text()})
            rowy['rowB'+str(itm2)] = data1.copy()
        alld = json.dumps([{'url':self.url},{'csv':self.watchedFile+'%'+self.offsetFileName+ \
                                             '%'+str(self.csvFiles)}, rowx, rowy])
        fid = open("save_plans_console.txt",'w')
        fid.write(alld)
        fid.close()

    def load_data(self):
        print("In load data")
        fid = open("save_plans_console.txt",'r')
        alld = fid.read()
        l = json.loads(alld)
        print("Get:"+str(l))
        self.url = l[0]['url']
        self.watchedFile,self.offsetFileName, self.csvFiles = l[1]['csv'].split('%')
        irow = 0
        for key in l[2]:
            self.ui.tableWidget.insertRow(irow)            
            self.ui.tableWidget.setItem(irow, 0, QtWidgets.QTableWidgetItem(l[2][key]['time']))
            self.ui.tableWidget.setItem(irow, 1, QtWidgets.QTableWidgetItem(l[2][key]['callsign']))
            self.ui.tableWidget.setItem(irow, 2, QtWidgets.QTableWidgetItem(l[2][key]['msg']))
            self.ui.tableWidget.setItem(irow, 3, QtWidgets.QTableWidgetItem(l[2][key]['status']))
            self.setRowColor(self.ui.tableWidget,irow,l[2][key]['color'])
            irow = irow + 1
        irow = 0    
        for key in l[3]:
            self.ui.tableWidget_TmAs.insertRow(irow)            
            self.ui.tableWidget_TmAs.setItem(irow, 0, QtWidgets.QTableWidgetItem(l[3][key]['team']))
            self.ui.tableWidget_TmAs.setItem(irow, 1, QtWidgets.QTableWidgetItem(l[3][key]['assign']))    
            self.ui.tableWidget_TmAs.setItem(irow, 2, QtWidgets.QTableWidgetItem(l[3][key]['type']))
            self.ui.tableWidget_TmAs.setItem(irow, 3, QtWidgets.QTableWidgetItem(l[3][key]['med']))
            irow = irow + 1
        fid.close()
        
    def setRowColor(self,table,row,color):
        for col in range(table.columnCount()):
            table.item(row,col).setBackground(QColor(color))

    def tableCellClicked(self,row,col):
        table=self.sender()
        i=table.item(row,col)
        if i:
            prevColor=i.background().color().name()
            if prevColor == self.color[1]:
                newColor=stateColorDict.get(prevColor,self.color[0])
            else:
                newColor=stateColorDict.get(prevColor,self.color[1])
            self.setRowColor(self.ui.tableWidget,row,newColor)
## save data
        self.save_data()

    def assignTab_OK_clicked(self):
        print("Ok button clicked, team is:"+self.ui.Team.text())
        rval = self.sts.getFeatures("Assignment",0)     # get assignments
        ifnd = 1                                        # flag for found valid Assignment
        ## location code are IC for command post (for type LE, leave marker on map, but at (lon-0.5deg) )
        ##                   TR for in transit
        ##                   RM to remove a team from the table
        ##                   Assignment name 
        if self.ui.Assign.text() != "IC" and self.ui.Assign.text() != "TR" \
           and self.ui.Assign.text() != "RM" : ## chk to see if assignment exists (ignore IC, TR, RM)
          ifnd = 0  
          for self.feature in rval:
            ##print("ZZZZ:"+str(self.feature["properties"].get("letter")))  # search for new assignment
            if str(self.feature["properties"].get("letter")) == self.ui.Assign.text():   # find assignment on map
                ##print("Geo:"+str(self.feature.get("geometry")))
                ifnd = 1     # found the desired assignment on the map, so continue
                break
        if self.ui.Team.text() == "" or ifnd == 0:  # error - checking select below when entry does not exist
            pass  # beepX1
            print("Issue with Assign inputs")
            return
        ifnd = 0                      # flag for found existing Team assignment
        irow = 0
        print("count:"+str(self.ui.tableWidget_TmAs.rowCount()))
        for ix in range(self.ui.tableWidget_TmAs.rowCount()):      # Look for existing Team entry in table
            if self.ui.Team.text() == self.ui.tableWidget_TmAs.item(ix,0).text():  # update
                ifnd = 1   # set found in table, may be on the map, too
                irow = ix      # why do I need this equivalence??
                if (self.ui.tableWidget_TmAs.item(ix,1).text() == "IC" and \
                    self.ui.tableWidget_TmAs.item(ix,2).text() != "LE") or \
                    self.ui.tableWidget_TmAs.item(ix,1).text() == "TR":
                     ifnd = 2        # means came from IC (except type LE) or TR, so s/b no marker on map now
                #get old marker location to remove 
                #rm marker (NOTE, if was at IC (except type LE) or TR there will not be a marker)
                #if to-assignment is IC or TR do not add marker
                #new marker
                break
        if self.ui.comboBox.currentText() == "Select": 
            if ifnd == 0:                 # does not exist in table
                pass  # beepX1
                print("Issue with Assign inputs2")
                return
            else:
                indx = self.ui.comboBox.findText(self.ui.tableWidget_TmAs.item(ix,2).text())
                print("INDEX is:"+str(indx))
                self.ui.comboBox.setCurrentIndex(indx)
                if self.ui.tableWidget_TmAs.item(ix,3).text() == ' X':  # also check Med setting
                    self.ui.Med.setChecked(True)
        if self.ui.Assign.text() == "RM":     # want to completely remove team
            if ifnd == 1:               # want to remove and presently in table AND on map
                self.curTeam = self.ui.Team.text()
                self.delMarker()        # uses curTeam to find
            if ifnd == 1 or ifnd == 2:  # want to remove and presently only in table
                self.ui.tableWidget_TmAs.removeRow(irow)
            # clear fields
            if ifnd == 0:    # entry not found in table
                pass  #  beep
            else:
                self.ui.Team.setText("")
                self.ui.Assign.setText("")
                self.ui.comboBox.setCurrentIndex(0)
                self.ui.Med.setChecked(False)
## save data
            self.save_data()    
            return
        ##  ifnd=0  not in table and not on map  - add team and marker
        ##  ifnd=1  in table and on map          - update/moving
        ##  ifnd=2  in table but not on map      - add to map (except IC or TR)
        # usually won't be assignment IC nor TR
        if ifnd == 0 and (self.ui.Assign.text() == "IC" or self.ui.Assign.text() == "TR") and \
                          self.ui.comboBox.currentText() != "LE":
            pass # beep
            return
        ###if ifnd == 0: self.ui.tableWidget_TmAs.insertRow(0)
        if ifnd == 1:                             # moving so remove present loc on map
            self.curTeam = self.ui.tableWidget_TmAs.item(irow,0).text()
            self.delMarker()        # uses curTeam to find
        cntComma = self.ui.Team.text().count(',')+1   # add 1 for first element
        tok = self.ui.Team.text().split(',')
        for ix in range(cntComma):
            if ifnd == 0: self.ui.tableWidget_TmAs.insertRow(0)
            self.ui.tableWidget_TmAs.setItem(irow, 0, QtWidgets.QTableWidgetItem(tok[ix]))
            self.ui.tableWidget_TmAs.setItem(irow, 1, QtWidgets.QTableWidgetItem(self.ui.Assign.text()))    
            self.ui.tableWidget_TmAs.setItem(irow, 2, QtWidgets.QTableWidgetItem(self.ui.comboBox.currentText()))
            self.curTeam = tok[ix]
            self.curAssign = self.ui.Assign.text()
            self.curType = self.ui.comboBox.currentText()
            if self.ui.Med.isChecked(): self.medval = " X"
            else: self.medval = " "    #  need at least a space so that it is not empty
            self.ui.tableWidget_TmAs.setItem(0, 3, QtWidgets.QTableWidgetItem(self.medval))
        # find center of shape in latField and lonField float
            if self.curType == "LE" and self.curAssign == "IC":    # moving LE to 'IC' (away)
                self.lonField = self.NCSO[1]+random.uniform(-1.0, 1.0)*0.001  # temp location; randomly adjust
                self.latField = self.NCSO[0]+random.uniform(-1.0, 1.0)*0.001    # +/-0.001 deg lat and long
            else:   
                self.calcLatLon_center()              # use self.ui.Assign.text() to find shape
        # set marker type (in addMarker) based on Med or if type=LE
            if (self.curAssign != "IC" and self.curAssign != "TR") or self.curType == "LE":
                self.addMarker()          # uses self.ui.Team, medval

        # clear fields
        self.ui.Team.setText("")
        self.ui.Assign.setText("")
        self.ui.comboBox.setCurrentIndex(0)
        self.ui.Med.setChecked(False)
## save data            
        self.save_data()
        
    def calcLatLon_center(self):
        print("iN LATLOG")
        loc = self.feature['geometry'].get("coordinates")   # of an assignment
        loc_lat = 0
        loc_long = 0
        ipt = 0
        lenloc = len(loc)
        if type(loc[0][0]) is list:    # polygon is list of list
            loc = loc[0]  
            ipt = 1                 # skip 1st pt of polygon since it is repeated
            lenloc = len(loc) - 1
            for loca in loc:
              if ipt == 1:
                  ipt = 0
                  continue            # skip 1st pt
              loc_lat = loc_lat + loca[1]
              loc_long = loc_long + loca[0]
            avg_lat = loc_lat/lenloc
            avg_lon = loc_long/lenloc
        else:    # line
            loca = loc[int(lenloc/2)]   # use its mid point
            avg_lat = loca[1]
            avg_lon = loca[0]
        print("Loc-lat:"+str(avg_lat)+" loc-long:"+str(avg_lon))
        self.latField = avg_lat
        self.lonField = avg_lon
        
    # get a list of non-clueLog filenames, modification times, and sizes
    #  in the watchedDir, sorted by modification time (so that the most recent
    #  file is the first item in the list)
    def readDir(self):
        print("in readDir")
        f=glob.glob(self.watchedDir+"\\*.csv")
        print("Files: %s"%f)
        f=[x for x in f if not regex.match('.*_clueLog.csv$',x)]
        f=[x for x in f if not regex.match('.*_fleetsync.csv$',x)]
        f=[x for x in f if not regex.match('.*_bak[123456789].csv$',x)]
        f=sorted(f,key=os.path.getmtime,reverse=True)
        for file in f:
            l=[file,os.path.getsize(file),os.path.getmtime(file)]
            self.csvFiles.append(l)

    def readWatchedFile(self):
        newEntries=[]
        for line in Pygtail(self.watchedFile,offset_file=self.offsetFileName):
            newEntries.append(line.split(','))
        return newEntries
                
    def updateClock(self):
        self.ui.clock.display(time.strftime("%H:%M"))
        
    def saveRcFile(self):
        print("saving...")
        (self.x,self.y,self.w,self.h)=self.geometry().getRect()
        rcFile=QFile(self.rcFileName)
        if not rcFile.open(QFile.WriteOnly|QFile.Text):
            warn=QMessageBox(QMessageBox.Warning,"Error","Cannot write resource file " + self.rcFileName + "; proceeding, but, current settings will be lost. "+rcFile.errorString(),
                            QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            warn.show()
            warn.raise_()
            warn.exec_()
            return
        out=QTextStream(rcFile)
        out << "[Plans_console]\n"
        out << "font-size=" << self.fontSize << "pt\n"
        out << "x=" << self.x << "\n"
        out << "y=" << self.y << "\n"
        out << "w=" << self.w << "\n"
        out << "h=" << self.h << "\n"
        rcFile.close()
        
    def loadRcFile(self):
        print("loading...")
        rcFile=QFile(self.rcFileName)
        if not rcFile.open(QFile.ReadOnly|QFile.Text):
            warn=QMessageBox(QMessageBox.Warning,"Error","Cannot read resource file " + self.rcFileName + "; using default settings. "+rcFile.errorString(),
                            QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            warn.show()
            warn.raise_()
            warn.exec_()
            return
        inStr=QTextStream(rcFile)
        line=inStr.readLine()
        if line!="[Plans_console]":
            warn=QMessageBox(QMessageBox.Warning,"Error","Specified resource file " + self.rcFileName + " is not a valid resource file; using default settings.",
                            QMessageBox.Ok,self,Qt.WindowTitleHint|Qt.WindowCloseButtonHint|Qt.Dialog|Qt.MSWindowsFixedSizeDialogHint|Qt.WindowStaysOnTopHint)
            warn.show()
            warn.raise_()
            warn.exec_()
            rcFile.close()
            return
        while not inStr.atEnd():
            line=inStr.readLine()
            tokens=line.split("=")
            if tokens[0]=="x":
                self.x=int(tokens[1])
            elif tokens[0]=="y":
                self.y=int(tokens[1])
            elif tokens[0]=="w":
                self.w=int(tokens[1])
            elif tokens[0]=="h":
                self.h=int(tokens[1])
            elif tokens[0]=="font-size":
                self.fontSize=int(tokens[1].replace('pt',''))
        rcFile.close()
                
    def closeEvent(self,event):  # to save RC file
        self.saveRcFile()
        event.accept()
        self.parent.quit()
        
def main():
    app = QApplication(sys.argv)
    w = MainWindow(app)
    w.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
