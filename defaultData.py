from extensions import *

import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.campaigns import tblcampaigns
from models.ledConfig import tblledconfig
from models.ledTypeModel import tblledtypemodel
from models.serverRole import tblserverrole
from models.genre import lutgenre
from models.status import lutstatus

baseDir = os.path.dirname(os.path.realpath(__file__))

#print(data)
# Create a SQLAlchemy engine and session
engine = create_engine('sqlite:///' + databaseDir)
Session = sessionmaker(bind=engine)
session = Session()

def loadStatus():
# Read the JSON file
    with open(baseDir + '/defaultData/lutStatus.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        StatusRow = lutstatus(
            status_ID=item['status_ID'],
            status=item['status']
        )
        session.add(StatusRow)

    # Commit the changes
    session.commit()


def loadCampaigns():
# Read the JSON file
    with open(baseDir + '/defaultData/tblCampaigns.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        campaign = tblcampaigns(
            campaign_name=item['campaign_name'],
            active=item['active'],
            order_by=item['order_by']
        )
        session.add(campaign)

    # Commit the changes
    session.commit()

def loadLedConfig():
# Read the JSON file
    with open(baseDir + '/defaultData/tblLEDConfig.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        ledConfig = tblledconfig(
            pin=item['pin'],
            ledCount=item['ledCount'],
            brightness=item['brightness'],
            active=item['active']
        )
        session.add(ledConfig)

    # Commit the changes
    session.commit()


def loadLedTypeModel():
# Read the JSON file
    with open(baseDir + '/defaultData/tblLEDTypeModel.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        ledTypeModel = tblledtypemodel(
            modelName=item['modelName'],
            ledJSON=item['ledJSON']
        )
        session.add(ledTypeModel)

    # Commit the changes
    session.commit()

def loadServerRole():
# Read the JSON file
    with open(baseDir + '/defaultData/tblServerRole.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        serverRole = tblserverrole(
            name=item['name'],
            active=item['active'],
            orderBy=item['orderBy']
        )
        session.add(serverRole)

    # Commit the changes
    session.commit()

def loadlutGenre():
# Read the JSON file
    with open(baseDir + '/defaultData/lutGenre.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        lutGenre = lutgenre(
            genre=item['genre'],
            directory=item['directory'],
            active=item['active'],
            orderBy=item['orderBY']
        )
        session.add(lutGenre)

    # Commit the changes
    session.commit()

def defaultData():
    query = session.query(tblcampaigns)
    if query.count() == 0:
        loadCampaigns()
        
    query = session.query(tblledconfig)
    if query.count() == 0:
        loadLedConfig()
        
    query = session.query(tblledtypemodel)
    if query.count() == 0:
        loadLedTypeModel()
        
    query = session.query(tblserverrole)    
    if query.count() == 0:
        loadServerRole()
        
    query = session.query(lutgenre)    
    if query.count() == 0:
        loadlutGenre()
        
    query = session.query(lutstatus)    
    if query.count() == 0:
        loadStatus()