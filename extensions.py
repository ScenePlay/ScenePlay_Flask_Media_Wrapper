from flask_sqlalchemy import SQLAlchemy 
from flask_migrate import Migrate
import os
import alsaaudio
import pulsectl

db = SQLAlchemy()
migrate = Migrate()
database = 'ScenePlay.db'
databaseDir = os.path.dirname(os.path.realpath(__file__)) + '/' + database


def getmixer():

    with pulsectl.Pulse('volume-control') as pulse:
    # Get a list of all output devices (sinks)
        mixers = pulse.sink_list()
    # try:
    #    mixer = alsaaudio.Mixer("Master")
    # except alsaaudio.ALSAAudioError:
    #    try:
    #       mixer = alsaaudio.Mixer("PCM", cardindex=1)
    #    except alsaaudio.ALSAAudioError:
    #         mixer = None
    return mixers

def currentvolume():

    with pulsectl.Pulse('volume-getter') as pulse:
    # 1. Get the name of the device currently acting as "Default"
        server_info = pulse.server_info()
        default_sink_name = server_info.default_sink_name
    
    # 2. Find that specific device (sink)
        sink = pulse.get_sink_by_name(default_sink_name)
    
    # 3. Calculate the volume percentage
    # value_flat gives the volume as a float (0.0 to 1.0)
    volume = round(sink.volume.value_flat * 100)
    
    #print(f"Device: {sink.description}")
    #print(f"Current Volume: {volume}%")
    # try:
    #    mixer = getmixer()
    #    if mixer == None:
    #        volume = 0
    #    else:
    #     volume = mixer.getvolume()[0]
    # except alsaaudio.ALSAAudioError:
    #     volume = 0
    return volume 

def setvolume(volume):
    # print(volume)
    with pulsectl.Pulse('volume-control') as pulse:
        mixers = getmixer()
        for sink in mixers:
            pulse.volume_set_all_chans(sink,volume/100)
    # try:
    #    mixer = getmixer()
    #    mixer.setvolume(volume)
    # except alsaaudio.ALSAAudioError:
    #     pass
    return