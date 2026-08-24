"""/ttrpg/ai endpoints: key masking, DM gating, floorplan generate (no DB
writes), trace bg validation, map-art save via _store_bg_bytes, texture
passthrough, and the video job endpoints. All Gemini calls monkeypatched —
no network, no quota."""
import base64
import io
import json
import os

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager
from PIL import Image

from extensions import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _png_bytes(size=32, color=(90, 70, 50)):
    buf = io.BytesIO()
    Image.new('RGB', (size, size), color).save(buf, 'PNG')
    return buf.getvalue()


@pytest.fixture()
def ai_app(tmp_path, monkeypatch):
    import gemini
    import routes.battlemap as bm_mod
    from models.user import tblUsers
    from models.ttrpg import tblSessions, tblBattleMaps
    from routes.ai import ai_bp
    import routes.textures as tex_mod

    import runware
    import sql
    monkeypatch.setattr(gemini, '_KEY_PATH', str(tmp_path / 'key'))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr(runware, '_KEY_PATH', str(tmp_path / 'rkey'))
    monkeypatch.delenv('RUNWARE_API_KEY', raising=False)
    # Isolate from the box's REAL tblAppSettings: _image_provider()/resolve_model()
    # read appsettings, and the live DB may have Runware selected.
    monkeypatch.setattr(sql, 'appsettingGet', lambda name, default=None: default)
    # uploads land in tmp dirs, not the repo
    monkeypatch.setattr(bm_mod, 'UPLOAD_FOLDER',
                        os.path.relpath(str(tmp_path / 'bg'), REPO))
    monkeypatch.setattr(tex_mod, 'UPLOAD_FOLDER',
                        os.path.relpath(str(tmp_path / 'tex'), REPO))
    monkeypatch.setattr(bm_mod, '_push_map_state', lambda bm: None)

    a = Flask(__name__, root_path=REPO)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager()
    login.init_app(a)
    a.register_blueprint(ai_bp)
    a.register_blueprint(bm_mod.battlemap_bp)
    a.register_blueprint(tex_mod.textures_bp)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient

    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        player = tblUsers(username='pl', display_name='PL', password_hash='x',
                          role='player', active=1,
                          created_at='2026-01-01 00:00:00')
        db.session.add_all([dm, player])
        db.session.flush()
        sess = tblSessions(title='S', status='planning',
                           created_at='2026-01-01 00:00:00')
        db.session.add(sess)
        db.session.flush()
        bm = tblBattleMaps(session_id=sess.session_id, name='M', grid_cols=20,
                           grid_rows=20, created_at='2026-01-01 00:00:00')
        db.session.add(bm)
        db.session.commit()
        yield a, dm, player, bm.map_id, gemini
        db.session.remove()
        db.drop_all()


def _dm(a, dm):
    return a.test_client(user=dm)


class TestStatusAndGating:
    def test_status_never_leaks_the_key(self, ai_app):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('sk-supersecret-abc')
        with _dm(a, dm) as c:
            r = c.get('/ttrpg/ai/status')
        assert r.get_json()['configured'] is True
        assert b'sk-supersecret-abc' not in r.data

    def test_unconfigured_status_and_endpoint_400(self, ai_app):
        a, dm, _, map_id, _ = ai_app
        with _dm(a, dm) as c:
            assert c.get('/ttrpg/ai/status').get_json()['configured'] is False
            r = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'x', 'mode': 'design',
                             'map_id': map_id})
        assert r.status_code == 400
        assert 'Utilities' in r.get_json()['error']

    def test_player_redirected(self, ai_app):
        a, _, player, _, gemini = ai_app
        gemini.save_api_key('k')
        with a.test_client(user=player) as c:
            assert c.get('/ttrpg/ai/status').status_code == 302
            assert c.post('/ttrpg/ai/image-generate',
                          json={'prompt_text': 'x'}).status_code == 302


