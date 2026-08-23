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

    monkeypatch.setattr(gemini, '_KEY_PATH', str(tmp_path / 'key'))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
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
