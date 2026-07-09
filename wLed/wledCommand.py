import logging
import random
import time
from wLed.wled import *
from models.serverIP import tblserversip as tblServerIP
from models.serverRole import tblserverrole as tblServerRole
from models.wledPattern import tbleffect as ef
from models.wledPattern import tblpallette as pt
from extensions import *

log = logging.getLogger(__name__)


def _wled_role_id():
    role = tblServerRole.query.filter(tblServerRole.name == "WLED").first()
    return role.ID if role else None


def wled_devices():
    """Yield (ServerIP row, Wled client) for every ENABLED device with the
    WLED role — a server the operator deactivated must stop receiving
    commands without being deleted.

    Single home for the role->devices lookup that used to be copy-pasted — with
    a shadowed `for each` loop and a stray `sr[0]` — into every command below.
    Constructing a Wled() no longer touches the network, so an offline board
    costs nothing here; it only matters when a command is actually sent."""
    role_id = _wled_role_id()
    if role_id is None:
        return
    for server in tblServerIP.query.filter(tblServerIP.serverroleid == role_id,
                                           tblServerIP.active == 1).all():
        yield server, Wled(server.ipAddress)


def wled_Off():
    # Per-device try so one unreachable board doesn't stop the rest from turning
    # off (the old whole-loop try aborted at the first failure).
    for server, led_strip in wled_devices():
        try:
            led_strip.turn_off()
        except Exception as e:
            log.warning("WLED turn_off failed for %s: %s", server.ipAddress, e)


def wledRandom():
    for server, led_strip in wled_devices():
        try:
            color  = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
            color2 = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
            color3 = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]
            transition = random.randint(1, 2)
            brightness = 125
            led_strip.turn_on()
            led_strip.set_color(color, color2, color3)
            led_strip.set_brightness(brightness)
            led_strip.set_transition(transition)
            alldata = led_strip.get_all()
            effects = alldata["effects"]
            pallettes = alldata["palettes"]
            # Historically this filtered out audio-reactive/2D/⚙️ effects by symbol;
            # currently a pass-through (all effects eligible).
            filtered_effects = list(effects)

            effect = random.choice(filtered_effects)
            pallette = random.choice(pallettes)

            if "!,!" in effect:
                led_strip.set_effect_pallette_by_name_(effect, pallette)
                eff = effect.split("@")[0] if "@" in effect else effect
                log.info("WLED %s effect %s + palette %s", server.ipAddress, eff, pallette)
            else:
                led_strip.set_effect_by_name(effect)
                eff = effect.split("@")[0] if "@" in effect else effect
                log.info("WLED %s effect %s", server.ipAddress, eff)
        except Exception as e:
            log.warning("WLED random failed for %s: %s", server.ipAddress, e)


def setWledEffect(_effect,_pallette,_color, _color2, _color3, _speed, _brightness, _serverIP_ID):
    # Applies one pattern to the single server identified by _serverIP_ID (a PK).
    # Scenes assign a pattern row PER DEVICE — each row targets its own server.
    server = tblServerIP.query.filter(tblServerIP.ServerIP_ID == _serverIP_ID).first()
    if server is None:
        return
    # Gate on the CURRENT server row: scene pattern rows keep their server_ID
    # after the operator disables the server or moves it off the WLED role,
    # and must stop firing at it when they do.
    if not server.active or server.serverroleid != _wled_role_id():
        return
    effect = ef.query.filter(ef.ef_ID == _effect).first()
    if effect is None:
        return
    pallette = pt.query.filter(pt.pa_ID == _pallette).first()
    try:
        led_strip = Wled(server.ipAddress)
        led_strip.turn_on()
        led_strip.set_speed(_speed)
        led_strip.set_color(_color, _color2, _color3)
        led_strip.set_brightness(_brightness)
        if pallette is not None:
            led_strip.set_effect_pallette_by_name_(effect.effectName, pallette.palletteName)
        else:
            led_strip.set_pallette_by_ID(0)
            led_strip.set_effect_by_name(effect.effectName)
    except Exception as e:
        log.warning("WLED setWledEffect failed for %s: %s", server.ipAddress, e)
        

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