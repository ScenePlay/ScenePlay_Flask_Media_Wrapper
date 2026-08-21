"""gemini.py client: key-file handling, model resolution, response parsing,
and the Veo job lifecycle. Every network call is faked — no test touches
the API or spends quota."""
import base64
import stat
import time

import pytest

import gemini


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = b''

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture()
def key_file(tmp_path, monkeypatch):
    path = tmp_path / 'gemini_api_key'
    monkeypatch.setattr(gemini, '_KEY_PATH', str(path))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    return path


class TestKeyFile:
    def test_unconfigured_by_default(self, key_file):
        assert gemini.load_api_key() is None
        assert gemini.configured() is False
        assert gemini.key_source() is None

    def test_save_load_clear_roundtrip(self, key_file):
        gemini.save_api_key('  sk-test-123  ')
        assert key_file.read_text() == 'sk-test-123'
        assert gemini.load_api_key() == 'sk-test-123'
        assert gemini.key_source() == 'file'
        # 0600: the key is private to the service user
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        gemini.clear_api_key()
        assert gemini.configured() is False

    def test_blank_save_is_a_noop(self, key_file):
        gemini.save_api_key('   ')
        assert not key_file.exists()

    def test_env_var_wins(self, key_file, monkeypatch):
        gemini.save_api_key('file-key')
        monkeypatch.setenv('GEMINI_API_KEY', 'env-key')
        assert gemini.load_api_key() == 'env-key'
        assert gemini.key_source() == 'env'

    def test_headers_raise_without_key(self, key_file):
        with pytest.raises(gemini.GeminiError) as e:
            gemini._headers()
        assert 'Utilities' in str(e.value)


class TestResolveModel:
    def test_defaults(self, monkeypatch):
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: default)
        for modality in ('text', 'image', 'video'):
            assert gemini.resolve_model(modality) == gemini.DEFAULTS[modality]

    def test_override_must_be_allowlisted(self, monkeypatch):
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: default)
        assert gemini.resolve_model('text', 'gemini-2.5-pro') == 'gemini-2.5-pro'
        assert gemini.resolve_model('text', 'gpt-9000') == gemini.DEFAULTS['text']

    def test_stored_setting_used_when_allowlisted(self, monkeypatch):
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: 'gemini-2.5-pro'
                            if name == 'gemini_model_text' else default)
        assert gemini.resolve_model('text') == 'gemini-2.5-pro'

    def test_stored_garbage_falls_back(self, monkeypatch):
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: 'llama-4')
        assert gemini.resolve_model('image') == gemini.DEFAULTS['image']


@pytest.fixture()
def fake_requests(key_file, monkeypatch):
    """Configured key + a scripted requests module."""
    gemini.save_api_key('k')
    calls = {'post': [], 'get': []}
    responses = {'post': [], 'get': []}

    class _FakeRequests:
        @staticmethod
        def post(url, headers=None, json=None, timeout=None):
            calls['post'].append({'url': url, 'headers': headers, 'json': json})
            return responses['post'].pop(0)

        @staticmethod
        def get(url, headers=None, timeout=None, allow_redirects=True):
            calls['get'].append({'url': url, 'headers': headers})
            return responses['get'].pop(0)

    import sys
    monkeypatch.setitem(sys.modules, 'requests', _FakeRequests)
    return calls, responses


def _gen_body(parts):
    return {'candidates': [{'content': {'parts': parts}}]}


class TestGenerateJson:
    def test_happy_path_and_request_shape(self, fake_requests):
        calls, responses = fake_requests
        responses['post'].append(_Resp(200, _gen_body([{'text': '{"walls": []}'}])))
        out = gemini.generate_json('design a map', 'gemini-2.5-flash')
        assert out == '{"walls": []}'
        req = calls['post'][0]
        assert req['url'].endswith('models/gemini-2.5-flash:generateContent')
        assert req['headers']['x-goog-api-key'] == 'k'
        assert '?' not in req['url']            # never the key in a URL
        assert req['json']['generationConfig']['responseMimeType'] == 'application/json'

    def test_image_attachment_rides_inline(self, fake_requests):
        calls, responses = fake_requests
        responses['post'].append(_Resp(200, _gen_body([{'text': '{}'}])))
        gemini.generate_json('trace', 'gemini-2.5-flash',
                             image=b'PNG', mime='image/png')
        parts = calls['post'][0]['json']['contents'][0]['parts']
        assert parts[1]['inline_data']['data'] == base64.b64encode(b'PNG').decode()

    def test_safety_block_readable(self, fake_requests):
        _, responses = fake_requests
        responses['post'].append(_Resp(200, {
            'promptFeedback': {'blockReason': 'SAFETY'}}))
        with pytest.raises(gemini.GeminiError) as e:
            gemini.generate_json('x', 'gemini-2.5-flash')
        assert 'safety' in str(e.value).lower()

    def test_http_errors_friendly(self, fake_requests):
        _, responses = fake_requests
        responses['post'].append(_Resp(429, {'error': {'message': 'slow down'}}))
        with pytest.raises(gemini.GeminiError) as e:
            gemini.generate_json('x', 'gemini-2.5-flash')
        assert 'quota' in str(e.value).lower() and 'slow down' in str(e.value)
        responses['post'].append(_Resp(403, {'error': {'message': 'bad key'}}))
        with pytest.raises(gemini.GeminiError) as e2:
            gemini.generate_json('x', 'gemini-2.5-flash')
        assert 'key' in str(e2.value).lower()


