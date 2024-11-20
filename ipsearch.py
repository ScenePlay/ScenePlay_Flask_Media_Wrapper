import subprocess  
import os
import psutil
from ippinger import *
import socket
import time
import signal

hosts = []
local_ip = ""
IPBase = ""
start_dir = ""

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect(('192.255.255.255', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def restartComputer():
    start_dir = os.path.dirname(os.path.realpath(__file__))
    subprocess.Popen(['bash',start_dir + "/./restartComputer.sh"],shell=False)
    
def startPinging():
    FNULL = open(os.devnull, 'w')
    subprocess.Popen(['pkill','-9','-f', 'ippinger.py'], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    subprocess.Popen(['pkill','-9','-f', 'iplauncher.sh'], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    subprocess.Popen(['pkill','-9','-f', 'ipping.sh'], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    subprocess.Popen(['pkill','-9','-f', 'ping'], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    local_ip = get_local_ip()
    IPBase = local_ip.split(".")

    for i in range(0,256,16):
        hosts.append(f"{IPBase[0]}.{IPBase[1]}.{IPBase[2]}.{i}")

    start_dir = os.path.dirname(os.path.realpath(__file__))
    #ippinger_dir = start_dir + "/ippinger.py"
    ippinger_dir = "ippinger.py"
    #ippinger_dir = "./ipping.sh"
    iplauncher_dir =  start_dir + "/./iplauncher.sh"
    #iplauncher_dir =  start_dir + "/./ipping.sh"
    
    
    A = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[0]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    B = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[1]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    C = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[2]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    D = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[3]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    E = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[4]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    F = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[5]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    G = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[6]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    H = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[7]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    I = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[8]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    J = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[9]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    K = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[10]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    L = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[11]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    M = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[12]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    N = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[13]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    O = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[14]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    P = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, hosts[15]], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
    
    
    #for ip in hosts:
        #p =  subprocess.Popen(['python3', start_dir, i])
        #p = 
        #p = subprocess.Popen([iplauncher_dir, start_dir, ippinger_dir, ip], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
        #os.system(f"{iplauncher_dir} {start_dir} {ippinger_dir} {ip}")
        #p.wait(timeout=1)   
        # while p.poll() is None:
        #     time.sleep(1)
        #p.kill()

#if __name__ == '__main__':
 #   startPinging()

# isNotDone = True
# while isNotDone:
#     script_name = "/pinger.py"
#     ps_output = subprocess.check_output(["ps", "-ef"])
#     ps_lines = ps_output.decode("utf-8").split("\n")
#     for line in ps_lines:
#         if script_name in line:
#             #print(line)
#             time.sleep(1)
#             break
#     else:
#         isNotDone = False
        
#x = input("Press Any key to exit")


