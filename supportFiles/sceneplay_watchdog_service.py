#!/usr/bin/env python3

import requests
import subprocess
import time
import signal
import os

# Configuration
URL = "http://localhost:8086/isAlive"
SCRIPT_PATH = os.path.expanduser("~/Desktop/ScenePlay.sh")
CHECK_INTERVAL = 30  # time in seconds between checks

stored_pid = None
store_watch_manage = 1

def check_service():
    global stored_pid
    global store_watch_manage
    try:
        response = requests.get(URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            watch_manage = data.get("WatchManage")
            is_alive = data.get("isAlive")
            pid = data.get("pid")
            if is_alive == "true":
                stored_pid = pid
                store_watch_manage = watch_manage
                #print(f"Service is alive with PID: {stored_pid} and WatchManage: {store_watch_manage}")
                #print(f"Service is alive with PID: {stored_pid}")
        else:
            if int(store_watch_manage) == 1:
                handle_failure()

    except (requests.RequestException, ValueError):
        if int(store_watch_manage) == 1:
            handle_failure()

def handle_failure():
    global stored_pid
    if stored_pid:
        print(f"Service is down. Killing PID {stored_pid} and restarting... at {time.strftime('%d/%m/%y   %H:%M:%S')}")
        try:
            os.kill(stored_pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"PID {stored_pid} not found, it may have already stopped.")
        stored_pid = None
    start_application()

def start_application():
    print("Starting application...")
    subprocess.Popen(["bash", SCRIPT_PATH])

if __name__ == "__main__":
    time.sleep(60)
    while True:
        check_service()
        time.sleep(CHECK_INTERVAL)