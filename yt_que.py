from sql import *
import os
import subprocess
import time

from multiprocessing import Process, Value, Array

def YT_Exec(fi):
   vl = 0
   url = fi[0][3]
   name = fi[0][2]
   filePath = fi[0][1]
   mediaType = fi[0][4]
   pkey = fi[0][0]
   tbl = fi[0][5]
   start_dir = os.path.dirname(os.path.realpath(__file__))
   if os.name == "nt":
      pass
   else:
      p = subprocess.Popen(['processMedia/./youtube.sh', url, name, filePath, mediaType, str(pkey), tbl],shell=False)
      appsettingYT_QuePlayFlagUpdatePID(p.pid)
      time.sleep(1)
      while p.poll() is None:
         time.sleep(1)


def YTQue_threader():
    n = Value('i', 1)
    a = Array('i', range(10))
    YT_QueRun = False
    breaker = 1
    appsettingYT_QuePlayFlagUpdate(0)
    while(breaker == 1):
      YT_QueFlag = appsettingYT_QueFlag()
      time.sleep(2)
      if int(YT_QueFlag[0][2]) == 1:
            fi = select_YT_Que_Next()
            if len(fi) == 0:
               pass
               appsettingYT_QuePlayFlagUpdate(0)
            else:
               YT_QueInfo = appsettingYT_QuePID()
               YT_QuePID = int(YT_QueInfo[0][2])
               try:
                  if(os.kill(YT_QuePID, 0) is None):
                     pass
                  else:
                     pass
               except:
                  if YT_QueRun == True:
                     YT_QueRun = False
                     row = [fi[0][0],2]
                     if fi[0][5] == "tblMusic":
                        CRUD_tblMusic(row,"dnUpdate")
                     else:
                        CRUD_tblvideomedia(row,"dnUpdate")
                     YT_Exec(fi)
                  YT_QueRun = True
               else:
                  YT_QueRun = False
                  pass           
            
      if os.name == "nt":
         pass
      else:
         try:
            os.kill(a[0], 0)
         except OSError:
               breaker = 0
         else:
               breaker = 1


