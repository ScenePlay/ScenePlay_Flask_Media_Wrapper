"""YouTube Live from the Broadcast page — so going live never means walking
to the streaming machine.

OBS's own "Manage Broadcast" dialog (title, description, privacy, category,
made-for-kids, thumbnail) is private to OBS's UI: obs-websocket does not
expose it. So ScenePlay talks to the YouTube Live API itself, then points
OBS at the broadcast's ingestion and hits StartStream — the DM fills the
form here and clicks once.

Auth is the OAuth *device flow*: ScenePlay shows a short code, the DM types
it at google.com/device on any logged-in device, and Google hands back a
refresh token. Chosen over the redirect flow because this app lives on a LAN
address — Google refuses plain-http redirect URIs, and the device flow needs
none. The DM supplies their own OAuth client (a "TVs and Limited Input
devices" client in Google Cloud with the YouTube Data API enabled): YouTube
scopes are only granted to a client the channel owner controls.

Every broadcast is bound to ONE reusable ScenePlay liveStream, created on
first go-live and reused forever — its RTMP key is stable, and OBS is
re-pointed at it each time anyway, so a key rotation on YouTube's side heals
itself on the next go-live.
"""
import json
import logging
import threading
import time

import requests

from sql import appsettingGet, appsettingSet

log = logging.getLogger(__name__)

DEVICE_CODE_URL = 'https://oauth2.googleapis.com/device/code'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API = 'https://www.googleapis.com/youtube/v3'
UPLOAD_API = 'https://www.googleapis.com/upload/youtube/v3'
# youtube: liveBroadcasts/liveStreams/videos. youtube.upload: thumbnails.set.
# (force-ssl would cover both but is not on the device flow's allowed list.)
SCOPES = ('https://www.googleapis.com/auth/youtube '
          'https://www.googleapis.com/auth/youtube.upload')
TIMEOUT = 20

STREAM_TITLE = 'ScenePlay'

# Assignable video categories (US). Static on purpose: the live list needs an
# API call per region and these ids have been stable for a decade.
CATEGORIES = (
    ('20', 'Gaming'),
    ('24', 'Entertainment'),
    ('22', 'People & Blogs'),
    ('10', 'Music'),
    ('27', 'Education'),
    ('28', 'Science & Technology'),
    ('23', 'Comedy'),
    ('17', 'Sports'),
    ('26', 'Howto & Style'),
    ('25', 'News & Politics'),
    ('1', 'Film & Animation'),
    ('15', 'Pets & Animals'),
    ('19', 'Travel & Events'),
    ('29', 'Nonprofits & Activism'),
    ('2', 'Autos & Vehicles'),
)
PRIVACIES = ('public', 'unlisted', 'private')


class YtError(Exception):
    """Anything the DM should read: bad credentials, revoked access, an API
    refusal. The message is already user-facing."""


# The in-flight device authorisation and the cached access token. Process
# memory on purpose: both are short-lived, and the refresh token — the only
# thing worth keeping — lives in appsettings.
_pending = {}
_token = {'value': '', 'exp': 0.0}
_lock = threading.Lock()


def linked():
    return bool((appsettingGet('yt_refresh_token', '') or '').strip())


def channel_name():
    return (appsettingGet('yt_channel', '') or '').strip()


def _client():
    cid = (appsettingGet('yt_client_id', '') or '').strip()
    secret = (appsettingGet('yt_client_secret', '') or '').strip()
    if not cid or not secret:
        raise YtError('Add your Google OAuth client ID and secret first '
                      '(Google Cloud Console → Credentials → OAuth client, '
                      'type "TVs and Limited Input devices", with the '
                      'YouTube Data API v3 enabled).')
    return cid, secret


