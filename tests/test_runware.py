"""runware.py client: key handling, model/size resolution, and the REST
request/response contract (requests.post mocked — no network)."""
import base64

import pytest

import runware


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    monkeypatch.setattr(runware, '_KEY_PATH', str(tmp_path / 'rkey'))
    monkeypatch.delenv('RUNWARE_API_KEY', raising=False)
    return tmp_path


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = status < 400

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


class TestKeys:
    def test_save_load_clear(self, keyfile):
        assert runware.load_api_key() is None and not runware.configured()
        runware.save_api_key('  abc  ')
        assert runware.load_api_key() == 'abc' and runware.key_source() == 'file'
        runware.clear_api_key()
        assert not runware.configured()

    def test_env_wins(self, keyfile, monkeypatch):
        runware.save_api_key('filekey')
        monkeypatch.setenv('RUNWARE_API_KEY', 'envkey')
        assert runware.load_api_key() == 'envkey' and runware.key_source() == 'env'


class TestModelAndSize:
    def test_resolve_override_setting_default(self, monkeypatch):
        import sql
        stored = {'runware_model': 'civitai:4201@130090'}
        monkeypatch.setattr(sql, 'appsettingGet', lambda n, d=None: stored.get(n, d))
        assert runware.resolve_model('runware:100@1') == 'runware:100@1'
        assert runware.resolve_model() == 'civitai:4201@130090'
        stored['runware_model'] = 'no-colon-junk'
        assert runware.resolve_model() == runware.DEFAULT_MODEL

    def test_size_for_ratio(self):
        assert runware.size_for_ratio(20, 20) == (1024, 1024)
        w, h = runware.size_for_ratio(30, 20)
        assert (w, h) == (1536, 1024) and w % 64 == 0
        assert runware.size_for_ratio(60, 20) == (2048, 1024)   # ratio clamped to 2:1
        assert runware.size_for_ratio(20, 60) == (1024, 2048)
        assert runware.size_for_ratio(None, 0) == (1024, 1024)


