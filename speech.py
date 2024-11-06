from gtts import gTTS
import os
from datetime import datetime, date, time
from sql import *

def TextToSpeechPlay(_fn):
    tts = gTTS(text=_fn)##, lang='en-uk')
    now = datetime.now()
    SaveDir = os.path.dirname(os.path.realpath(__file__))
    if os.name == 'nt':
        SaveDir = SaveDir + "\\tts\\" + now.strftime('%Y-%m-%d-%S-%f') + ".mp3"
    else:
        SaveDir = SaveDir + "/tts/" + now.strftime('%Y-%m-%d-%S-%f') + ".mp3"
    tts.save(SaveDir)
    addSongToDB(SaveDir)


