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
from models.cronSchedule import tblcronschedule

baseDir = os.path.dirname(os.path.realpath(__file__))

#print(data)
# Create a SQLAlchemy engine and session
engine = create_engine('sqlite:///' + databaseDir)
Session = sessionmaker(bind=engine)
session = Session()

def loadCronSchedules():
# Read the JSON file
    with open(baseDir + '/defaultData/tblCronSchedule.json') as file:
        data = json.load(file)
        
    # Iterate over the JSON data and insert it into the database
    for item in data:
        cronSchedule = tblcronschedule(
            name=item['name'],
            minute=item['minute'],
            hour=item['hour'],
            day_of_month=item['day_of_month'],
            month=item['month'],
            day_of_week=item['day_of_week'],
            command=item['command'],
            description=item['description'],
            active=item['active']
        )
        session.add(cronSchedule)

    # Commit the changes
    session.commit()

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
    """Top-up sync for the RPiLED pattern models: insert any DEFAULT model
    missing from the live table (matched by modelName, case-insensitive).
    Runs EVERY boot — pattern types added in updates reach existing installs
    instead of only fresh databases; rows the user has edited or added are
    never touched. The seed file's entries all carry the FULL field set
    (type, color, cdiff, wait_ms, iterations, direction) so every pattern
    passes the same information to led_Run / remotes / the relay."""
    with open(baseDir + '/defaultData/tblLEDTypeModel.json') as file:
        data = json.load(file)

    existing = {(m.modelName or '').strip().lower()
                for m in session.query(tblledtypemodel).all()}
    added = 0
    for item in data:
        if (item['modelName'] or '').strip().lower() in existing:
            continue
        session.add(tblledtypemodel(
            modelName=item['modelName'],
            ledJSON=item['ledJSON']
        ))
        added += 1
    if added:
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
        
    # No empty-table gate: loadLedTypeModel is a top-up (inserts only models
    # missing by name), so updates deliver new pattern types to old installs.
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
    
    query = session.query(tblcronschedule)    
    if query.count() == 0:
        loadCronSchedules() 