class TestGenerate:
    def _ok(self, b64):
        return FakeResp({'data': [{'taskType': 'imageInference',
                                   'imageBase64Data': b64, 'cost': 0.001}]})

    def test_request_shape_and_result(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        sent = {}
        def fake_post(url, json=None, timeout=None, headers=None):
            sent.update(url=url, body=json, headers=headers)
            return self._ok(base64.b64encode(b'IMG').decode())
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        raw, ext = runware.generate_image('a dragon', 'runware:100@1',
                                          size=(1000, 500))
        assert (raw, ext) == (b'IMG', 'png')
        assert sent['url'] == runware.API_URL
        assert sent['headers']['Authorization'] == 'Bearer rk'
        task = sent['body'][0]
        assert task['taskType'] == 'imageInference'
        assert task['positivePrompt'] == 'a dragon' + runware.NO_TEXT_SUFFIX
        assert task['negativePrompt'] == runware.NEGATIVE_PROMPT
        assert task['model'] == 'runware:100@1'
        assert task['width'] == 1024 and task['height'] == 512    # rounded to 64
        assert task['outputType'] == 'base64Data' and task['numberResults'] == 1
        assert 'seedImage' not in task

    def test_no_text_clause_survives_truncation(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        sent = {}
        monkeypatch.setattr(runware.requests, 'post',
                            lambda url, json=None, timeout=None, headers=None:
                            sent.update(body=json) or self._ok(base64.b64encode(b'X').decode()))
        runware.generate_image('x' * 5000)
        pp = sent['body'][0]['positivePrompt']
        assert pp.endswith(runware.NO_TEXT_SUFFIX)
        assert len(pp) <= runware.PROMPT_MAX

    def test_seed_image_conditioning(self, keyfile, monkeypatch):
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE[runware.DEFAULT_MODEL] = False
        runware.save_api_key('rk')
        sent = {}
        monkeypatch.setattr(runware.requests, 'post',
                            lambda url, json=None, timeout=None, headers=None:
                            sent.update(body=json) or self._ok(base64.b64encode(b'X').decode()))
        runware.generate_image('paint over', image=b'PNGBYTES', mime='image/png')
        task = sent['body'][0]
        assert task['seedImage'] == 'data:image/png;base64,' + base64.b64encode(b'PNGBYTES').decode()
        assert task['strength'] == runware.SEED_STRENGTH

    def test_no_key_raises_before_network(self, keyfile, monkeypatch):
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError('no network expected')))
        with pytest.raises(runware.RunwareError, match='API key'):
            runware.generate_image('x')

    def test_api_error_normalized(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'errors': [{'message': 'Invalid API key'}]}, 401))
        with pytest.raises(runware.RunwareError, match='rejected the API key'):
            runware.generate_image('x')

    def test_non_json_and_empty_and_missing_data(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post', lambda *a, **k: FakeResp(None, 500))
        with pytest.raises(runware.RunwareError, match='unreadable body'):
            runware.generate_image('x')
        monkeypatch.setattr(runware.requests, 'post', lambda *a, **k: FakeResp({'data': []}))
        with pytest.raises(runware.RunwareError, match='empty response'):
            runware.generate_image('x')
        monkeypatch.setattr(runware.requests, 'post', lambda *a, **k: FakeResp({'data': [{}]}))
        with pytest.raises(runware.RunwareError, match='no image data'):
            runware.generate_image('x')

    def test_network_error_normalized(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        def boom(*a, **k):
            raise runware.requests.ConnectionError('down')
        monkeypatch.setattr(runware.requests, 'post', boom)
        with pytest.raises(runware.RunwareError, match='request failed'):
            runware.generate_image('x')


class TestSeedFallback:
    def _seed_reject(self):
        return FakeResp({'errors': [{'code': 'unsupportedParameter',
                                     'message': "Unsupported use of 'seedImage' parameter. "
                                                'This parameter is not supported for the selected model.'}]}, 400)

    def test_rejected_seed_converts_to_reference_images(self, keyfile, monkeypatch):
        import base64 as b64
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE['runware:101@1'] = False
        runware.save_api_key('rk')
        bodies = []
        def fake_post(url, json=None, timeout=None, headers=None):
            bodies.append(dict(json[0]))   # copy: the retry mutates the task in place
            if 'seedImage' in json[0]:
                return self._seed_reject()
            return FakeResp({'data': [{'imageBase64Data': b64.b64encode(b'IMG').decode()}]})
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        info = {}
        raw, ext = runware.generate_image('paint', 'runware:101@1', image=b'SCHEMATIC', info=info)
        assert raw == b'IMG' and info == {}                  # image survived via referenceImages
        assert 'seedImage' in bodies[0]
        assert bodies[1]['referenceImages'] == [bodies[0]['seedImage']]
        assert 'strength' not in bodies[1]
        assert bodies[0]['taskUUID'] != bodies[1]['taskUUID']

    def test_reference_images_also_rejected_drops_and_flags(self, keyfile, monkeypatch):
        import base64 as b64
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE['runware:101@1'] = False
        runware.save_api_key('rk')
        def fake_post(url, json=None, timeout=None, headers=None):
            for p in ('seedImage', 'referenceImages'):
                if p in json[0]:
                    return FakeResp({'errors': [{'message': f"Unsupported use of '{p}' parameter. "
                                                            'This parameter is not supported for the selected model.'}]}, 400)
            return FakeResp({'data': [{'imageBase64Data': b64.b64encode(b'IMG').decode()}]})
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        info = {}
        raw, _ = runware.generate_image('paint', 'runware:101@1', image=b'S', info=info)
        assert raw == b'IMG' and info == {'seed_dropped': True}

    def test_instruction_native_model_sends_reference_images_first(self, keyfile, monkeypatch):
        import base64 as b64
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE['google:4@3'] = True
        runware.save_api_key('rk')
        sent = {}
        monkeypatch.setattr(runware.requests, 'post',
                            lambda url, json=None, timeout=None, headers=None:
                            sent.update(body=dict(json[0])) or FakeResp(
                                {'data': [{'imageBase64Data': b64.b64encode(b'X').decode()}]}))
        runware.generate_image('edit this', 'google:4@3', image=b'SCHEMATIC')
        assert 'seedImage' not in sent['body'] and 'strength' not in sent['body']
        assert sent['body']['referenceImages'][0].startswith('data:image/png;base64,')

    def test_other_errors_still_raise(self, keyfile, monkeypatch):
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE[runware.DEFAULT_MODEL] = False
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'errors': [{'message': 'model not found'}]}, 400))
        with pytest.raises(runware.RunwareError, match='model not found'):
            runware.generate_image('x', image=b'S')

    def test_seed_error_without_seed_raises(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'errors': [{'message': "Unsupported use of 'seedImage' parameter"}]}, 400))
        with pytest.raises(runware.RunwareError):
            runware.generate_image('x')            # no image sent → nothing to retry


