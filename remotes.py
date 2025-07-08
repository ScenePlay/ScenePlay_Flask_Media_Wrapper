

import requests
import json
from extensions import *

from sql import *
from models.serverIP import tblserversip as IP
from models.serverRole import tblserverrole as Role
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
engine = create_engine('sqlite:///' + databaseDir)
Session = sessionmaker(bind=engine)
session = Session()

def remoteSend(LEDPattern):
    try:
        query = select(IP, Role).where(Role.ID == IP.serverroleid).where(Role.name == 'Remote').where(IP.active == 1)
        remoteIPs = session.execute(query).fetchall()
        for eachIP in remoteIPs:
            ip_address = str(eachIP[0].ipAddress) #eachIP.
            #print(f"Sending Data to Remotes: {ip_address}")
            port = str(8086)
            api_url = f"http://{ip_address}:{port}/receive_led_patterns"
            print(LEDPattern)
            response = requests.post(api_url, json=json.loads(LEDPattern))
        session.close()
    except Exception as err: 
        print(err)
        
def prepJsonRemote(ledMdl, scnPat, isLocal=False) -> str:
    i=0
    ledPattern = f'{{"patterns\": '
    tester = ""
    for row in ledMdl:
        #print(row[2])
        tester = str(row[2])
        t = json.loads(row[2])
        ledPattern = ledPattern + f'[{{\"type\": \"{t["type"]}\"'
        if tester.find("color")>0:
            ledPattern += ', \"color\": ' + str(scnPat[i][3]) 
        if tester.find("wait_ms")>0:
            ledPattern += ', \"wait_ms\": ' + str(scnPat[i][4])
        if tester.find("iterations")>0:
            ledPattern += ', \"iterations\": ' + str(scnPat[i][5])
        if tester.find("direction")>0:
            ledPattern += ', \"direction\": ' + str(scnPat[i][6])
        if tester.find("cdiff")>0:
            ledPattern += ', \"cdiff\": ' + str(scnPat[i][7])
        #allow local settings to activate
        if isLocal:
            ledPattern += ', \"outPinID\": ' + str(scnPat[i][9])
            ledPattern += ', \"brightness\": ' + str(scnPat[i][10])
        i+=1
        if i < len(ledMdl):
            ledPattern += ","
        if tester.find("solid")>0:
            ledPattern += '}]}'
        else:
            ledPattern += '},{"type": "solid", "color": [0,0,0]}]}'
    
    return ledPattern