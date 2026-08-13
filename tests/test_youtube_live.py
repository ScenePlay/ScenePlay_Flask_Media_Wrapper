"""Going live on YouTube from the Broadcast page.

The API client is exercised against recorded fake HTTP — no network. What
matters: the device-flow linking stores the refresh token, an expired link
explains itself, and go_live dresses the broadcast exactly as the form said
(privacy, kids flag, category on the VIDEO, auto start/stop).
"""
import time

import pytest

import youtube_live as yt


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._d = {} if data is None else data
        self.content = b'x' if data is not None else b''

    def json(self):
        return self._d


@pytest.fixture()
def store(monkeypatch):
    s = {'yt_client_id': 'cid', 'yt_client_secret': 'sec'}
    monkeypatch.setattr(yt, 'appsettingGet', lambda n, d=None: s.get(n, d))
    monkeypatch.setattr(yt, 'appsettingSet',
                        lambda n, v: s.__setitem__(n, str(v)))
    yt._pending.clear()
    yt._token.update({'value': '', 'exp': 0.0})
    return s


@pytest.fixture()
def http(monkeypatch):
    """Queue of canned responses; every request is recorded."""
    calls, queue = [], []

    def fake_post(url, data=None, timeout=None):
        calls.append({'method': 'POST', 'url': url, 'data': data})
        return queue.pop(0)

    def fake_request(method, url, params=None, headers=None,
                     json=None, data=None, timeout=None):
        calls.append({'method': method, 'url': url, 'params': params,
                      'json': json, 'raw': data})
        return queue.pop(0)

    monkeypatch.setattr(yt.requests, 'post', fake_post)
    monkeypatch.setattr(yt.requests, 'request', fake_request)
    return calls, queue


def _fresh_token():
    yt._token.update({'value': 'tok', 'exp': time.time() + 300})


class TestLinking:
    def test_link_start_hands_back_the_code_to_type(self, store, http):
        calls, queue = http
        queue.append(FakeResp(200, {'device_code': 'dev1', 'user_code':
                                    'ABCD-EFGH', 'interval': 5,
                                    'expires_in': 900,
                                    'verification_url':
                                        'https://www.google.com/device'}))
        d = yt.link_start()
        assert d['user_code'] == 'ABCD-EFGH'
        assert calls[0]['data']['client_id'] == 'cid'
        assert 'youtube' in calls[0]['data']['scope']

    def test_link_poll_pending_then_linked(self, store, http):
        calls, queue = http
        yt._pending.update({'device_code': 'dev1',
                            'expires_at': time.time() + 900})
        queue.append(FakeResp(428, {'error': 'authorization_pending'}))
        assert yt.link_poll()['state'] == 'pending'
        queue.append(FakeResp(200, {'access_token': 'tok',
                                    'refresh_token': 'ref',
                                    'expires_in': 3600}))
        queue.append(FakeResp(200, {'items': [{'snippet':
                                               {'title': 'My Channel'}}]}))
        d = yt.link_poll()
        assert d == {'state': 'ok', 'channel': 'My Channel'}
        assert store['yt_refresh_token'] == 'ref'
        assert yt.linked()

    def test_missing_credentials_read_as_instructions(self, store, http):
        store['yt_client_id'] = ''
        with pytest.raises(yt.YtError, match='client ID'):
            yt.link_start()

    def test_expired_refresh_token_unlinks_and_explains(self, store, http):
        _calls, queue = http
        store['yt_refresh_token'] = 'ref'
        queue.append(FakeResp(400, {'error': 'invalid_grant'}))
        with pytest.raises(yt.YtError, match='link YouTube again'):
            yt._access_token()
        assert store['yt_refresh_token'] == ''


