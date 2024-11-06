import subprocess 
import os

def set_volume_old(vl):
   start_dir = os.path.dirname(os.path.realpath(__file__))
   if os.name == "nt":
       print("volume " + str(vl))
##      player = start_dir+"\\ffplay.exe"
##      player.replace("\\","\\\\",0)
##      fi.replace("\\","\\\\",0)
##      subprocess.Popen([player, '-autoexit', vl]).wait()
   else:
      strOSData =  str(os.uname())
      #print(strOSData)
      if (strOSData.find("chip", 0) > 0):
         vl = vl/100 * 63
         #print(vl)
         subprocess.Popen('amixer cset numid=1 ' + str(vl),shell=True, stdout=subprocess.PIPE).wait()
      else:
         vl = vl/100 * 65000
         #print(vl)
         #subprocess.Popen('sudo amixer cset numid=1 -- ' + str(vl),shell=True, stdout=subprocess.PIPE).wait()
         #headless
         subprocess.Popen('amixer cset numid=3 -- ' + str(vl),shell=True, stdout=subprocess.PIPE).wait()