def link_start():
    """Begin the device flow. Returns what the DM needs on screen: the code
    to type and where to type it."""
    cid, _secret = _client()
    r = requests.post(DEVICE_CODE_URL,
                      data={'client_id': cid, 'scope': SCOPES},
                      timeout=TIMEOUT)
    d = r.json() if r.content else {}
    if r.status_code != 200:
        raise YtError('Google refused to start linking: '
                      + (d.get('error_description') or d.get('error')
                         or f'HTTP {r.status_code}'))
    with _lock:
        _pending.update({
            'device_code': d['device_code'],
            'interval': int(d.get('interval', 5)),
            'expires_at': time.time() + int(d.get('expires_in', 1800)),
        })
    return {'user_code': d['user_code'],
            'verification_url': d.get('verification_url')
                                or 'https://www.google.com/device',
            'interval': int(d.get('interval', 5))}


def link_poll():
    """One poll of the pending device authorisation.

    Returns 'pending' while the DM is still typing, 'ok' once linked. The
    page drives the polling loop so a closed tab simply stops asking."""
    cid, secret = _client()
    with _lock:
        code = _pending.get('device_code')
        expires_at = _pending.get('expires_at', 0)
    if not code:
        raise YtError('No link in progress — press "Link YouTube" first.')
    if time.time() > expires_at:
        raise YtError('The code expired — press "Link YouTube" for a new one.')
    r = requests.post(TOKEN_URL, data={
        'client_id': cid, 'client_secret': secret, 'device_code': code,
        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
    }, timeout=TIMEOUT)
    d = r.json() if r.content else {}
    err = d.get('error', '')
    if err in ('authorization_pending', 'slow_down'):
        return {'state': 'pending'}
    if err:
        raise YtError('Linking failed: '
                      + (d.get('error_description') or err))
    with _lock:
        _pending.clear()
        _token.update({'value': d['access_token'],
                       'exp': time.time() + int(d.get('expires_in', 3600)) - 60})
    appsettingSet('yt_refresh_token', d.get('refresh_token', ''))
    try:
        me = _get('/channels', {'part': 'snippet', 'mine': 'true'})
        items = me.get('items') or []
        name = items[0]['snippet']['title'] if items else ''
    except YtError:
        name = ''
    appsettingSet('yt_channel', name)
    return {'state': 'ok', 'channel': name}


def unlink():
    with _lock:
        _pending.clear()
        _token.update({'value': '', 'exp': 0.0})
    appsettingSet('yt_refresh_token', '')
    appsettingSet('yt_channel', '')
    appsettingSet('yt_stream_id', '')


def _access_token():
    with _lock:
        if _token['value'] and time.time() < _token['exp']:
            return _token['value']
    cid, secret = _client()
    refresh = (appsettingGet('yt_refresh_token', '') or '').strip()
    if not refresh:
        raise YtError('YouTube is not linked yet — press "Link YouTube".')
    r = requests.post(TOKEN_URL, data={
        'client_id': cid, 'client_secret': secret,
        'refresh_token': refresh, 'grant_type': 'refresh_token',
    }, timeout=TIMEOUT)
    d = r.json() if r.content else {}
    if r.status_code != 200:
        if d.get('error') == 'invalid_grant':
            # Revoked, or a testing-mode consent screen's 7-day expiry.
            unlink()
            raise YtError('Google no longer accepts the saved link — link '
                          'YouTube again. (If this keeps happening, publish '
                          'your OAuth consent screen to "In production": '
                          'testing-mode links expire after 7 days.)')
        raise YtError('Could not refresh YouTube access: '
                      + (d.get('error_description') or d.get('error')
                         or f'HTTP {r.status_code}'))
    with _lock:
        _token.update({'value': d['access_token'],
                       'exp': time.time() + int(d.get('expires_in', 3600)) - 60})
        return _token['value']


