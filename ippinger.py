import subprocess
import signal
import psutil
import os
import sys
import socket
from contextlib import closing
from sql import *
import time

def check_socket(host, port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(1)
        if sock.connect_ex((host, port)) == 0:
            return f", {port}"
        else:
            return ""
        
class pinger:
    def __init__(self, h) -> None:
        self.host = h
        self.pingThing()
        pass

    FNULL = open(os.devnull, 'w')
    def pingThing(self):
        FNULL = open(os.devnull, 'w')
        print(self.host)
        p = subprocess.Popen(['ping', '-c', '1', self.host], stdout=FNULL, stderr=subprocess.STDOUT,shell=False)
        p.wait()
        try:
           hostname = f" {socket.gethostbyaddr(self.host)[0]}"
        except:
            hostname = ""
        
        if not p.poll():
            #ports = f"{check_socket(self.host,22)}{check_socket(self.host,80)}{check_socket(self.host,443)}{check_socket(self.host,8081)}"
            ports = f"{check_socket(self.host,22)}\
{check_socket(self.host,80)}\
{check_socket(self.host,443)}\
{check_socket(self.host,8080)}\
{check_socket(self.host,8081)}\
{check_socket(self.host,8082)}\
{check_socket(self.host,8083)}\
{check_socket(self.host,8084)}\
{check_socket(self.host,8085)}\
{check_socket(self.host,8086)}\
{check_socket(self.host,8087)}\
{check_socket(self.host,8088)}"

            ports = ports.replace(",", "",1)
            print(f"{self.host}{ports}{hostname}", end='\n')
            ipAddresses = getAllIPAddressFromtblServersIP(self.host)
            found = False
            if ipAddresses is not None:
                for x in ipAddresses:
                    if self.host == x[2]:
                        found = True
                        print(f"Found in database {self.host}{ports}{hostname}", end='\n')
                        break
                
            if  ports.find("80") > 0 or ports.find("443") > 0  or ports.find("8081") > 0 or ports.find("8082") > 0 or ports.find("8083") > 0 or ports.find("8084") > 0 or ports.find("8085") > 0 or ports.find("8086") > 0 or ports.find("8087") > 0 or ports.find("8088") > 0 or ports.find("22") > 0:
                if found:
                    row = [ipAddresses[0][0],ipAddresses[0][1], ipAddresses[0][2], ports, ipAddresses[0][4],ipAddresses[0][6]]
                    CRUD_tblServersIP(row, "U")
                else:
                    row = [hostname, self.host, ports, 1, 1]
                    CRUD_tblServersIP(row, "C")
    
    
def main():
    pid = os.getpid()
    p = psutil.Process(pid)
    args = sys.argv[1:]
    IPBase = args[0].split(".")
    N = 64 + int(IPBase[3]) -1
    for i in range(int(IPBase[3]), N):
        if(i>0 and i<255):
            print(f"{str(i)}")
            pinger(f"{IPBase[0]}.{IPBase[1]}.{IPBase[2]}.{str(i)}")
            time.sleep(2)
    
    print(pid)
    p.terminate()
    p.kill()
    os.kill(pid, signal.SIGKILL)

if __name__ == '__main__':
    main()