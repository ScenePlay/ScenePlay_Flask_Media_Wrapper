from gtts import gTTS
import os
from datetime import datetime, date, time
from sql import *

def TextToSpeechPlay(_fn):
    tts = gTTS(text=_fn)##, lang='en-uk')
    now = datetime.now()
    # tts/ is not in the repo (generated audio only) — a fresh install doesn't
    # have it, and gTTS.save() can't create directories.
    ttsDir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tts")
    os.makedirs(ttsDir, exist_ok=True)
    SaveDir = os.path.join(ttsDir, now.strftime('%Y-%m-%d-%S-%f') + ".mp3")
    tts.save(SaveDir)
    addSongToDB(SaveDir)