def _call(method, path, params=None, body=None, raw=None, content_type=None,
          base=API):
    headers = {'Authorization': f'Bearer {_access_token()}'}
    if content_type:
        headers['Content-Type'] = content_type
    r = requests.request(
        method, base + path, params=params, headers=headers,
        json=body if raw is None else None, data=raw, timeout=TIMEOUT)
    if r.status_code == 204 or not r.content:
        d = {}
    else:
        try:
            d = r.json()
        except ValueError:
            d = {}
    if r.status_code >= 400:
        err = (d.get('error') or {})
        msgs = '; '.join(e.get('reason', '') for e in err.get('errors', [])
                         if e.get('reason'))
        raise YtError('YouTube said no: '
                      + (err.get('message') or f'HTTP {r.status_code}')
                      + (f' ({msgs})' if msgs else ''))
    return d


def _get(path, params):
    return _call('GET', path, params=params)


def _post(path, params, body):
    return _call('POST', path, params=params, body=body)


def _ensure_stream():
    """The one reusable RTMP endpoint every ScenePlay broadcast binds to."""
    sid = (appsettingGet('yt_stream_id', '') or '').strip()
    if sid:
        d = _get('/liveStreams', {'part': 'cdn', 'id': sid})
        items = d.get('items') or []
        if items:
            return items[0]
        appsettingSet('yt_stream_id', '')     # deleted on YouTube's side
    d = _post('/liveStreams', {'part': 'snippet,cdn'}, {
        'snippet': {'title': STREAM_TITLE},
        'cdn': {'ingestionType': 'rtmp',
                'resolution': 'variable', 'frameRate': 'variable'},
    })
    appsettingSet('yt_stream_id', d['id'])
    return d


def go_live(title, description, privacy, category, kids, thumb=None,
            start_iso=None):
    """Create tonight's broadcast, fully dressed. Returns what OBS and the
    page need: the RTMP ingestion and the watch link.

    thumb: (bytes, mime) or None. start_iso: injected by the caller —
    datetime is imported there, and tests hand in a fixed stamp."""
    title = (title or '').strip()[:100] or 'ScenePlay stream'
    privacy = privacy if privacy in PRIVACIES else 'unlisted'
    if category not in dict(CATEGORIES):
        category = '20'

    stream = _ensure_stream()
    b = _post('/liveBroadcasts',
              {'part': 'snippet,status,contentDetails'}, {
                  'snippet': {'title': title,
                              'description': (description or '')[:5000],
                              'scheduledStartTime': start_iso},
                  'status': {'privacyStatus': privacy,
                             'selfDeclaredMadeForKids': bool(kids)},
                  # Auto start/stop tie the broadcast's life to OBS's output:
                  # the existing Start/Stop streaming buttons stay the only
                  # lever, and ending the stream ends the video.
                  'contentDetails': {'enableAutoStart': True,
                                     'enableAutoStop': True,
                                     'monitorStream':
                                         {'enableMonitorStream': False}},
              })
    bid = b['id']
    _post('/liveBroadcasts/bind',
          {'part': 'id', 'id': bid, 'streamId': stream['id']}, None)
    # Category lives on the VIDEO, not the broadcast — and a snippet update
    # replaces the whole snippet, so title/description ride along.
    _call('PUT', '/videos', params={'part': 'snippet'}, body={
        'id': bid,
        'snippet': {'title': title,
                    'description': (description or '')[:5000],
                    'categoryId': category},
    })
    thumb_warning = ''
    if thumb:
        data, mime = thumb
        try:
            _call('POST', '/thumbnails/set',
                  params={'videoId': bid}, raw=data,
                  content_type=mime, base=UPLOAD_API)
        except YtError as exc:
            # A rejected thumbnail (unverified channel, >2MB) must not stop
            # the show — the stream is the point, the picture is trim.
            thumb_warning = str(exc)

    ingest = stream['cdn']['ingestionInfo']
    return {
        'broadcast_id': bid,
        'watch_url': f'https://youtu.be/{bid}',
        'server': ingest['ingestionAddress'],
        'key': ingest['streamName'],
        'thumb_warning': thumb_warning,
    }
