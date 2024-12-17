import sqlite3
import subprocess
import os
from glob import glob
import time
from datetime import datetime, timedelta
import logging
import unicodedata
from unittest import case
from extensions import *
from collections import defaultdict

#logging.basicConfig(filename='myapp.log', level=logging.DEBUG, format='%(asctime)s %(levelname)s %(name)s %(message)s')
#logger=logging.getLogger(__name__)

database = databaseDir

def create_table():
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    # c.execute("drop table tblscenes")
    c.execute("CREATE TABLE IF NOT EXISTS lutGenre (  genre_id INTEGER PRIMARY KEY AUTOINCREMENT,  genre TEXT,  directory TEXT,  active INT,  orderBY INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblAppSettings (  ID INTEGER PRIMARY KEY AUTOINCREMENT,  name TEXT,  value TEXT,  typevalue TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblCampaigns  (  campaign_id INTEGER NOT NULL PRIMARY KEY,  campaign_name TEXT,  active INT,  order_by TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblGlobalVar (  globalVar_id INTEGER PRIMARY KEY AUTOINCREMENT,  varName TEXT,  varType TEXT,  varValue TEXT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblHours (  hours_id INTEGER PRIMARY KEY AUTOINCREMENT,  startDTTM TEXT,  endDTTM TEXT,  startTime TEXT,  endTime TEXT,  gmt INT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLED (  led_ID INTEGER PRIMARY KEY AUTOINCREMENT,  ledJSON TEXT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLEDConfig (  ledConfig_ID INTEGER PRIMARY KEY AUTOINCREMENT,  pin INT,  ledCount INT,  active INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblLEDTypeModel (  ledTypeModel_ID INTEGER PRIMARY KEY AUTOINCREMENT,  modelName TEXT,  ledJSON TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblMusic (  song_id INTEGER PRIMARY KEY AUTOINCREMENT,  path TEXT,  song TEXT,  pTimes INT,  playedDTTM TEXT,  active INT,  genre INT,  que INT,  urlSource TEXT,  dnLoadStatus INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblMusicScene (  musicScene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  song_ID INT,  orderBy INT,  volume INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblScenePattern (  scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  ledTypeModel_ID INT,  color TEXT,  wait_ms INT,  iterations INT,  direction INT,  cdiff TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblScenes (  scene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  sceneName TEXT,  active INT,  orderBy INT,  campaign_id INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblServerRole (  ID INTEGER PRIMARY KEY AUTOINCREMENT,  name TEXT,  active INT,  orderBy INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblServersIP (  ServerIP_ID INTEGER PRIMARY KEY AUTOINCREMENT,  serverName TEXT,  ipAddress TEXT,  ports TEXT,  active INT,  PingTime TEXT,  serverroleid INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblVideoMedia (  video_ID INTEGER PRIMARY KEY AUTOINCREMENT,  path TEXT,  title TEXT,  pTimes INT,  playedDTTM TEXT,  active INT,  genre INT,  que INT,  urlSource TEXT,  dnLoadStatus INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblVideoScene (  videoScene_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT,  video_ID INT,  DisplayScreen_ID INT,  orderBy INT,  volume INT, loops INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblwledPattern (  wledPattern_ID INTEGER PRIMARY KEY AUTOINCREMENT,  scene_ID INT, server_ID INT,  effect INT,  pallette INT,  color1 TEXT,  color2 TEXT,  color3 TEXT,  speed INT,  brightness INT,  orderBy INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tbleffect (  effect_ID INTEGER PRIMARY KEY AUTOINCREMENT,  effectName TEXT, ef_ID INT)")
    c.execute("CREATE TABLE IF NOT EXISTS tblpallette (  pallette_ID INTEGER PRIMARY KEY AUTOINCREMENT,  palletteName TEXT, pa_ID INT)")
    c.execute("CREATE TABLE IF NOT EXISTS lutStatus (pkey INTEGER PRIMARY KEY AUTOINCREMENT,  status_ID INT,  status TEXT)")
    conn.commit()
    c.close()




def getLEDOutPIN():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM tblLEDConfig where active = 1")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def appsettings(apparray):
    CRUD_tblAppSettings(apparray,"DA")
    for a in apparray:
        CRUD_tblAppSettings(a,"C")
    pass

def appsettingYT_QuePlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'yt_que_PID'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def appsettingYT_QuePlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'yt_que_switch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingYT_QueFlag():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'yt_que_switch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def select_YT_Que_Next():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("Select * from ( \
                                Select song_id as pkey,path, song as title, urlSource,substr(song,INSTR(song,'.')+1,LENGTH(song)) as media , 'tblMusic' as tbl \
                                    from tblMusic where urlSource not null and dnLoadStatus=1 \
                             union \
                                Select video_ID as pkey, path, title, urlSource,substr( title , INSTR(title,'.')+1 , LENGTH(title)) as media , 'tblVideoMedia' as tbl \
                                    from tblVideoMedia where urlSource not null and dnLoadStatus=1 \
                             ) Order By RANDOM(), pkey ASC LIMIT 1;") 
      
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data




def appsettingVideoPlayFlag():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playvideoswitch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingYT_QuePID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'yt_que_PID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data