class TestGenerateImage:
    def test_camelcase_inline_data(self, fake_requests):
        _, responses = fake_requests
        responses['post'].append(_Resp(200, _gen_body([
            {'text': 'here you go'},
            {'inlineData': {'mimeType': 'image/png',
                            'data': base64.b64encode(b'IMG').decode()}},
        ])))
        raw, ext = gemini.generate_image('paint', 'gemini-2.5-flash-image')
        assert raw == b'IMG' and ext == 'png'

    def test_snake_case_and_jpeg_ext(self, fake_requests):
        _, responses = fake_requests
        responses['post'].append(_Resp(200, _gen_body([
            {'inline_data': {'mime_type': 'image/jpeg',
                             'data': base64.b64encode(b'J').decode()}},
        ])))
        raw, ext = gemini.generate_image('paint', 'gemini-2.5-flash-image')
        assert raw == b'J' and ext == 'jpg'

    def test_text_only_reply_is_an_error(self, fake_requests):
        _, responses = fake_requests
        responses['post'].append(_Resp(200, _gen_body([{'text': 'sorry no'}])))
        with pytest.raises(gemini.GeminiError) as e:
            gemini.generate_image('paint', 'gemini-2.5-flash-image')
        assert 'without an image' in str(e.value)


class TestVeo:
    def test_start_poll_extract(self, fake_requests):
        calls, responses = fake_requests
        responses['post'].append(_Resp(200, {'name': 'operations/abc'}))
        op = gemini.veo_start('animate', 'veo-3.1-fast-generate-preview')
        assert op == 'operations/abc'
        assert calls['post'][0]['url'].endswith(':predictLongRunning')
        responses['get'].append(_Resp(200, {'done': False}))
        assert gemini.veo_poll(op) == {'done': False}
        responses['get'].append(_Resp(200, {'done': True, 'response': {
            'generateVideoResponse': {'generatedSamples': [
                {'video': {'uri': 'https://dl/video.mp4'}}]}}}))
        assert gemini.veo_poll(op) == {'done': True, 'uri': 'https://dl/video.mp4'}

    def test_poll_surfaces_operation_error(self, fake_requests):
        _, responses = fake_requests
        responses['get'].append(_Resp(200, {'done': True,
                                            'error': {'message': 'no credit'}}))
        with pytest.raises(gemini.GeminiError) as e:
            gemini.veo_poll('operations/x')
        assert 'no credit' in str(e.value)

    def test_inline_bytes_shape(self):
        uri, raw = gemini._veo_extract_video({
            'generatedVideos': [{'video': {
                'bytesBase64Encoded': base64.b64encode(b'MP4').decode()}}]})
        assert raw == b'MP4' and uri is None


class TestVideoJob:
    def test_lifecycle_success(self, fake_requests, monkeypatch):
        _, responses = fake_requests
        monkeypatch.setattr(gemini, 'VEO_POLL_S', 0)
        responses['post'].append(_Resp(200, {'name': 'operations/j'}))
        responses['get'].append(_Resp(200, {'done': False}))
        done = _Resp(200, {'done': True, 'response': {
            'generateVideoResponse': {'generatedSamples': [
                {'video': {'bytesBase64Encoded':
                           base64.b64encode(b'VID').decode()}}]}}})
        responses['get'].append(done)
        saved = {}

        def on_success(raw, ext):
            saved['raw'], saved['ext'] = raw, ext
            return {'ok': True, 'url': '/x.mp4'}

        job_id = gemini.start_video_job('go', 'veo-3.1-fast-generate-preview',
                                        on_success=on_success)
        for _ in range(100):
            rec = gemini.job_status(job_id)
            if rec['status'] != 'running':
                break
            time.sleep(0.02)
        assert rec['status'] == 'done', rec
        assert saved == {'raw': b'VID', 'ext': 'mp4'}
        assert rec['result'] == {'ok': True, 'url': '/x.mp4'}

    def test_lifecycle_error(self, fake_requests, monkeypatch):
        _, responses = fake_requests
        monkeypatch.setattr(gemini, 'VEO_POLL_S', 0)
        responses['post'].append(_Resp(400, {'error': {'message': 'bad prompt'}}))
        job_id = gemini.start_video_job('go', 'veo-3.1-fast-generate-preview')
        for _ in range(100):
            rec = gemini.job_status(job_id)
            if rec['status'] != 'running':
                break
            time.sleep(0.02)
        assert rec['status'] == 'error'
        assert 'bad prompt' in rec['error']

    def test_unknown_job(self):
        assert gemini.job_status('nope') is None
