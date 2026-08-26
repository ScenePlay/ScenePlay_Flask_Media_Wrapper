"""Chimes: short sounds the box plays on an EVENT, driven by data.

EVENTS is the registry — one row per thing that can chime. A new chime is a
row here plus one `chime_path('<key>')` call where it should sound; the
Utilities card, the settings keys, and the API all render from this list.
Each event has an on/off switch and a sound picked from the effects/ folder
(any .mp3/.wav dropped or uploaded there is offered), falling back to the
event's bundled default when the chosen file has gone.

Settings (tblAppSettings): chime_<key>_on ('1'/'0'), chime_<key>_file.
The download events also honour the older dl_sound_ok / dl_sound_fail
switches so an existing "off" keeps holding after the upgrade.

Pure module: no Flask, settings access is injected (sql.appsettingGet/Set).
"""
import os
import re

EVENTS = [
    {'key': 'download_ok',   'label': 'YouTube download finished',
     'default': 'finished.mp3', 'legacy_on': 'dl_sound_ok',
     'help': 'Plays when a song or video download completes.'},
    {'key': 'download_fail', 'label': 'YouTube download failed',
     'default': 'failed.mp3',   'legacy_on': 'dl_sound_fail',
     'help': 'Plays when a download fails (see the Download Queue card for why).'},
]
EVENT_KEYS = {e['key']: e for e in EVENTS}
SOUND_EXTS = ('.mp3', '.wav', '.ogg')
_SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}\.(mp3|wav|ogg)$', re.I)


def effects_dir(base=None):
    return os.path.join(base or os.path.dirname(os.path.abspath(__file__)), 'effects')


def available_sounds(directory):
    """Sound files offered by the picker, bundled defaults first."""
    try:
        names = [n for n in os.listdir(directory)
                 if n.lower().endswith(SOUND_EXTS) and not n.startswith('.')]
    except OSError:
        names = []
    defaults = [e['default'] for e in EVENTS]
    return sorted(names, key=lambda n: (n not in defaults, n.lower()))


def safe_sound_name(name):
    return bool(name) and bool(_SAFE_NAME.match(name)) and name == os.path.basename(name)


def _on(get, ev):
    raw = get(f"chime_{ev['key']}_on", None)
    if raw is None and ev.get('legacy_on'):
        raw = get(ev['legacy_on'], None)
    return str(raw if raw is not None else '1') == '1'


def config(get, directory):
    """[{key, label, help, enabled, file, default, missing}] for the card."""
    have = set(available_sounds(directory))
    out = []
    for ev in EVENTS:
        chosen = (get(f"chime_{ev['key']}_file", '') or '').strip()
        missing = bool(chosen) and chosen not in have
        out.append({'key': ev['key'], 'label': ev['label'], 'help': ev['help'],
                    'enabled': _on(get, ev), 'default': ev['default'],
                    'file': chosen if chosen and not missing else ev['default'],
                    'missing': missing})
    return out


def save(get, set_, directory, key, enabled=None, file=None):
    """Persist one event's switch and/or sound. Unknown files are refused
    (returns False); the legacy switch is kept in step for old readers."""
    ev = EVENT_KEYS.get(key)
    if not ev:
        return False
    if enabled is not None:
        set_(f"chime_{key}_on", '1' if enabled else '0')
        if ev.get('legacy_on'):
            set_(ev['legacy_on'], '1' if enabled else '0')
    if file is not None:
        if file and file not in available_sounds(directory):
            return False
        set_(f"chime_{key}_file", file or '')
    return True


def chime_path(get, directory, key):
    """Absolute path of the sound to play for an event, or None when the
    event is switched off / unknown. Never raises — a settings hiccup means
    the default sound, not silence."""
    ev = EVENT_KEYS.get(key)
    if not ev:
        return None
    try:
        if not _on(get, ev):
            return None
        chosen = (get(f"chime_{key}_file", '') or '').strip()
    except Exception:
        chosen = ''
    if not chosen or not os.path.isfile(os.path.join(directory, chosen)):
        chosen = ev['default']
    return os.path.join(directory, chosen)
