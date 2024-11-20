from sql import *
#from fileHold.volume import *
import os
import subprocess
import time

def play_mp3_local(fi,vol, a):
   vl = 0
   start_dir = os.path.dirname(os.path.realpath(__file__))
   if os.name == "nt":
      #player = start_dir+"\\ffplay.exe"
      player = start_dir+"\\cmdmp3win.exe"
      player.replace("\\","\\\\",0)
      fi.replace("\\","\\\\",0)
      #set_volume(a)
      #p = subprocess.Popen([player, '-autoexit', fi],shell=False)
      p = subprocess.Popen([player, fi],shell=False)
      while p.poll() is None:
         #print(p.poll())
         if vl != a[1]:
            #set_volume(a[1])
            vl = int(a[1])
         time.sleep(1) 
   else:
      vol = int(max(0, min(100, vol)))
      volume = int(32768*(vol/100))
      #print(volume)
      p = subprocess.Popen(['mpg123', '-q', '-f', str(volume), fi])
      appsettingAudioPlayFlagUpdatePID(p.pid)
      time.sleep(1)
      while p.poll() is None:
         #print(p.poll())
         # if vl != a[1]:
         #    #set_volume(a[1])
         #    vl = int(a[1])
         time.sleep(1)


def threader(n, a):
    songRun = False
    breaker = 1
    appsettingAudioPlayFlagUpdate(0)
    while(breaker == 1):
      PlayFlag = appsettingAudioPlayFlag()
      #print(PlayFlag)
      time.sleep(1)
      
      #Too Implement
      #I admit that it is not called 'volume', but what about this, from mpg123 --longhelp:
      #-f <n> --scale <n> scale output samples (soft gain - based on 32768), default=32768)
      #ex mpg123 -f 32768 40U2.mp3  == volume = 32768*(vol/100)
      if int(PlayFlag[0][2]) == 1:
            fi = select_play_threadQ()
            if len(fi) == 0:
               appsettingAudioPlayFlagUpdate(0)
               n.value = 0
               if a[2] != 0: 
                  a[3] = a[2]
               a[2] = 0
            else:
               if a[2] != 0:
                  a[3] = a[2]
               a[2] = fi[0]
               playerInfo = appsettingAudioPlayPID()
              #print(playerInfo)
               playerPID = int(playerInfo[0][2])
               try:
                  if(os.kill(playerPID, 0) is None):
                     pass
                  else:
                     pass
               except:
                  if songRun == True:
                     songRun = False
                     play_mp3_local(fi[1],fi[7], a)
                     update_data_entry(fi)
                  songRun = True
               else:
                  songRun = False
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