def appsettingGetCampaignSelected():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("select value from tblAppSettings where name = 'ShowCampaign'")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data


def appsettingGetCampaignSelected():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("select value from tblAppSettings where name = 'ShowCampaign'")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingGetSceneFilter():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("select value from tblAppSettings where name = 'SceneFilter'")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def appsettingSetSceneFilter(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'SceneFilter'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def appsettingGetNotCampaignSelected():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Select campaign_id from tblCampaigns where campaign_id not in (select value from tblAppSettings where name = 'ShowCampaign')")
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data




def CRUD_tblCampaigns(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _campaign_name = row[0]  
        _active = row[1]
        _order_by = row[2]
        c.execute("Insert INTO tblCampaigns(campaign_name, active,order_by) VALUES (?, ?, ?)",(_campaign_name, _active, _order_by))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblCampaigns where campaign_id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _campaign_name = row[1]  
        _active = row[2]
        _order_by = row[3]
        c.execute("Update tblCampaigns set campaign_name = ?, active = ?, order_by = ? where campaign_id = ?",(_campaign_name, _active, _order_by, _id)) 
        conn.commit()
        return _id
    elif CRUD == "D":
        _id = row[0]
        c.execute("Delete from tblCampaigns where campaign_id = ?", (_id,))
        conn.commit()
        return _id
    elif CRUD == "Selected":
        c.execute("select c.campaign_id, c.campaign_name from tblCampaigns c where c.active = 1 order by c.order_by")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()    

def appsettingSetCampaignSelected(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'ShowCampaign'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    



def appsettingAudioPlayFlag():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playsongswitch'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingAudioPlayPID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playsongPID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingVideoPlayPID():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblAppSettings where name =  'playvideoPID'")    
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    return data

def appsettingVideoPlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playvideoswitch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingVideoPlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playvideoPID'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingAudioPlayFlagUpdate(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playsongswitch'",(val,))    
    conn.commit()
    c.close()
    conn.close()
    
def appsettingAudioPlayFlagUpdatePID(val):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("Update tblAppSettings set value = ?  where name =  'playsongPID'",(val,))    
    conn.commit()
    c.close()
    conn.close()

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
def combine_rows(rows):
    combined_row = {}
    for row in rows:
        for key, value in row.items():
            # If value is None and the key exists in combined_row, skip
            # Otherwise, update the combined_row with non-null value
            if combined_row.get(key) is None and value is not None:
                combined_row[key] = value
            elif key not in combined_row:
                combined_row[key] = value
    return combined_row



def get_Scenes():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    
    
    camppaignids = "("
    testCampaignID = appsettingGetCampaignSelected()
    if int(testCampaignID[0][0]) != 0:
        campaignsNotSelected = appsettingGetNotCampaignSelected()
        if len(campaignsNotSelected) != 0:
            for row in campaignsNotSelected:
                camppaignids = camppaignids + str(row[0]) + ","
            camppaignids = camppaignids[:-1] + ")"
    else:
        camppaignids = camppaignids + "0)"
    #print(camppaignids)
    c = conn.cursor()
    
    c.row_factory = dict_factory
    
    c.execute("select s.scene_ID, substr(s.sceneName,0,16) AS sceneName, dt.scenePattern_ID,  dt.color, UPPER(substr(dt.modelName,0,16)) as modelName , dt.wledPattern_ID,  dt.color1, UPPER(substr(dt.effectName,0,16)) as effectName,  dt.musicScene_ID,  dt.videoScene_ID, s.orderby from ( \
                    select sp.scene_ID , sp.scenePattern_ID, substr(sp.color, 2, LENGTH(sp.color)-2) as color, l.modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, NULL as musicScene_ID, NULL as videoScene_ID  from tblScenePattern sp \
                        join tblLEDTypeModel l on SP.ledTypeModel_ID = l.ledTYpeMOdel_ID where sp.scene_ID <> 0 \
                union \
                    select  wl.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, wl.wledPattern_ID, substr(wl.color1, 2, LENGTH(wl.color1)-2) as color1, case when instr(effectName, '@') = 0 THEN effectName ELSE substr(effectName,1, instr(effectName, '@')-1) END  as effectName, NULL as musicScene_ID, NULL as videoScene_ID from tblwledPattern wl \
                        join tblEffect e on e.ef_ID = wl.effect where wl.scene_ID <> 0 \
                union \
                    select  ms.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, ms.musicScene_ID, NULL as videoScene_ID from tblMusicScene ms where ms.scene_ID <> 0 \
                union \
                    select vs.scene_ID, NULL as scenePattern_ID,null as color, NULL as modelName, NULL as wledPattern_ID, null as color1, NULL as effectName, NULL as musicScene_ID, vs.videoScene_ID from tblvideoScene vs where vs.scene_ID <> 0 ) dt \
                    join tblScenes s on s.scene_ID = dt.scene_ID where s.campaign_id NOT IN "+str(camppaignids)+ " and s.active = 1 order by s.orderby,dt.color desc,dt.modelName desc,dt.color1 desc,dt.effectName desc;")


    dataPre = c.fetchall()
    #print(dataPre)
    grouped_data = defaultdict(list)
    for row in dataPre:
        grouped_data[row['scene_ID']].append(row)
    data = [combine_rows(rows) for rows in grouped_data.values()]
    
    conn.commit()
    c.close()
    conn.close()
    #for r in data:
    #   row = r
    
    return data

def getAllIPAddressFromtblServersIP(ips):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    unix = time.time()
    c.execute("SELECT * FROM tblServersIP where ipAddress =  ?",(str(ips),))
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def CRUD_tblvideomedia(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C": 
        _path = str(row[0])
        _title = row[1]
        _pTimes = row[2]
        _playedDTTM = row[3]
        _active = row[4]
        _genre = row[5]
        _que = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("Insert INTO tblVideoMedia(path, title, pTimes, playedDTTM, active, genre, que,urlSource, dnLoadStatus) VALUES (?, ?, ?, ?, ?, ?, ?,?, ?)",( _path, _title, _pTimes, _playedDTTM, _active, _genre,_que, _urlSource, _dnLoadStatus))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblVideoMedia where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _path= row[1]
        _title = row[2]
        _pTimes = row[3]
        _playedDTTM = row[4]
        _active = row[5]
        _genre = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("UPDATE tblVideoMedia SET path = ?, title = ?, pTimes = ?, playedDTTM = ?, active = ?, genre = ?, urlSource = ?, dnLoadStatus = ?  where video_id = ?" ,( _path,_title, _pTimes, _playedDTTM, _active, _genre, _urlSource, _dnLoadStatus,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        #print("id",_id)
        c.execute("Delete From tblVideoMedia where video_id = ?", (_id,))
        conn.commit()
    elif CRUD == "dnUpdate":
        _id = row[0]
        _dnLoadStatus = row[1]
        c.execute("UPDATE tblVideoMedia SET dnLoadStatus = ?  where video_id = ?" ,( _dnLoadStatus,  _id))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblVideoMedia order by title")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblMusicScene(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C": 
        _scene_ID = row[0]
        _song_ID = row[1]
        _orderBy = row[2]
        _volume = row[3]
        c.execute("Insert INTO tblmusicScene(scene_ID, song_ID, orderBy, volume) VALUES (?, ?, ?, ?)",( _scene_ID, _song_ID, _orderBy, _volume))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _musicScene_ID = row[0]
        c.execute("SELECT * FROM tblmusicScene where id = ?", (_musicScene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _musicScene_ID = row[0]
        _scene_ID= row[1]
        _song_ID = row[2]
        _orderBy = row[3]
        _volume = row[4]
        c.execute("UPDATE tblmusicScene SET  scene_ID = ?, song_ID = ?,  orderBy = ?, volume = ?  where musicScene_id = ?" ,( _scene_ID,_song_ID, _orderBy, _volume,  _musicScene_ID))
        conn.commit()
    elif CRUD == "D":
        _musicScene_ID = row[0]
        #print("id",_musicScene_ID)
        c.execute("Delete From tblmusicScene where musicScene_ID = ?", (_musicScene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblmusicScene")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()


def CRUD_tblMusic(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C": 
        _path = str(row[0])
        _song = row[1]
        _pTimes = row[2]
        _playedDTTM = row[3]
        _active = row[4]
        _genre = row[5]
        _que = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("Insert INTO tblmusic(path, song, pTimes, playedDTTM, active, genre, que,urlSource, dnLoadStatus) VALUES (?, ?, ?, ?, ?, ?, ?,?, ?)",( _path, _song, _pTimes, _playedDTTM, _active, _genre,_que, _urlSource, _dnLoadStatus))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblmusic where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _path= row[1]
        _song = row[2]
        _pTimes = row[3]
        _playedDTTM = row[4]
        _active = row[5]
        _genre = row[6]
        _urlSource = row[7]
        _dnLoadStatus = row[8]
        c.execute("UPDATE tblmusic SET   path = ?, song = ?, pTimes = ?, playedDTTM = ?, active = ?, genre = ?, urlSource = ?, dnLoadStatus = ?  where song_id = ?" ,( _path,_song, _pTimes, _playedDTTM, _active, _genre, _urlSource, _dnLoadStatus,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        #print("id",_id)
        c.execute("Delete From tblmusic where song_id = ?", (_id,))
        conn.commit()
    elif CRUD == "dnUpdate":
        _id = row[0]
        _dnLoadStatus = row[1]
        c.execute("UPDATE tblmusic SET  dnLoadStatus = ?  where song_id = ?" ,( _dnLoadStatus,  _id))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblmusic ORDER BY song")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblAppSettings(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _name = row[0]  
        _value = str(row[1])
        _typevalue = row[2]
        c.execute("Insert INTO tblAppSettings(name, value, typevalue) VALUES (?, ?, ?)",(_name, _value, _typevalue))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _id = row[0]
        c.execute("SELECT * FROM tblAppSettings where id = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _id = row[0]
        _name = row[1]
        _value= row[2]
        _typevalue = row[3]
        c.execute("UPDATE tblAppSettings SET  name = ?, value= ?, typevalue = ?  where id = ?" ,( _name, _value,_typevalue,  _id))
        conn.commit()
    elif CRUD == "D":
        _id = row[0]
        c.execute("Delete From tblAppSettings where id = ?", (_id,))
        conn.commit()
    elif CRUD == "DA":
        _id = row[0]
        c.execute("Delete From tblAppSettings")
        conn.commit()
    elif CRUD == "byName":
        _id = row[0]
        c.execute("select * From tblAppSettings where name = ?", (_id,))
        data = c.fetchall()
        conn.commit()
        return data
    else:
        c.execute("SELECT * FROM tblAppSettings")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblServerRole(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _name = row[0] 
        _active = row[1]
        _orderBy = row[2]
        c.execute("Insert INTO tblServerRole(name, active, orderBy) VALUES (?, ?, ?)",(_name, _active, _orderBy))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ID = row[0]
        c.execute("SELECT * FROM tblServerRole where ID = ?", (_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ID = row[0]
        _name = row[1]
        _active = row[2]
        _orderBy = row[3]
        c.execute("UPDATE tblServerRole SET  name = ?,  active = ?, orderBy = ?  where ID = ?" ,( _name, _active, _orderBy, _ID))
        conn.commit()
    elif CRUD == "D":
        _ID = row[0]
        c.execute("Delete From tblServerRole where ID = ?", (_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblServerRole")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblServersIP(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _serverName = row[0] 
        _ipAddress= row[1]
        _ports = row[2]
        _active = row[3]
        _pingTime = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _serverroleid = row[4]
        c.execute("Insert INTO tblServersIP(serverName, ipAddress, ports, active, pingTime, serverroleid) VALUES (?, ?, ?,?,?,?)",(_serverName, _ipAddress, _ports, _active,_pingTime,_serverroleid))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ServerIP_ID = row[0]
        c.execute("SELECT * FROM tblServersIP where ServerIP_ID = ?", (_ServerIP_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ServerIP_ID = row[0]
        _serverName = row[1]
        _ipAddress= row[2]
        _ports = row[3]
        _active = row[4]
        _pingTime = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _serverroleid = row[5]
        c.execute("UPDATE tblServersIP SET  serverName = ?, ipAddress= ?, ports = ?, active = ?, pingTime = ?, serverroleid = ?  where ServerIP_ID = ?" ,( _serverName, _ipAddress, _ports, _active, _pingTime, _serverroleid,  _ServerIP_ID))
        conn.commit()
    elif CRUD == "D":
        _ServerIP_ID = row[0]
        c.execute("Delete From tblServersIP where ServerIP_ID = ?", (_ServerIP_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblServersIP")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()
    


def CRUD_tblScenes(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _sceneName = row[0] 
        _active = row[1]
        _orderBY = row[2]
        _campaign_ID = row[3]
        c.execute("Insert INTO tblScenes(sceneName, active, orderBy, campaign_id) VALUES (?, ?, ?,?)",(_sceneName, _active, _orderBY,_campaign_ID))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _Scene_ID = row[0]
        c.execute("SELECT * FROM tblScenes where Scene_ID = ?", (_Scene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _Scene_ID = row[0]
        _sceneName = row[1]
        _active = row[2]
        _orderBY = row[3]
        _campaign_ID = row[4]
        c.execute("UPDATE tblScenes SET  sceneName = ?, active = ?, orderBY = ?, campaign_id = ? where scene_ID = ?" ,( _sceneName, _active, _orderBY,_campaign_ID, _Scene_ID))
        conn.commit()
    elif CRUD == "D":
        _Scene_ID = row[0]
        c.execute("Delete From tblScenes where Scene_ID = ?", (_Scene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblScenes")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblScenePattern(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0] 
        _ledTypeModel_ID = row[1]
        _color = row[2]
        _wait_ms = row[3]
        _iterations = row[4]
        _direction = row[5]
        _cdiff = row[6]
        c.execute("Insert INTO tblScenePattern(scene_ID, ledTypeModel_ID, color, wait_ms, iterations, direction, cdiff) VALUES (?, ?, ?, ?, ?, ?, ?)",(_scene_ID, _ledTypeModel_ID, _color, _wait_ms, _iterations, _direction, _cdiff))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _ScenePattern_ID = row[0]
        c.execute("SELECT * FROM tblScenePattern where ScenePattern_ID = ?", (_ScenePattern_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "bySceneID":
        _Scene_ID = row[0]
        c.execute("SELECT * FROM tblScenePattern where Scene_ID = ?", (_Scene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _ScenePattern_ID = row[0]
        _Scene_ID = row[1]
        _ledTypeModel_ID = row[2]
        _color = row[3]
        _wait_ms = row[4]
        _iterations = row[5]
        _direction = row[6]
        _cdiff = row[7]
        c.execute("UPDATE tblScenePattern SET Scene_ID = ?, ledTypeModel_ID = ?, color = ?, wait_ms = ?, iterations = ?, direction = ?, cdiff = ? where ScenePattern_id = ?",(_Scene_ID,  _ledTypeModel_ID,  _color, _wait_ms, _iterations, _direction, _cdiff, _ScenePattern_ID))
        conn.commit()
    elif CRUD == "D":
        _ScenePattern_ID = row[0]
        c.execute("Delete From tblScenePattern where ScenePattern_ID = ?", (_ScenePattern_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblScenePattern")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblLEDTypeModel(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _modelName = row[0] 
        _ledJSON = row[1]
        c.execute("Insert INTO tblLEDTypeModel(modelName, ledJSON) VALUES (?, ?)",(_modelName, _ledJSON))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _LEDTypeModel_ID = row[0]
        c.execute("SELECT * FROM tblLEDTypeModel where LEDTypeModel_ID = ?", (_LEDTypeModel_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _LEDTypeModel_ID = row[0] 
        _modelName = row[1]
        _ledJSON = row[2]
        c.execute("UPDATE tblLEDTypeModel SET modelName = ?, ledJSON = ? where LEDTypeModel_id = ?",(_modelName,  _ledJSON,  _LEDTypeModel_ID))
        conn.commit()
    elif CRUD == "D":
        _LEDTypeModel_ID = row[0]
        c.execute("Delete From tblLEDTypeModel where LEDTypeModel_ID = ?", (_LEDTypeModel_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblLEDTypeModel")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblMusicScene(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0] 
        _song_ID = row[1]
        _orderBy = row[2]
        _volume = row[3]
        c.execute("Insert INTO tblMusicScene(scene_ID, song_ID, orderBy,volume) VALUES (?, ?, ?, ?)",(_scene_ID, _song_ID, _orderBy, _volume))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _MusicScene_ID = row[0]
        c.execute("SELECT * FROM tblMusicScene where MusicScene_ID = ?", (_MusicScene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _MusicScene_ID = row[0] 
        _scene_ID = row[1]
        _song_ID = row[2]
        _orderBy = row[3]
        c.execute("UPDATE tblMusicScene SET scene_ID = ?, song_ID = ?,  orderBy = ? where MusicScene_id = ?",(_scene_ID,  _song_ID,  _orderBy, _MusicScene_ID))
        conn.commit()
    elif CRUD == "D":
        _MusicScene_ID = row[0]
        c.execute("Delete From tblMusicScene where MusicScene_ID = ?", (_MusicScene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblMusicScene")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblPixel(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _pin = row[0] 
        _ledCount = row[1]
        c.execute("Insert INTO tblPixel(pin, ledCount) VALUES (?, ?)",(_pin, _ledCount))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _pixel_ID = row[0]
        c.execute("SELECT * FROM tblPixel where pixel_ID = ?", (_pixel_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _pixel_ID = row[0] 
        _pin = row[1]
        _ledCount = row[2]
        c.execute("UPDATE tblPixel SET pin = ?, ledCount = ? where pixel_id = ?",(_pin,  _ledCount, _pixel_ID))
        conn.commit()
    elif CRUD == "D":
        pixel_ID = row[0]
        c.execute("Delete From tblPixel where pixel_ID = ?", (pixel_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblPixel")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def CRUD_tblVideoScene(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _scene_ID = row[0] 
        _video_ID = row[1]
        _DisplayScreen_ID = row[2]
        _orderBy = row[3]
        _volume = row[4]
        _loops = row[5]
        c.execute("Insert INTO tblVideoScene(scene_ID, video_ID, DisplayScreen_ID, orderBy,volume, loops) VALUES (?, ?, ?,?, ?,?)",(_scene_ID, _video_ID,_DisplayScreen_ID, _orderBy, _volume, _loops))
        conn.commit()
        return c.lastrowid
    elif CRUD == "R":
        _VideoScene_ID = row[0]
        c.execute("SELECT * FROM tblVideoScene where VideoScene_ID = ?", (_VideoScene_ID,))
        data = c.fetchall()
        conn.commit()
        return data
    elif CRUD == "U":
        _VideoScene_ID = row[0] 
        _scene_ID = row[1]
        _video_ID = row[2]
        _DisplayScreen_ID = row[3]
        _orderBy = row[4]
        _volume = row[5]
        c.execute("UPDATE tblVideoScene SET scene_ID = ?, video_ID = ?, DisplayScreen_ID = ?, orderBy = ?, volume = ?, loops = ? where VideoScene_id = ?",(_scene_ID,  _video_ID, _DisplayScreen_ID, _orderBy, _volume, _loops, _VideoScene_ID))
        conn.commit()
    elif CRUD == "D":
        VideoScene_ID = row[0]
        c.execute("Delete From tblVideoScene where VideoScene_ID = ?", (VideoScene_ID,))
        conn.commit()
    else:
        c.execute("SELECT * FROM tblVideoScene")
        data = c.fetchall()
        conn.commit()
        return data
    c.close()
    conn.close()

def loadDefaults():
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    #c.execute("insert into tblMusicScene(scene_ID,song_ID,orderBy)values(1,6,1)")
    #c.execute("insert into tblMusicScene(scene_ID,song_ID,orderBy)values(1,3,2)")
    #c.execute("insert into tblScenePattern (scene_ID,ledTypeModel_ID,Color,wait_ms,interations ,direction) values (1,1,'[0,0,0]',10,100,1)")
    #c.execute("insert into tblScene (scenesName,orderby) values ('Sparkle',1)")
    #c.execute("insert into tblLEDTypeModel(modelName, ledJSON) values ('sparkle','{\"type\": \"sparkle\", \"color\": [0,0,0], \"wait_ms\": 8,\"cdiff\": [0,0,0],\"iterations\": 1000000}')")
    #c.execute("insert into tblPixel (pin,ledCount) values (26,86)")
    #c.execute("insert into tblVideoScene (scene_id,Video_ID,DisplayScreen_ID) values (1,1,1)")
    conn.commit()
    c.close()
    conn.close()

def get_SceneID(_scenePattern_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT scene_ID FROM tblScenePattern where scenePattern_ID = ?", (_scenePattern_ID,))
    data = c.fetchall()
    conn.commit()
    c.close()
    conn.close()
    return data

def get_VideoScene_BYSceneID(_scene_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblVideoScene where scene_ID = ?", (_scene_ID,))
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    return data

def get_MusicSceneSongs_BYSceneID(_scene_ID):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblMusicScene where scene_ID = ?", (_scene_ID,))
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    return data

def get_LEDJSON():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT ledJSON FROM tblLED")
    data = c.fetchall()
    c.execute("DELETE FROM tblLED")
    conn.commit()
    c.close()
    conn.close()
    for r in data:
        row = r[0]
    return row

def insert_LEDJSON(json):
    conn = sqlite3.connect(database)
    conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("INSERT INTO tblLED (ledJSON) VALUES (?)",[json])
    conn.commit()
    
# def insert_LEDJSON(json):
#     conn = sqlite3.connect(database)
#     conn.text_factory = lambda x: unicodedata(x, 'utf-8', 'ignore')
#     c = conn.cursor()
#     c.execute("INSERT INTO tblLED (ledJSON) VALUES (?)",[json])
#     conn.commit()

def update_video_data_entry(row):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    _video_id = row[0]
    _playedDTTM = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
    _pTimes = row[4]
    _pTimes = _pTimes + 1
    _active = row[5]
    _que = 0
    c.execute("UPDATE tblvideomedia SET pTimes = ?, playedDTTM = ?, active = ?, que = ? where video_ID = ?",(_pTimes, _playedDTTM, _active,  _que, _video_id))
    conn.commit()
    c.close()
    conn.close()
    
def update_data_entry(row):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    _song_id = row[0]
    _playedDTTM = str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
    _pTimes = row[4]
    _pTimes = _pTimes + 1
    _active = row[5]
    _que = 0
    c.execute("UPDATE tblMusic SET pTimes = ?, playedDTTM = ?, active = ?, que = ? where song_ID = ?",(_pTimes, _playedDTTM, _active,  _que, _song_id))
    conn.commit()
    c.close()
    conn.close()

def CRUD_tblHours(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _startDTTM = row[1] #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _endDTTM = row[2]   #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _gmt = row[3]
        _active = row[4]
        c.execute("Insert INTO tblHours(startDTTM, endDTTM, gmt, active) VALUES(?, ?, ?, ?)",(_startDTTM, _endDTTM, _gmt, _active))
        conn.commit()
    elif CRUD == "R":
        _hours_id = row(0)
        c.execute("SELECT hours_id, startDTTM, endDTTM, gmt, active FROM tblHours where hours_id = ?", (_hours_id))
        conn.commit()
    elif CRUD == "U":
        _hours_id = row[0]
        _startDTTM = row[1] #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _endDTTM = row[2]   #str(datetime.fromtimestamp(unix).strftime('%Y-%m-%d %H:%M:%S'))
        _gmt = row[3]
        _active = row[4]
        c.execute("UPDATE tblHours SET startDTTM = ?, endDTTM = ?, gmt = ?, active = ? where hours_id = ?",(_startDTTM, _endDTTM, _gmt,  _active, _hours_id))
        conn.commit()
    elif CRUD == "D":
        _hours_id = row(0)
        c.execute("Delete From tblHours where hours_id = ?", (_hours_id))
        conn.commit()
    else:
        c.execute("SELECT hours_id, startDTTM, endDTTM, gmt, active FROM tblHours")
        conn.commit()
    c.close()
    conn.close()

def CRUD_tblGlobalVars(row,CRUD):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    unix = time.time()
    if CRUD == "C":
        _varName = row[1] 
        _varType = row[2]
        _varValue = row[3]
        _active = row[4]
        c.execute("Insert INTO tblGlobalVar(varName, varType, varValue, active)) VALUES(?, ?, ?, ?)",(_varName, _varType, _varValue, _active))
        conn.commit()
    elif CRUD == "R":
        _globalVar_id = row(0)
        c.execute("SELECT globalVar_id, varName, varType, varValue, active FROM tblGlobalVar where globalVar_id = ?", (_globalVar_id))
        conn.commit()
    elif CRUD == "U":
        _varName = row[1] 
        _varType = row[2]
        _varValue = row[3]
        _active = row[4]
        c.execute("UPDATE tblGlobalVar SET varName = ?, varType = ?, varValue = ?, active = ? where _globalVar_id = ?",(_varName, _varType, _varValue,  _active, _globalVar_id))
        conn.commit()
    elif CRUD == "D":
        globalVar_id = row(0)
        c.execute("Delete From tblGlobalVar where _globalVar_id = ?", (globalVar_id))
        conn.commit()
    else:
        c.execute("SELECT globalVar_id, varName, varType, varValue, active FROM tblGlobalVar")
        conn.commit()
    c.close()
    conn.close()

def select_play():
    blnEnd = 0
    while (blnEnd == 0):
        conn = sqlite3.connect(database)
        #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
        c = conn.cursor()
        c.execute("SELECT song_ID, (path || song),path,song,pTimes,active,que FROM tblMusic where que = 1") #ORDER BY RANDOM() ")
        data = c.fetchall()
        c.close()
        conn.close()
        for row in data:
           #print(row[3])
           play_mp3(row[1])
           update_data_entry(row)
        blnEnd = 1 

def add_songID_Queue(_song_ID):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 1 where song_id = ?",(_song_ID,))
    conn.commit()
    c.close()
    conn.close()


def update_play_queue(_fn):
    songCount = 0
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 1 where path like '%" + _fn + "%' or song like '%" + _fn + "%'")
    conn.commit()
    data = c.execute("SELECT count(*) FROM tblMusic where que = 1")
    for row in data:
        songCount = row[0]
    c.close()
    conn.close()
    return songCount

def update_video_queue_selected(_selected):
    videoCount = 0
    conn = sqlite3.connect(database)
    #print(_selected)
    c = conn.cursor()
    if len(_selected) > 0:
        for i in _selected:
            c.execute("UPDATE tblvideomedia SET que = 1 where dnLoadStatus = 3 and video_ID = " + str(i))
            conn.commit()
    data = c.execute("SELECT count(*) FROM tblvideomedia where que = 1")
    for row in data:
        videoCount = row[0]
    c.close()
    conn.close()
    return videoCount

def update_play_queue_selected(_selected):
    songCount = 0
    conn = sqlite3.connect(database)
    #print(_selected)
    c = conn.cursor()
    if len(_selected) > 0:
        for i in _selected:
            c.execute("UPDATE tblMusic SET  que = 1 where dnLoadStatus = 3 and song_id = " + str(i))
            conn.commit()
    data = c.execute("SELECT count(*) FROM tblMusic where que = 1")
    for row in data:
        songCount = row[0]
    c.close()
    conn.close()
    return songCount

def select_play_queue():
    blnEnd = 0
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    while (blnEnd == 0):
        c.execute("SELECT song_ID, (path || song),path,song,pTimes,active,que FROM tblMusic WHERE que <> 0 ORDER BY RANDOM(), ROWID ASC LIMIT 1")
        data = c.fetchall()
        if len(data) == 0:
            blnEnd = 1
        else:    
            for row in data:
               #print(row[3])
               play_mp3(row[1])
               update_data_entry(row)
    c.close()
    conn.close()

def select_play_threadQ():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    #c.execute("SELECT song_ID, (path || song),path,song,pTimes,active,que FROM tblMusic WHERE que <> 0 ORDER BY RANDOM(), ROWID ASC LIMIT 1")
    c.execute("SELECT m.song_ID, (m.path || m.song),m.path,m.song,m.pTimes,m.active,m.que, ms.volume FROM tblMusic m join tblMusicScene ms on m.song_ID = ms.song_ID WHERE m.que <> 0 and m.dnLoadStatus = 3 ORDER BY ms.orderby,RANDOM(), m.ROWID ASC LIMIT 1")
    data = c.fetchall()
    c.close()
    conn.close()    
    for row in data:
        #update_data_entry(row)
        return row
    return ""

def select_video_threadQ():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT vm.video_ID, (vm.path || vm.title),vm.path,vm.title,vm.pTimes,vm.active,vm.que, vs.displayScreen_ID, vs.volume, vs.loops FROM tblVideoMedia vm join tblVideoScene vs on vm.video_ID = vs.video_ID where vm.que <> 0  and vm.dnLoadStatus = 3 ORDER BY VS.orderby, RANDOM(), vm.ROWID ASC LIMIT 1;")
    data = c.fetchall()
    #print(f"Video {data}")
    c.close()
    conn.close()    
    for row in data:
        #update_data_entry(row)
        return row
    return ""

def queue_off():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 0 where que = 1")
    conn.commit()
    c.execute("UPDATE tblVideoMedia SET  que = 0 where que = 1")
    conn.commit()
    c.close()
    conn.close()

def queue_kill():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("UPDATE tblMusic SET  que = 0 where que = 1")
    conn.commit()
    c.execute("UPDATE tblVideoMedia SET  que = 0 where que = 1")
    conn.commit()
    if os.name == "nt":
       #os.system("taskkill /f /im ffplay.exe")
       os.system("taskkill /f /im cmdmp3win.exe")
    else:
       os.system("pkill mpg123")
       os.system("pkill mpv")
    c.close()
    conn.close()
    
def queue_next(): 
    if os.name == "nt":
       #os.system("taskkill /f /im ffplay.exe")
       os.system("taskkill /f /im cmdmp3win.exe")
    else:
       os.system("pkill mpg123")
def queueVideo_next(): 
    if os.name == "nt":
       #os.system("taskkill /f /im ffplay.exe")
       os.system("taskkill /f /im cmdmp3win.exe")
    else:
       os.system("pkill mpv")

def select_data_all():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT * FROM tblMusic")
    data = c.fetchall()
    for row in data:
       print(row[0], row[1],row[2],row[3])
    c.close()
    conn.close()
    
def delete_all(_tableName):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("DELETE FROM " + _tableName)
    conn.commit()
    c.close()
    conn.close()

def delete_songs(_selected):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    for i in _selected:
        c.execute("SELECT (path || song) FROM tblMusic where song_id = " + str(i))
        data = c.fetchall()
        for row in data:
            os.remove(row[0])
    for i in _selected:
        c.execute("Delete from tblMusic where song_id = " + str(i))
        conn.commit()
    c.close()
    conn.close()

def addSongToDB(fi):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    _pTimes = 0
    _playedDTTM = ""
    _active = 1
    _genre = 0
    _que = 1
    _path, _song = os.path.split(fi)
    if os.name == 'nt':
        _path = _path + "\\"
        _path.replace("\\","\\\\",0)
    else:
        _path = _path + "/"
    try:
        c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
        conn.commit()
    except Exception as err:
        #logger.error(err)
        pass
    c.close()
    conn.close()

    
def find_store_files():
    files = []
    fileslocal = []
    start_dir = ""
    if os.name == 'nt':
        start_local  = os.path.dirname(os.path.realpath(__file__))
    else:
        start_dir  = "/media"
        start_local  = os.path.dirname(os.path.realpath(__file__))
    
    pattern   = "*.mp3"
    
    if os.name != 'nt':
        for dir,_,_ in os.walk(start_dir):
            files.extend(glob(os.path.join(dir,pattern)))

    for dir,_,_ in os.walk(start_local):
        fileslocal.extend(glob(os.path.join(dir,pattern)))

    conn = sqlite3.connect(database)
    c = conn.cursor()
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    _pTimes = 0
    _playedDTTM = ""
    _active = 1
    _genre = 0
    _que = 0
    if len(files) > 0:
        for file in files:
            _path, _song = os.path.split(file)
            if os.name == 'nt':
                _path = _path + "\\"
                _path.replace("\\","\\\\",0)
            else:
                _path = _path + "/"
            try:
                c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
                conn.commit()
            except Exception as err:
                #logger.error(err)
                pass
    else:
        for file in fileslocal:
            _path, _song = os.path.split(file)
            if os.name == 'nt':
                _path = _path + "\\"
                _path.replace("\\","\\\\",0)
            else:
                _path = _path + "/"
            try:
                c.execute("INSERT INTO tblMusic(path, song, pTimes, playedDTTM, active, genre, que) VALUES(?, ?, ?, ?, ?, ?, ?)",(_path, _song, _pTimes, _playedDTTM, _active, _genre, _que))
                conn.commit()
            except Exception as err:
                #logger.error(err)
                pass

    c.close()
    conn.close()
    

def play_mp3(fi):
   start_dir = os.path.dirname(os.path.realpath(__file__))
   if os.name == "nt":
      player = start_dir+"\\ffplay.exe"
      player.replace("\\","\\\\",0)
      fi.replace("\\","\\\\",0)
      subprocess.Popen([player, '-autoexit', fi]).wait()
   else:
      subprocess.Popen(['mpg123', '-q', fi]).wait()

def drop_table(_tableName):
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS " + _tableName)
    conn.commit()
    c.close()
    conn.close()
    
def get_table():
    conn = sqlite3.connect(database)
    #conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    data = c.fetchall()
    for row in data:
       print(row)
    c.close()
    conn.close()
    
def select_data_stats():#a):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    # c.execute("SELECT 'Songs Stored' as T, Count(*) as C FROM tblMusic "
            #   + "UNION SELECT 'Songs Queued' as T, Count(*) as C FROM tblMusic where que <> 0 "
             # + "UNION SELECT 'Total Songs Played' as T, SUM(pTimes) as C FROM tblMusic "
             # + "UNION SELECT 'Song Current' as T, song as c FROM tblMusic where song_id = " + str(a[2]) + " "
             # + "UNION SELECT 'Song Last' as T, song as c FROM tblMusic where song_id = " + str(a[3]) + " "
             # + "UNION SELECT 'Song Volume' as T, " + str(a[1]) + " as c"
            #  )
    c.execute( #"SELECT 'Songs Stored' as T, Count(*) as C FROM tblMusic "
              #+ "UNION 
              "SELECT 'Songs Queued' as T, Count(*) as C FROM tblMusic where que <> 0 "
              + "UNION SELECT 'Videos Queued' as T, Count(*) as C FROM tblvideoMedia where que <> 0"
             # + "UNION SELECT 'Total Songs Played' as T, SUM(pTimes) as C FROM tblMusic "
             # + "UNION SELECT 'Song Current' as T, song as c FROM tblMusic where song_id = " + str(a[2]) + " "
             # + "UNION SELECT 'Song Last' as T, song as c FROM tblMusic where song_id = " + str(a[3]) + " "
             # + "UNION SELECT 'Song Volume' as T, " + str(a[1]) + " as c"
             )
    data = c.fetchall()
    c.close()
    conn.close()
    #print(data)
    return data

def select_data_allsongs():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT song_id, (path || song) FROM tblMusic ORDER BY path, song")
    data = c.fetchall()
    c.close()
    conn.close()
    return data


#drop_table('tblMusic')
#create_table()
#delete_all('tblMusic')
#find_store_files()
#queue_kill()
#update_play_queue('')
#select_play_queue()
#select_play()
#get_table()
#select_data_all()
#select_data_stats()
#select_data_allsongs()

 