class TestGoLive:
    def _queue_happy_path(self, queue, with_thumb=False):
        queue.append(FakeResp(200, {                      # liveStreams insert
            'id': 'S1',
            'cdn': {'ingestionInfo': {'ingestionAddress': 'rtmp://in',
                                      'streamName': 'key-1'}}}))
        queue.append(FakeResp(200, {'id': 'B1'}))         # broadcast insert
        queue.append(FakeResp(200, {}))                   # bind
        queue.append(FakeResp(200, {}))                   # videos update
        if with_thumb:
            queue.append(FakeResp(200, {}))               # thumbnails.set

    def test_broadcast_is_dressed_exactly_as_asked(self, store, http):
        calls, queue = http
        _fresh_token()
        self._queue_happy_path(queue)
        res = yt.go_live('Night 12', 'the plot thickens', 'public', '24',
                         True, start_iso='2026-08-13T00:00:00Z')
        assert res['watch_url'] == 'https://youtu.be/B1'
        assert res['server'] == 'rtmp://in' and res['key'] == 'key-1'
        bcast = next(c for c in calls if c['url'].endswith('/liveBroadcasts'))
        assert bcast['json']['snippet']['title'] == 'Night 12'
        assert bcast['json']['status'] == {'privacyStatus': 'public',
                                           'selfDeclaredMadeForKids': True}
        assert bcast['json']['contentDetails']['enableAutoStart'] is True
        assert bcast['json']['contentDetails']['enableAutoStop'] is True
        # Category rides the VIDEO update, not the broadcast.
        vid = next(c for c in calls if c['url'].endswith('/videos'))
        assert vid['json']['snippet']['categoryId'] == '24'
        assert store['yt_stream_id'] == 'S1'

    def test_existing_stream_is_reused_not_recreated(self, store, http):
        calls, queue = http
        _fresh_token()
        store['yt_stream_id'] = 'S1'
        queue.append(FakeResp(200, {'items': [{                 # streams list
            'id': 'S1',
            'cdn': {'ingestionInfo': {'ingestionAddress': 'rtmp://in',
                                      'streamName': 'key-1'}}}]}))
        queue.append(FakeResp(200, {'id': 'B2'}))
        queue.append(FakeResp(200, {}))
        queue.append(FakeResp(200, {}))
        yt.go_live('t', '', 'unlisted', '20', False,
                   start_iso='2026-08-13T00:00:00Z')
        inserts = [c for c in calls if c['url'].endswith('/liveStreams')
                   and c['method'] == 'POST']
        assert not inserts, 'the reusable stream must not be recreated'
        bind = next(c for c in calls if 'bind' in c['url'])
        assert bind['params']['streamId'] == 'S1'

    def test_bad_privacy_and_category_fall_back_safe(self, store, http):
        calls, queue = http
        _fresh_token()
        self._queue_happy_path(queue)
        yt.go_live('t', '', 'everyone!!', 'nope', False,
                   start_iso='2026-08-13T00:00:00Z')
        bcast = next(c for c in calls if c['url'].endswith('/liveBroadcasts'))
        assert bcast['json']['status']['privacyStatus'] == 'unlisted'
        vid = next(c for c in calls if c['url'].endswith('/videos'))
        assert vid['json']['snippet']['categoryId'] == '20'

    def test_rejected_thumbnail_warns_instead_of_stopping_the_show(
            self, store, http):
        _calls, queue = http
        _fresh_token()
        self._queue_happy_path(queue)
        queue.append(FakeResp(400, {'error': {'message': 'too big'}}))
        res = yt.go_live('t', '', 'unlisted', '20', False,
                         thumb=(b'x' * 10, 'image/jpeg'),
                         start_iso='2026-08-13T00:00:00Z')
        assert res['watch_url'] == 'https://youtu.be/B1'
        assert 'too big' in res['thumb_warning']

    def test_api_refusal_is_a_readable_error(self, store, http):
        _calls, queue = http
        _fresh_token()
        queue.append(FakeResp(403, {'error': {
            'message': 'The user is not enabled for live streaming.',
            'errors': [{'reason': 'liveStreamingNotEnabled'}]}}))
        with pytest.raises(yt.YtError, match='not enabled for live'):
            yt.go_live('t', '', 'unlisted', '20', False,
                       start_iso='2026-08-13T00:00:00Z')