class TestDistillBattlemapPrompt:
    GEMINI_PROMPT = (
        "Please generate a strictly TOP-DOWN TTRPG battlemap background image that EXACTLY "
        "reproduces the ATTACHED schematic floorplan — see LAYOUT MATCH below.\n\n"
        "## SCENE\nEnvironment: ruined chapel with a crypt below\nTime of day: night\n"
        "Atmosphere: heavy fog\nLighting: torchlight\nArt style: dark oil painting\n"
        "Additional details: a pit trap before the altar\n\n"
        "## LAYOUT MATCH\n- wall from (0,0) to (10,0)\n- door at (5,0) width 1\n"
        "Before finalising, verify every door covers a gap in a wall.")

    def test_keeps_scene_drops_schematic_language(self):
        out = runware.distill_battlemap_prompt(self.GEMINI_PROMPT)
        for kept in ('ruined chapel with a crypt below', 'night', 'heavy fog',
                     'torchlight', 'dark oil painting', 'a pit trap before the altar'):
            assert kept in out
        low = out.lower()
        for banned in ('schematic', 'layout match', 'attached', 'wall from', 'reproduce'):
            assert banned not in low
        assert low.startswith('flat top-down orthographic battle map')

    def test_travel_maps_get_cartography_framing(self):
        out = runware.distill_battlemap_prompt(
            'Please generate ... a large-scale TRAVEL MAP for a TTRPG.\n'
            '## SCENE\nMap type: island archipelago\nArt style: inked atlas')
        assert out.startswith('hand-drawn fantasy cartography')
        assert 'island archipelago' in out and 'inked atlas' in out

    def test_empty_prompt_still_yields_a_caption(self):
        out = runware.distill_battlemap_prompt('')
        assert 'battle map' in out

    def test_extra_negative_is_appended(self, keyfile, monkeypatch):
        import base64 as b64
        runware.save_api_key('rk')
        sent = {}
        monkeypatch.setattr(runware.requests, 'post',
                            lambda url, json=None, timeout=None, headers=None:
                            sent.update(body=json) or FakeResp({'data': [{'imageBase64Data': b64.b64encode(b'X').decode()}]}))
        runware.generate_image('map', negative=runware.BATTLEMAP_NEGATIVE)
        neg = sent['body'][0]['negativePrompt']
        assert neg.startswith(runware.NEGATIVE_PROMPT) and 'isometric' in neg


class TestPrepSchematicSeed:
    def _schematic(self, mode='RGB'):
        from PIL import Image, ImageDraw
        import io as _io
        im = Image.new(mode, (256, 256), (255, 255, 255, 255) if mode == 'RGBA' else 'white')
        d = ImageDraw.Draw(im)
        d.line((20, 20, 236, 20), fill=(0, 0, 0, 255) if mode == 'RGBA' else 'black', width=6)
        buf = _io.BytesIO()
        im.save(buf, 'PNG')
        return buf.getvalue()

    def test_dark_base_with_lighter_walls(self):
        from PIL import Image
        import io as _io
        out = Image.open(_io.BytesIO(runware.prep_schematic_seed(self._schematic()))).convert('L')
        px = out.load()
        floor = [px[x, 200] for x in range(30, 220, 10)]
        wall = [px[x, 20] for x in range(30, 220, 10)]
        assert max(floor) < 90                      # murky, never white
        assert min(wall) > max(floor)               # walls read lighter than floor

    def test_rgba_schematic_handled(self):
        out = runware.prep_schematic_seed(self._schematic('RGBA'))
        assert out[:8] == b'\x89PNG\r\n\x1a\n'

    def test_garbage_returns_input(self):
        assert runware.prep_schematic_seed(b'not a png') == b'not a png'


