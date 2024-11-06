#from sql import *
import os
import subprocess
import time



def play_led_local():
    vl = 0
    s = subprocess.Popen(['sudo', 'pkill','-9','-f', 'led_Run.py'])
    #s = subprocess.Popen(['pkill','-9','-f', 'led_Run.py'])
    while s.poll() is None:
        time.sleep(1/100)

    start_dir = os.path.dirname(os.path.realpath(__file__))
    full_dir = start_dir + "/led_Run.py"
    #p = subprocess.Popen(['python3', full_dir])
    p = subprocess.Popen(['sudo', 'python3', full_dir])
    #while p.poll() is None:
        #print(p.poll())
        #if vl != a[1]:
        #set_volume(a[1])
        #vl = int(a[1])
        #time.sleep(1)


def threaderLED():
    play_led_local()
    #breaker = 1
    #while(breaker == 1): 
            # if n.value == 1:
            #     fi = 'test'#select_led_threadQ()
            #     if len(fi) == 0:
            #         n.value = 0
            #         if a[2] != 0: 
            #            a[3] = a[2]
            #         a[2] = 0
            #     else:
            #         if a[2] != 0:
            #            a[3] = a[2]
            #         a[2] = fi[0]
            #         play_led_local(fi[1], a)
            #         #update_data_entry(fi)
            # elif n.value == 0:
            #     if a[2] != 0: 
            #        a[3] = a[2]
            #     a[2] = 0               
            #     time.sleep(2)
            # try:
            #     os.kill(a[0], 0)
            # except OSError:
            #     breaker = 0
            # else:
            #     breaker = 1

