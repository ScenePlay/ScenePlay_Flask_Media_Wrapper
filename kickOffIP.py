import subprocess
import os
from threading import Thread
#import _thread
from ipsearch import *

def startPinging():
    #FNULL = open(os.devnull, 'w')
    start_dir = os.path.dirname(os.path.realpath(__file__)) + "/startPing.sh"
    os.system(f"bash {start_dir}")
    #p = subprocess.Popen(['bash',start_dir],shell=False)
    #p = subprocess.call(['python3', 'ipsearch.py'], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    #print(p.pid)
    pass

#if __name__ == '__main__':
    #_thread.start_new_thread(start, ())
#    thread = Thread(target=startPinging)
#    thread.start()
    #main()