class TestGenerateJson:
    def _ok(self, text):
        return FakeResp({'choices': [{'message': {'role': 'assistant', 'content': text}}]})

    def test_request_shape_and_reply(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        sent = {}
        def fake_post(url, json=None, timeout=None, headers=None):
            sent.update(url=url, body=json, headers=headers)
            return self._ok('{"walls": []}')
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        out = runware.generate_json('design a map', 'google:gemini@3-5-flash')
        assert out == '{"walls": []}'
        assert sent['url'] == runware.CHAT_URL
        assert sent['headers']['Authorization'] == 'Bearer rk'
        body = sent['body']
        assert body['model'] == 'google:gemini@3-5-flash'
        assert body['messages'][0]['content'][0] == {'type': 'text', 'text': 'design a map'}
        assert len(body['messages'][0]['content']) == 1

    def test_vision_image_attached(self, keyfile, monkeypatch):
        import base64 as b64
        runware.save_api_key('rk')
        sent = {}
        monkeypatch.setattr(runware.requests, 'post',
                            lambda url, json=None, timeout=None, headers=None:
                            sent.update(body=json) or self._ok('{}'))
        runware.generate_json('trace', image=b'PNGBYTES', mime='image/png')
        part = sent['body']['messages'][0]['content'][1]
        assert part['type'] == 'image_url'
        assert part['image_url']['url'] == 'data:image/png;base64,' + b64.b64encode(b'PNGBYTES').decode()

    def test_resolve_text_model(self, monkeypatch):
        import sql
        stored = {'runware_text_model': 'anthropic-claude-sonnet-4-6'}
        monkeypatch.setattr(sql, 'appsettingGet', lambda n, d=None: stored.get(n, d))
        assert runware.resolve_text_model() == 'anthropic-claude-sonnet-4-6'
        stored['runware_text_model'] = 'junk'
        assert runware.resolve_text_model() == runware.DEFAULT_TEXT_MODEL
        stored['runware_text_model'] = 'has spaces-bad'
        assert runware.resolve_text_model() == runware.DEFAULT_TEXT_MODEL

    def test_openai_error_shape_normalized(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'error': {'message': 'Invalid API key'}}, 401))
        with pytest.raises(runware.RunwareError, match='rejected the API key'):
            runware.generate_json('x')

    def test_empty_and_malformed_replies(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post', lambda *a, **k: self._ok(''))
        with pytest.raises(runware.RunwareError, match='empty reply'):
            runware.generate_json('x')
        monkeypatch.setattr(runware.requests, 'post', lambda *a, **k: FakeResp({'nope': 1}))
        with pytest.raises(runware.RunwareError, match='unexpected reply shape'):
            runware.generate_json('x')


class TestDistillImagePrompt:
    TOKEN_DOC = ("Please generate a creature token portrait for use on a TTRPG map.\n\n"
                 "## SUBJECT\nName: Pinky\nType: ooze\nSize: Small — occupies 1×1 grid square on the map\n"
                 "Description: a rotund pink jelly beast with stubby arms\nDetails: wide toothy grin\n\n"
                 "## TOKEN REQUIREMENTS (CRITICAL)\n- A single creature, centered.\n"
                 "- No text, numbers, labels, borders, or watermarks anywhere in the image.\n\n"
                 "## ART DIRECTION\n- High quality digital fantasy RPG creature art\n"
                 "- Dramatic lighting that highlights form and texture\n")

    def test_token_document_becomes_caption(self):
        out = runware.distill_image_prompt(self.TOKEN_DOC)
        assert out.startswith('fantasy character portrait for a game token')
        for kept in ('rotund pink jelly beast', 'wide toothy grin', 'ooze',
                     'Dramatic lighting that highlights form and texture'):
            assert kept in out
        low = out.lower()
        for banned in ('##', 'critical', 'requirements', 'pinky', 'name:'):
            assert banned not in low

    def test_topdown_token_framing(self):
        out = runware.distill_image_prompt(
            'Please generate a TOP-DOWN game token image for use on a TTRPG map.\n'
            '## SUBJECT\nType: sailing ship\n## ART DIRECTION\n- inked vessel art\n')
        assert out.startswith('top-down game token art')
        assert 'sailing ship' in out and 'inked vessel art' in out

    def test_texture_document(self):
        out = runware.distill_image_prompt(
            'Please generate a SEAMLESSLY TILEABLE material texture image.\n'
            '## SUBJECT\nweathered gray dungeon stone — a flat material surface\n'
            '## TECHNICAL REQUIREMENTS (CRITICAL)\n- SEAMLESS TILING: edges wrap.\n')
        assert out.startswith('seamless tileable texture')
        assert 'seamless tiling' not in out.lower().replace('seamless tileable texture', '')

    def test_battlemap_document_routes_to_map_distiller(self):
        out = runware.distill_image_prompt(
            'Please generate a strictly TOP-DOWN TTRPG battlemap background image.\n'
            '## SCENE\nEnvironment: sunken temple\n')
        assert out.startswith('flat top-down orthographic battle map')

    def test_caption_prompt_passes_through(self):
        assert runware.distill_image_prompt('a red dragon on a cliff') == 'a red dragon on a cliff'


class TestValidateImageModel:
    def _catalog(self, monkeypatch, results):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'data': [{'results': results}]}))

    def test_checkpoint_passes(self, keyfile, monkeypatch):
        self._catalog(monkeypatch, [{'air': 'google:4@3', 'category': 'checkpoint'}])
        assert runware.validate_image_model('google:4@3') == (True, None)

    def test_video_model_rejected_with_guidance(self, keyfile, monkeypatch):
        self._catalog(monkeypatch, [{'air': 'google:gemini@omni-flash', 'category': 'video'}])
        ok, why = runware.validate_image_model('google:gemini@omni-flash')
        assert not ok and 'VIDEO model' in why and 'google:4@3' in why

    def test_lora_rejected(self, keyfile, monkeypatch):
        self._catalog(monkeypatch, [{'air': 'civitai:1@2', 'category': 'lora'}])
        ok, why = runware.validate_image_model('civitai:1@2')
        assert not ok and 'LoRA' in why

    def test_unknown_or_unreachable_passes(self, keyfile, monkeypatch):
        self._catalog(monkeypatch, [])
        assert runware.validate_image_model('mystery:1@1') == (True, None)
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: (_ for _ in ()).throw(runware.requests.ConnectionError()))
        assert runware.validate_image_model('runware:400@3') == (True, None)

    def test_no_key_passes(self, keyfile):
        assert runware.validate_image_model('runware:400@3') == (True, None)