class TestFloorplanGenerate:
    def test_design_returns_json_and_writes_nothing(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')
        monkeypatch.setattr(gemini, 'generate_json',
                            lambda prompt, model, image=None, mime=None:
                            '{"walls": []}')
        from models.ttrpg import tblBattleMapFloorplans
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'design', 'mode': 'design',
                             'map_id': map_id}).get_json()
        assert d['ok'] and d['json_text'] == '{"walls": []}'
        with a.app_context():
            assert tblBattleMapFloorplans.query.count() == 0

    def test_trace_requires_still_bg(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')
        with _dm(a, dm) as c:
            r = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'trace', 'mode': 'trace',
                             'map_id': map_id})
            assert r.status_code == 400
            assert 'no background' in r.get_json()['error']
        # video bg also refused (the fixture's app context is still active,
        # so this mutation is visible to the next request)
        from models.ttrpg import tblBattleMaps
        bm = db.session.get(tblBattleMaps, map_id)
        bm.bg_image = 'clip.mp4'
        db.session.commit()
        with _dm(a, dm) as c:
            r = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'trace', 'mode': 'trace',
                             'map_id': map_id})
            assert r.status_code == 400
            assert 'VIDEO' in r.get_json()['error']

    def test_trace_attaches_the_bg_image(self, ai_app, monkeypatch, tmp_path):
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')
        import routes.battlemap as bm_mod
        folder = os.path.join(REPO, bm_mod.UPLOAD_FOLDER)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'art.png'), 'wb') as f:
            f.write(_png_bytes())
        from models.ttrpg import tblBattleMaps
        bm = db.session.get(tblBattleMaps, map_id)
        bm.bg_image = 'art.png'
        db.session.commit()
        seen = {}

        def fake(prompt, model, image=None, mime=None):
            seen['image'], seen['mime'] = image, mime
            return '{}'
        monkeypatch.setattr(gemini, 'generate_json', fake)
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'trace', 'mode': 'trace',
                             'map_id': map_id}).get_json()
        assert d['ok']
        assert seen['image'] == _png_bytes() and seen['mime'] == 'image/png'


