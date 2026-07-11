from sql import *
from procutil import pid_alive
#from fileHold.volume import *
import os
import subprocess
import time

# Optional live streaming to the relay portal — a broken/missing streaming
# module must never take down local playback, so all hooks no-op on failure.
try:
    import relay_audio_stream as _relay_audio
except Exception:
    class _RelayAudioNoop:
        def __getattr__(self, _name):
            return lambda *a, **k: None
    _relay_audio = _RelayAudioNoop()

def play_mp3_local(fi,vol, a):
   # mpv (audio-only) replaces mpg123: same one-file-per-process lifecycle,
   # but with an IPC socket for pause/seek and a direct 0-100 volume instead
   # of mpg123's 32768 sample scaling. On Windows the same mpv runs directly
   # (no bash wrapper) with the IPC socket as a named pipe.
   vol = int(max(0, min(100, vol)))
   if os.name == "nt":
      # CREATE_NO_WINDOW: mpv.exe is a console app, so without it Windows pops
      # a console window for every track (--no-terminal only mutes the output).
      # --force-window=no: Windows mpv builds default force-window ON, which
      # opens a player window for audio even with --no-video.
      p = subprocess.Popen(['mpv', fi, '--no-terminal', '--no-video',
                            '--force-window=no',
                            '--input-ipc-server=\\\\.\\pipe\\mpvsocket-music',
                            '--volume=' + str(vol)], shell=False,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
   else:
      # When the relay stream's capture sink is up, mpv plays into it (the
      # loopback module mirrors it to the real speakers, so the GM hears the
      # same thing). Empty sink -> mpvAudio.sh omits --audio-device.
      sink = _relay_audio.sink_name() or ''
      p = subprocess.Popen(['./mpvAudio.sh', str(vol), fi, sink])
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
               appsettingFlagUpdate('currentsong', 0)   # queue drained — nothing playing
               _relay_audio.on_playback_stopped()
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
               # pid_alive replaces os.kill(pid, 0), which is not a liveness
               # probe on Windows (signal 0 sends CTRL_C_EVENT).
               if pid_alive(playerPID):
                  songRun = False
               else:
                  if songRun == True:
                     songRun = False
                     # Persist what's ACTUALLY starting (a[2] is process-local and
                     # reshuffles every poll) so the dashboard can show it.
                     appsettingFlagUpdate('currentsong', fi[0])
                     _relay_audio.on_track_start(fi[0])
                     play_mp3_local(fi[1],fi[7], a)
                     _relay_audio.on_track_end()
                     update_data_entry(fi)
                  songRun = True
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