class TestUnsupportedParamRetry:
    def _reject(self, param):
        return FakeResp({'errors': [{'message': f"Unsupported use of '{param}' parameter. "
                                                'This parameter is not supported for the selected model.'}]}, 400)

    def test_strength_dropped_seed_kept(self, keyfile, monkeypatch):
        import base64 as b64
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE[runware.DEFAULT_MODEL] = False
        runware.save_api_key('rk')
        bodies = []
        def fake_post(url, json=None, timeout=None, headers=None):
            bodies.append(dict(json[0]))
            if 'strength' in json[0]:
                return self._reject('strength')
            return FakeResp({'data': [{'imageBase64Data': b64.b64encode(b'IMG').decode()}]})
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        info = {}
        raw, _ = runware.generate_image('paint', image=b'S', info=info)
        assert raw == b'IMG'
        assert 'seedImage' in bodies[-1] and 'strength' not in bodies[-1]
        assert info == {}                                # seed survived — no note

    def test_multiple_params_dropped_in_turn(self, keyfile, monkeypatch):
        import base64 as b64
        runware._MODEL_CACHE.clear()
        runware._MODEL_CACHE[runware.DEFAULT_MODEL] = False
        runware.save_api_key('rk')
        bodies = []
        def fake_post(url, json=None, timeout=None, headers=None):
            bodies.append(dict(json[0]))
            for p in ('strength', 'negativePrompt', 'seedImage', 'referenceImages'):
                if p in json[0]:
                    return self._reject(p)
            return FakeResp({'data': [{'imageBase64Data': b64.b64encode(b'IMG').decode()}]})
        monkeypatch.setattr(runware.requests, 'post', fake_post)
        info = {}
        raw, _ = runware.generate_image('paint', image=b'S',
                                        negative='isometric', info=info)
        assert raw == b'IMG' and info == {'seed_dropped': True}
        assert 'negativePrompt' not in bodies[-1] and 'seedImage' not in bodies[-1]
        assert 'referenceImages' not in bodies[-1]

    def test_unrelated_error_still_raises(self, keyfile, monkeypatch):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'errors': [{'message': 'model not found'}]}, 400))
        with pytest.raises(runware.RunwareError, match='model not found'):
            runware.generate_image('x', image=b'S')


