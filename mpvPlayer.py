from sql import *
from fileHold.volume import *
import os
import subprocess
import time
from multiprocessing import Process, Value, Array


def play_mpv_local(fi, scrn, vol, a, loop):
   vl = 0
   start_dir = os.path.dirname(os.path.realpath(__file__))
   screen = str(scrn)
   volume = str(int(max(0, min(100, vol))))
   loops = str(int(max(0, min(9999, loop))))
   speed=str(1)
   
  
   #VideoCommand = f"DISPLAY=:0 mpv --no-terminal --fullscreen=yes --speed={str(speed)} --input-ipc-server=/tmp/mpvsocket --loop-file={str(loops)} --volume={str(volume)} --screen={str(screen)} {str(fi)}"
   print(f"Trying to play: {fi}")
   p = subprocess.Popen(['./mpv.sh',speed,loops,volume,screen,fi],shell=False)
   #p = subprocess.Popen(['mpv', '--no-terminal','--fullscreen=yes','--speed='+str(speed),'--input-ipc-server=/tmp/mpvsocket','--loop-file='+str(loops),'--volume='+str(volume), '--screen='+str(screen), str(fi)])
   appsettingVideoPlayFlagUpdatePID(p.pid)
   time.sleep(1)
   while p.poll() is None:
      #print(p.poll())
      time.sleep(1)


def threaderVideo():
    n = Value('i', 1)
    a = Array('i', range(10))
    videoRun = False
    breaker = 1
    appsettingVideoPlayFlagUpdate(0)
    while(breaker == 1):
      VPlayFlag = appsettingVideoPlayFlag()
      #print(PlayFlag)
      time.sleep(1)
      if int(VPlayFlag[0][2]) == 1:
            fi = select_video_threadQ()
            if len(fi) == 0:
               appsettingVideoPlayFlagUpdate(0)
               n.value = 0
               if a[2] != 0: 
                  a[3] = a[2]
               a[2] = 0
            else:
               if a[2] != 0:
                  a[3] = a[2]
               a[2] = fi[0]
               vplayerInfo = appsettingVideoPlayPID()
               vplayerPID = int(vplayerInfo[0][2])
               try:
                  if(os.kill(vplayerPID, 0) is None):
                     pass
                  else:
                     pass
               except:
                  if videoRun == True:
                     videoRun = False
                     #print("Threader Video3")
                     play_mpv_local(fi[1], fi[7], fi[8], a, fi[9])
                     #              file    scrn  vol         loop
                     update_video_data_entry(fi)
                  videoRun = True
               else:
                  videoRun = False
                  pass
            #time.sleep(2)
            
      elif n.value == 0:
            if a[2] != 0: 
               a[3] = a[2]
            a[2] = 0               
            
      if os.name == "nt":
         #print(a[0])
         #print(n.value)
         import ctypes
         kernel32 = ctypes.windll.kernel32
         SYNCHRONIZE = 0x100000
         process = kernel32.OpenProcess(SYNCHRONIZE, 0, a[0])
         if process != 0:
            kernel32.CloseHandle(process)
            breaker = 1
         else:
            breaker = 0
      else:
         try:
            #print(a[0])
            os.kill(a[0], 0)
         except OSError:
               breaker = 0
         else:
               breaker = 1


#play_mpv_local('','')