class TestMapArt:
    def test_returns_preview_bytes_without_storing(self, ai_app, monkeypatch):
        """Preview-before-save: the endpoint hands the image back; nothing
        touches the map until the browser accepts it via bg-paste."""
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')
        png = _png_bytes(64)
        monkeypatch.setattr(gemini, 'generate_image',
                            lambda prompt, model, image=None, mime=None:
                            (png, 'png'))
        from models.ttrpg import tblBattleMaps
        with a.app_context():
            before = db.session.get(tblBattleMaps, map_id).bg_image
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/ai/map-art/{map_id}',
                       json={'prompt_text': 'paint',
                             'schematic_png_b64':
                                 base64.b64encode(_png_bytes()).decode()}
                       ).get_json()
        assert d['ok'] and d['ext'] == 'png' and d['map_id'] == map_id
        assert base64.b64decode(d['image_b64']) == png
        assert 'url' not in d and 'filename' not in d
        with a.app_context():
            assert db.session.get(tblBattleMaps, map_id).bg_image == before   # untouched

    def test_accepted_preview_saves_through_bg_paste(self, ai_app):
        a, dm, _, map_id, gemini = ai_app
        import io as _io
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/battlemap/{map_id}/bg-paste',
                       data={'ext': 'png',
                             'bg_image': (_io.BytesIO(_png_bytes(64)), 'gemini.png')},
                       content_type='multipart/form-data').get_json()
        assert d['ok'] and d['is_video'] is False and d['url'].startswith('/static/')
        from models.ttrpg import tblBattleMaps
        import routes.battlemap as bm_mod
        with a.app_context():
            bm = db.session.get(tblBattleMaps, map_id)
            assert bm.bg_image == d['filename']
            assert os.path.exists(os.path.join(REPO, bm_mod.UPLOAD_FOLDER,
                                               d['filename']))

    def test_gemini_error_surfaces(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')

        def boom(prompt, model, image=None, mime=None):
            raise gemini.GeminiError('Blocked by safety filter')
        monkeypatch.setattr(gemini, 'generate_image', boom)
        with _dm(a, dm) as c:
            r = c.post(f'/ttrpg/ai/map-art/{map_id}',
                       json={'prompt_text': 'paint'})
        assert r.status_code == 502
        assert 'safety' in r.get_json()['error'].lower()


class TestMapVideo:
    def test_job_lifecycle_saves_video_bg(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        gemini.save_api_key('k')

        # Run the job synchronously: call on_success right away.
        def fake_start(prompt, model, image=None, mime=None, on_success=None):
            result = on_success(b'MP4BYTES', 'mp4')
            gemini._jobs['jobX'] = {'status': 'done', 'created': 0,
                                    'error': None, 'result': result}
            return 'jobX'
        monkeypatch.setattr(gemini, 'start_video_job', fake_start)
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/ai/map-video/{map_id}',
                       json={'prompt_text': 'animate'}).get_json()
            assert d['ok'] and d['job_id'] == 'jobX'
            j = c.get('/ttrpg/ai/job/jobX').get_json()
        assert j['status'] == 'done'
        assert j['result']['is_video'] is True
        import routes.battlemap as bm_mod
        path = os.path.join(REPO, bm_mod.UPLOAD_FOLDER, j['result']['filename'])
        with open(path, 'rb') as f:
            assert f.read() == b'MP4BYTES'   # videos stored verbatim

    def test_unknown_job_404(self, ai_app):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        with _dm(a, dm) as c:
            r = c.get('/ttrpg/ai/job/ghost')
        assert r.status_code == 404
        assert 'restarted' in r.get_json()['error']


class TestTextureGenerate:
    def test_returns_preview_bytes_library_untouched(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        png = _png_bytes()
        monkeypatch.setattr(gemini, 'generate_image',
                            lambda prompt, model, image=None, mime=None:
                            (png, 'png'))
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/texture-generate',
                       json={'prompt_text': 'moss', 'name': 'AI Moss',
                             'category': 'stone', 'tile_ft': 6}).get_json()
            assert d['ok'] and d['name'] == 'ai_moss'        # normalised slug
            assert base64.b64decode(d['image_b64']) == png
            man = c.get('/ttrpg/textures/manifest').get_json()
        assert not any(t['name'] == 'ai_moss' for t in man['textures'])   # not saved yet

    def test_accepted_preview_saves_through_paste(self, ai_app):
        a, dm, _, _, gemini = ai_app
        import io as _io
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/textures/paste',
                       data={'name': 'ai_moss', 'category': 'stone', 'tile_ft': '6',
                             'source': 'ai', 'ext': 'png',
                             'image': (_io.BytesIO(_png_bytes()), 'pasted')},
                       content_type='multipart/form-data').get_json()
            assert d['ok'] and d['name'] == 'ai_moss'
            man = c.get('/ttrpg/textures/manifest').get_json()
        mine = next(t for t in man['textures'] if t['name'] == 'ai_moss')
        assert mine['source'] == 'ai' and mine['tile_ft'] == 6.0

    def test_slug_collision_rejected_before_generating(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        calls = []
        monkeypatch.setattr(gemini, 'generate_image',
                            lambda prompt, model, image=None, mime=None:
                            calls.append(1) or (_png_bytes(), 'png'))
        with _dm(a, dm) as c:
            r = c.post('/ttrpg/ai/texture-generate',
                       json={'prompt_text': 'x', 'name': 'flagstone',
                             'category': 'floor', 'tile_ft': 5})
        assert r.status_code == 400
        assert 'already exists' in r.get_json()['error']
        assert calls == []                                   # no generation paid for


class TestImageGenerate:
    def test_returns_b64(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        monkeypatch.setattr(gemini, 'generate_image',
                            lambda prompt, model, image=None, mime=None:
                            (b'PORTRAIT', 'png'))
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/image-generate',
                       json={'prompt_text': 'a hero'}).get_json()
        assert d['ok'] and d['ext'] == 'png'
        assert base64.b64decode(d['image_b64']) == b'PORTRAIT'


class TestImageProviderRunware:
    """image_provider='runware' routes every IMAGE flow through runware.py;
    text/video endpoints never look at it. Settings are faked at the
    sql.appsettingGet seam (the real table lives in the live DB)."""

    def _use_runware(self, monkeypatch, extra=None):
        import sql
        vals = {'image_provider': 'runware', 'runware_model': 'runware:100@1'}
        vals.update(extra or {})
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: vals.get(name, default))

    def test_image_generate_uses_runware(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        runware.save_api_key('rk')
        calls = {}
        def fake(prompt, model=None, image=None, mime=None, size=None, timeout=None, info=None, negative=None):
            calls.update(prompt=prompt, model=model, image=image, size=size)
            return b'RWIMG', 'png'
        monkeypatch.setattr(runware, 'generate_image', fake)
        def boom(*a, **k):
            raise AssertionError('gemini must not be called')
        monkeypatch.setattr(gemini, 'generate_image', boom)
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/image-generate',
                       json={'prompt_text': 'a knight'}).get_json()
        assert d['ok'] and base64.b64decode(d['image_b64']) == b'RWIMG'
        assert d['model'] == 'runware runware:100@1'
        assert calls['model'] == 'runware:100@1' and calls['image'] is None

    def test_runware_selected_without_key_fails_before_generating(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        called = []
        monkeypatch.setattr(runware, 'generate_image',
                            lambda *a, **k: called.append(1) or (b'x', 'png'))  # noqa
        with _dm(a, dm) as c:
            r = c.post('/ttrpg/ai/image-generate', json={'prompt_text': 'x'})
        assert r.status_code == 400
        assert 'Runware' in r.get_json()['error']
        assert called == []

    def test_map_art_passes_schematic_and_grid_size(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        runware.save_api_key('rk')
        calls = {}
        def fake(prompt, model=None, image=None, mime=None, size=None, timeout=None, info=None, negative=None):
            calls.update(image=image, mime=mime, size=size)
            return b'ART', 'png'
        monkeypatch.setattr(runware, 'generate_image', fake)
        monkeypatch.setattr(runware, 'prep_schematic_seed', lambda b: b'PREPPED:' + b)
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/ai/map-art/{map_id}',
                       json={'prompt_text': 'paint',
                             'schematic_png_b64': base64.b64encode(b'SCHEMATIC').decode()}
                       ).get_json()
        assert d['ok'] and base64.b64decode(d['image_b64']) == b'ART'
        assert calls['image'] == b'PREPPED:SCHEMATIC' and calls['mime'] == 'image/png'
        # the size hint is derived from the map's own grid ratio
        from models.ttrpg import tblBattleMaps
        with a.app_context():
            bm = db.session.get(tblBattleMaps, map_id)
            assert calls['size'] == runware.size_for_ratio(bm.grid_cols, bm.grid_rows)

    def test_gemini_stays_default_and_serves_text(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        monkeypatch.setattr(gemini, 'generate_image',
                            lambda prompt, model, image=None, mime=None: (b'G', 'png'))
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/image-generate', json={'prompt_text': 'x'}).get_json()
        assert d['ok'] and base64.b64decode(d['image_b64']) == b'G'

    def test_status_reports_provider_and_readiness(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        with _dm(a, dm) as c:
            d = c.get('/ttrpg/ai/status').get_json()
            assert d['image_provider'] == 'runware'
            assert d['image_ready'] is False and d['runware_configured'] is False
            runware.save_api_key('rk')
            d = c.get('/ttrpg/ai/status').get_json()
            assert d['image_ready'] is True and d['runware_configured'] is True

    def test_seed_dropped_surfaces_a_note(self, ai_app, monkeypatch):
        """A Runware model without image-input support: the schematic is
        dropped with a retry and the response carries a DM-facing note."""
        a, dm, _, map_id, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        runware.save_api_key('rk')
        def fake(prompt, model=None, image=None, mime=None, size=None, timeout=None, info=None, negative=None):
            if info is not None:
                info['seed_dropped'] = True
            return b'ART', 'png'
        monkeypatch.setattr(runware, 'generate_image', fake)
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/ai/map-art/{map_id}',
                       json={'prompt_text': 'paint',
                             'schematic_png_b64': base64.b64encode(b'S').decode()}
                       ).get_json()
        assert d['ok'] and 'schematic was ignored' in d['note']

    def test_map_art_prompt_is_distilled_for_runware(self, ai_app, monkeypatch):
        a, dm, _, map_id, gemini = ai_app
        import runware
        self._use_runware(monkeypatch)
        runware.save_api_key('rk')
        seen = {}
        def fake(prompt, model=None, image=None, mime=None, size=None, timeout=None, info=None, negative=None):
            seen['prompt'] = prompt
            return b'ART', 'png'
        monkeypatch.setattr(runware, 'generate_image', fake)
        gem_prompt = ('Please generate ... EXACTLY reproduces the ATTACHED schematic floorplan '
                      '— see LAYOUT MATCH below.\n## SCENE\nEnvironment: flooded sewer\n'
                      '## LAYOUT MATCH\n- wall from (0,0) to (9,0)')
        with _dm(a, dm) as c:
            d = c.post(f'/ttrpg/ai/map-art/{map_id}',
                       json={'prompt_text': gem_prompt}).get_json()
        assert d['ok']
        assert 'flooded sewer' in seen['prompt']
        assert 'schematic' not in seen['prompt'].lower()


class TestTextProviderRunware:
    """text_provider='runware' routes the floorplan design/trace through
    runware.generate_json; the image provider setting is independent."""

    def _use_runware_text(self, monkeypatch, extra=None):
        import sql
        vals = {'text_provider': 'runware', 'runware_text_model': 'google:gemini@3-5-flash'}
        vals.update(extra or {})
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None: vals.get(name, default))

    def test_design_uses_runware(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        self._use_runware_text(monkeypatch)
        runware.save_api_key('rk')
        seen = {}
        def fake(prompt, model=None, image=None, mime=None, timeout=None):
            seen.update(prompt=prompt, model=model, image=image)
            return '{"walls": []}'
        monkeypatch.setattr(runware, 'generate_json', fake)
        monkeypatch.setattr(gemini, 'generate_json',
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError('gemini must not be called')))
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'design'}).get_json()
        assert d['ok'] and d['json_text'] == '{"walls": []}'
        assert d['model'] == 'runware google:gemini@3-5-flash'
        assert seen['image'] is None

    def test_runware_text_without_key_fails_first(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        self._use_runware_text(monkeypatch)
        with _dm(a, dm) as c:
            r = c.post('/ttrpg/ai/floorplan-generate', json={'prompt_text': 'x'})
        assert r.status_code == 400 and 'Runware' in r.get_json()['error']

    def test_status_reports_text_provider(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        self._use_runware_text(monkeypatch)
        runware.save_api_key('rk')
        with _dm(a, dm) as c:
            d = c.get('/ttrpg/ai/status').get_json()
        assert d['text_provider'] == 'runware' and d['text_ready'] is True

    def test_gemini_default_untouched(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        gemini.save_api_key('k')
        monkeypatch.setattr(gemini, 'generate_json',
                            lambda prompt, model, image=None, mime=None: '{"ok": 1}')
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/floorplan-generate',
                       json={'prompt_text': 'design'}).get_json()
        assert d['ok'] and d['json_text'] == '{"ok": 1}'

    def test_image_generate_prompt_distilled_for_runware(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None:
                            {'image_provider': 'runware'}.get(name, default))
        runware.save_api_key('rk')
        seen = {}
        def fake(prompt, model=None, image=None, mime=None, size=None, timeout=None, info=None, negative=None):
            seen['prompt'] = prompt
            return b'X', 'png'
        monkeypatch.setattr(runware, 'generate_image', fake)
        doc = ('Please generate a creature token portrait for use on a TTRPG map.\n'
               '## SUBJECT\nName: Zed\nDescription: a bone golem\n'
               '## TOKEN REQUIREMENTS (CRITICAL)\n- centered\n')
        with _dm(a, dm) as c:
            d = c.post('/ttrpg/ai/image-generate', json={'prompt_text': doc}).get_json()
        assert d['ok']
        assert 'bone golem' in seen['prompt'] and '##' not in seen['prompt']

    def test_status_reports_resolved_models(self, ai_app, monkeypatch):
        a, dm, _, _, gemini = ai_app
        import runware
        import sql
        monkeypatch.setattr(sql, 'appsettingGet',
                            lambda name, default=None:
                            {'image_provider': 'runware', 'runware_model': 'runware:400@3',
                             'text_provider': 'gemini'}.get(name, default))
        with _dm(a, dm) as c:
            d = c.get('/ttrpg/ai/status').get_json()
        assert d['image_model'] == 'runware:400@3'
        assert d['text_model'] == gemini.resolve_model('text')