class TestInstructionNative:
    def test_gemini_architecture_detected_and_cached(self, keyfile, monkeypatch):
        runware._MODEL_CACHE.clear()
        runware.save_api_key('rk')
        calls = []
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: calls.append(1) or FakeResp(
                                {'data': [{'results': [{'air': 'google:4@3',
                                                        'architecture': 'gemini_3_1_flash_image',
                                                        'category': 'checkpoint'}]}]}))
        assert runware.instruction_native('google:4@3') is True
        assert runware.instruction_native('google:4@3') is True
        assert len(calls) == 1                            # cached

    def test_flux_is_not(self, keyfile, monkeypatch):
        runware._MODEL_CACHE.clear()
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'data': [{'results': [
                                {'air': 'runware:400@3', 'architecture': 'flux2klein_base_9b'}]}]}))
        assert runware.instruction_native('runware:400@3') is False

    def test_unknown_defaults_to_diffusion(self, keyfile, monkeypatch):
        runware._MODEL_CACHE.clear()
        runware.save_api_key('rk')
        monkeypatch.setattr(runware.requests, 'post',
                            lambda *a, **k: FakeResp({'data': [{'results': []}]}))
        assert runware.instruction_native('mystery:1@1') is False


class TestNormalizeTextModel:
    IDS = ['google-gemini-3-6-flash', 'google-gemini-3-5-flash',
           'anthropic-claude-opus-4-8', 'openai-gpt-5-5']

    def _with_list(self, monkeypatch, ids):
        runware.save_api_key('rk')
        monkeypatch.setattr(runware, 'list_text_models', lambda timeout=None: ids)

    def test_slug_accepted_verbatim(self, keyfile, monkeypatch):
        self._with_list(monkeypatch, self.IDS)
        assert runware.normalize_text_model('google-gemini-3-6-flash') == ('google-gemini-3-6-flash', None)

    def test_air_form_converted(self, keyfile, monkeypatch):
        self._with_list(monkeypatch, self.IDS)
        assert runware.normalize_text_model('google:gemini@3.6-flash') == ('google-gemini-3-6-flash', None)
        assert runware.normalize_text_model('anthropic:claude@opus-4.8') == ('anthropic-claude-opus-4-8', None)

    def test_unknown_fails_with_suggestions(self, keyfile, monkeypatch):
        self._with_list(monkeypatch, self.IDS)
        slug, why = runware.normalize_text_model('google:gemini@9.9-ultra')
        assert slug is None and 'google-gemini-3-6-flash' in why

    def test_unverifiable_accepts_as_is(self, keyfile, monkeypatch):
        self._with_list(monkeypatch, [])
        assert runware.normalize_text_model('whatever-model') == ('whatever-model', None)

    def test_spaces_rejected(self, keyfile, monkeypatch):
        self._with_list(monkeypatch, self.IDS)
        slug, why = runware.normalize_text_model('bad value')
        assert slug is None and 'no spaces' in why
