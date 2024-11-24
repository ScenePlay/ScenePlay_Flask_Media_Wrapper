import random
import time
from wLed.wled import * 
from models.serverIP import tblserversip as tblServerIP
from models.serverRole import tblserverrole as tblServerRole
from models.wledPattern import tbleffect as ef
from models.wledPattern import tblpallette as pt
from extensions import *


def wled_Off():
    try:
        sr = tblServerRole.query.filter(tblServerRole.name == "WLED")
        for each in sr:
            query = tblServerIP.query
            query = query.filter(tblServerIP.serverroleid == sr[0].ID)
            for each in query:
                led_strip = Wled(each.ipAddress)
                led_strip.turn_off()
    except Exception as e:
        print(e)


def wledRandom():
    try:
        sr = tblServerRole.query.filter(tblServerRole.name == "WLED")
        for each in sr:
            query = tblServerIP.query
            query = query.filter(tblServerIP.serverroleid == sr[0].ID)
            for each in query:
                led_strip = Wled(each.ipAddress)
                color = [random.randint(0, 255),random.randint(0, 255),random.randint(0, 255)]
                color2 = [random.randint(0, 255),random.randint(0, 255),random.randint(0, 255)]
                color3 = [random.randint(0, 255),random.randint(0, 255),random.randint(0, 255)]
                transition = random.randint(1, 2)
                brightness = 125
                #led_strip.set_speed(125)
                led_strip.turn_on()
                led_strip.set_color(color, color2, color3)
                #print(led_strip.get_all())
                led_strip.set_brightness(brightness)
                led_strip.set_transition(transition)
                alldata = led_strip.get_all()
                #effects=led_strip.get_effects()
                effects = alldata["effects"]
                pallettes = alldata["palettes"]
                filtered_effects = [effected for effected in effects \
                                        # if "♪" not in effected \
                                        # #and "2D" not in effected \
                                        # #and "♫" not in effected \
                                        # and "🎧" not in effected \
                                        # #and "3D" not in effected \
                                        # and "⚙️" not in effected \
                                        # and "🎉" not in effected \
                                        # and "🔨" not in effected
                                        ]
                                        
                effect = random.choice(filtered_effects)
                pallette = random.choice(pallettes) 

                if "!,!" in effect:
                    led_strip.set_effect_pallette_by_name_(effect, pallette)
                    
                    if "@" in effect:
                        eff = effect.split("@")[0]
                    else:
                        eff = effect
                    print(f"Effect {eff} and Pallette {pallette} ")
                else:
                    led_strip.set_effect_by_name(effect)
                    if "@" in effect:
                        eff = effect.split("@")[0]
                    else:
                        eff = effect
                    print(f"Effect Only {eff}")
    except Exception as e:
        print(e)


def setWledEffect(_effect,_pallette,_color, _color2, _color3, _speed, _brightness, _serverIP_ID):
    try:
        sr = tblServerRole.query.filter(tblServerRole.name == "WLED")
        for row in sr:
            server = tblServerIP.query.filter(tblServerIP.ServerIP_ID == _serverIP_ID).all()
            effect = ef.query.filter(ef.ef_ID == _effect).first()
            pallette = pt.query.filter(pt.pa_ID == _pallette).first()
            for row in server:
                led_strip = Wled(row.ipAddress)
                led_strip.turn_on()
                led_strip.set_speed(_speed)
                led_strip.set_color(_color, _color2, _color3)
                led_strip.set_brightness(_brightness)
                if (pallette != None):
                    led_strip.set_effect_pallette_by_name_(effect.effectName, pallette.palletteName)
                    #print(effect.effectName, pallette.palletteName)
                else:
                    led_strip.set_pallette_by_ID(0)
                    led_strip.set_effect_by_name(effect.effectName)
                    print(effect.effectName)
                    
                
    except Exception as e:
        print(e)
        

def addEffectsPallettes(ServerIP_ID):
    
    try:
        query = tblServerIP.query.filter(tblServerIP.ServerIP_ID == ServerIP_ID)
        led_strip = Wled(query[0].ipAddress)
        alldata = led_strip.get_all()
        effects = alldata["effects"]
        db.session.query(ef).delete()
        i = 0
        for item in effects:
                erRow = ef(
                    effectName=item,
                    ef_ID= i+1
                )
                db.session.add(erRow)
                i += 1
        db.session.commit()
    except Exception as e:
        print(e)
        
    try:
        query = tblServerIP.query.filter(tblServerIP.ServerIP_ID == ServerIP_ID)
        led_strip = Wled(query[0].ipAddress)
        alldata = led_strip.get_all()
        pallettes = alldata["palettes"]
        db.session.query(pt).delete()
        i = 0
        for item in pallettes:
            ptRow = pt(
                palletteName=item,
                pa_ID=i+1
            )
            db.session.add(ptRow)
            i += 1
        db.session.commit()
    except Exception as e:
        print(e)