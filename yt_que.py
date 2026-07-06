from sql import *
from procutil import pid_alive
import os
import shutil
import subprocess
import sys
import time
import ytdlp_source

from multiprocessing import Process, Value, Array

def YT_Exec(fi):
   """Download one queued row — shared Python pipeline for BOTH OSes.

   Python port of processMedia/youtube.sh (kept in-tree, unreferenced, as the
   rollback hatch). The observable contract is preserved exactly: same yt-dlp
   format flags, the file lands in the repo root then moves to <dir><name>,
   SUCCESS = THE FILE EXISTS ON DISK (never the returncode — the SIGCHLD
   reaper on Linux steals those), dnLoadStatus 2 -> 3/4, finished/failed
   chime. yt-dlp comes from pip and runs as `python -m yt_dlp` (no bash, no
   runtime git clone); ffmpeg must be on PATH for the extract/merge steps."""
   url = fi[0][3]
   name = fi[0][2]
   filePath = fi[0][1]
   mediaType = fi[0][4]
   pkey = fi[0][0]
   tbl = fi[0][5]
   start_dir = os.path.dirname(os.path.realpath(__file__))

   if mediaType == 'mp3':
      fmt = ['-i', '-x', '--audio-format', mediaType]
   else:
      fmt = ['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]',
             '--merge-output-format', mediaType]
   # --output=NAME ('=' form): video-id filenames can START WITH '-' (~1.6% of
   # videos) and must not parse as a flag. --no-playlist guards a stray &list=.
   cmd = [sys.executable, '-m', 'yt_dlp', *fmt, '--no-playlist',
          f'--output={name}', url, '--proxy', '']

   # youtube.sh's git-pull-before-every-download, restored: refresh the yt-dlp
   # checkout and run from it via PYTHONPATH (pip copy is the fallback).
   ytdlp_source.refresh()
   kwargs = {'cwd': start_dir, 'shell': False, 'env': ytdlp_source.popen_env()}
   if os.name != 'nt':
      kwargs['preexec_fn'] = lambda: os.nice(19)   # youtube.sh's `renice -n 19`
   else:
      # Suppress the console window each yt-dlp spawn would otherwise pop;
      # ffmpeg grandchildren inherit the hidden console too.
      kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
   # Keep the last download's yt-dlp output on disk — a status-4 row with no
   # diagnostics is undebuggable (the workers have no visible console).
   log_path = os.path.join(start_dir, 'instance', 'ytdlp_last.log')
   try:
      os.makedirs(os.path.join(start_dir, 'instance'), exist_ok=True)
      log = open(log_path, 'w', encoding='utf-8', errors='replace')
      log.write(' '.join(cmd) + '\n\n')
      log.flush()
      kwargs['stdout'] = log
      kwargs['stderr'] = log
   except OSError:
      log = None                  # logging must never block the download
   p = subprocess.Popen(cmd, **kwargs)
   if log:
      log.close()                 # the child holds its own copy of the handle
   if os.name == 'nt':
      try:
         import psutil
         psutil.Process(p.pid).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
      except Exception:
         pass
   appsettingYT_QuePlayFlagUpdatePID(p.pid)
   time.sleep(1)
   while p.poll() is None:
      time.sleep(1)

   src = os.path.join(start_dir, name)
   dst = filePath + name           # dir string ends with '/'; stored path format unchanged
   try:
      os.makedirs(filePath, exist_ok=True)
      if os.path.exists(src):
         shutil.move(src, dst)
   except OSError:
      pass

   ok = os.path.exists(dst)
   row = [pkey, 3 if ok else 4]
   if tbl == 'tblMusic':
      CRUD_tblMusic(row, 'dnUpdate')
   else:
      CRUD_tblvideomedia(row, 'dnUpdate')
   try:
      play_mp3(os.path.join(start_dir, 'effects',
                            'finished.mp3' if ok else 'failed.mp3'))
   except Exception:
      pass                        # a missing chime must never fail the download


def YTQue_threader():
    n = Value('i', 1)
    a = Array('i', range(10))
    # Parent-liveness sentinel (probed at the bottom of the loop): range(10)
    # leaves a[0]==0, which the Windows OpenProcess check rejects and would
    # exit the worker after one pass. Point it at our own process.
    a[0] = os.getpid()
    YT_QueRun = False
    breaker = 1
    appsettingYT_QuePlayFlagUpdate(0)
    while(breaker == 1):
      YT_QueFlag = appsettingYT_QueFlag()
      time.sleep(2)
      queSwitch = YT_QueFlag[0][2] if YT_QueFlag and YT_QueFlag[0][2] is not None else 0
      if int(queSwitch) == 1:
            fi = select_YT_Que_Next()
            if len(fi) == 0:
               pass
               appsettingYT_QuePlayFlagUpdate(0)
            else:
               YT_QueInfo = appsettingYT_QuePID()
               YT_QuePID = int(YT_QueInfo[0][2]) if YT_QueInfo and YT_QueInfo[0][2] is not None else 0
               # pid_alive replaces os.kill(pid, 0): on Windows signal 0 is
               # CTRL_C_EVENT (not a probe) and "succeeded" for stale PIDs,
               # so the queue thought a download was forever in progress.
               if pid_alive(YT_QuePID):
                  YT_QueRun = False
               else:
                  if YT_QueRun == True:
                     YT_QueRun = False
                     row = [fi[0][0],2]
                     if fi[0][5] == "tblMusic":
                        CRUD_tblMusic(row,"dnUpdate")
                     else:
                        CRUD_tblvideomedia(row,"dnUpdate")
                     YT_Exec(fi)
                  YT_QueRun = True
            
      if os.name == "nt":
         # same liveness idiom as player.py/mpvPlayer.py (was a bare pass)
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
            os.kill(a[0], 0)
         except OSError:
               breaker = 0
         else:
               breaker = 1


