"""Texture library endpoints: manifest union (builtin + DB), upload/paste
validation, slug collisions, delete guards, DM gating."""
import io
import os

import pytest
from flask import Flask
from flask_login import FlaskLoginClient, LoginManager
from PIL import Image

from extensions import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _png_bytes(size=64, color=(120, 90, 60)):
    img = Image.new('RGB', (size, size), color)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return buf


def _make_app(tmp_path):
    from flask import Blueprint
    from routes.textures import textures_bp
    a = Flask(__name__, root_path=REPO)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager()
    login.init_app(a)
    a.register_blueprint(textures_bp)
    # dm_required redirects to auth.login — give the minimal app a stub
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient
    return a


@pytest.fixture()
def tex_app(tmp_path, monkeypatch):
    from models.user import tblUsers
    import routes.textures as tex_mod
    # uploads land in a temp dir, not the repo
    monkeypatch.setattr(tex_mod, 'UPLOAD_FOLDER',
                        os.path.relpath(str(tmp_path), REPO))
    a = _make_app(tmp_path)
    with a.app_context():
        db.create_all()

        @a.login_manager.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        player = tblUsers(username='pl', display_name='PL', password_hash='x',
                          role='player', active=1,
                          created_at='2026-01-01 00:00:00')
        db.session.add_all([dm, player])
        db.session.commit()
        yield a, dm, player
        db.session.remove()
        db.drop_all()


class TestManifest:
    def test_builtin_manifest_served_to_players(self, tex_app):
        a, dm, player = tex_app
        with a.test_client(user=player) as c:
            d = c.get('/ttrpg/textures/manifest').get_json()
        assert d['ok']
        names = {t['name'] for t in d['textures']}
        # the repo starter set is present with categories and urls
        assert 'flagstone' in names and 'oak_planks' in names
        fl = next(t for t in d['textures'] if t['name'] == 'flagstone')
        assert fl['source'] == 'builtin' and fl['tile_ft'] > 0
        assert fl['url'].startswith('/static/textures/builtin/')

    def test_upload_appears_in_manifest(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'My Moss', 'category': 'stone', 'tile_ft': '8',
                'image': (_png_bytes(), 'moss.png'),
            })
            assert r.get_json()['ok'], r.get_json()
            assert r.get_json()['name'] == 'my_moss'   # slugified
            d = c.get('/ttrpg/textures/manifest').get_json()
        mine = next(t for t in d['textures'] if t['name'] == 'my_moss')
        assert mine['source'] == 'upload' and mine['tile_ft'] == 8.0


class TestUploadValidation:
    def test_bad_slug_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'BAD!SLUG', 'image': (_png_bytes(), 'x.png')})
        assert r.status_code == 400

    def test_builtin_name_collision_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'flagstone', 'image': (_png_bytes(), 'x.png')})
        assert r.status_code == 400
        assert 'already exists' in r.get_json()['error']

    def test_duplicate_upload_rejected(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'dupe', 'image': (_png_bytes(), 'x.png')})
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'dupe', 'image': (_png_bytes(), 'x.png')})
        assert r.status_code == 400

    def test_downscaled_to_cap(self, tex_app, tmp_path):
        import routes.textures as tex_mod
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'big', 'image': (_png_bytes(2048), 'big.png')})
            assert r.get_json()['ok']
        from models.ttrpg import tblTextures
        with a.app_context():
            row = tblTextures.query.filter_by(name='big').first()
            path = os.path.join(REPO, tex_mod.UPLOAD_FOLDER, row.filename)
            with Image.open(path) as im:
                assert max(im.size) <= tex_mod.MAX_TEXTURE_DIM

    def test_paste_endpoint(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/paste', data={
                'name': 'pasted', 'category': 'wood', 'source': 'ai',
                'ext': 'png', 'image': (_png_bytes(), 'blob')})
            assert r.get_json()['ok']
            d = c.get('/ttrpg/textures/manifest').get_json()
        mine = next(t for t in d['textures'] if t['name'] == 'pasted')
        assert mine['source'] == 'ai'


class TestDelete:
    def test_delete_own_texture_removes_row_and_file(self, tex_app):
        import routes.textures as tex_mod
        from models.ttrpg import tblTextures
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'doomed', 'image': (_png_bytes(), 'x.png')})
            with a.app_context():
                row = tblTextures.query.filter_by(name='doomed').first()
                path = os.path.join(REPO, tex_mod.UPLOAD_FOLDER, row.filename)
            assert os.path.exists(path)
            r = c.post('/ttrpg/textures/doomed/delete')
            assert r.get_json()['ok']
        assert not os.path.exists(path)
        with a.app_context():
            assert tblTextures.query.filter_by(name='doomed').first() is None

    def test_builtin_not_deletable(self, tex_app):
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/textures/flagstone/delete')
        assert r.status_code == 404


class TestGating:
    def test_player_cannot_write(self, tex_app):
        a, _, player = tex_app
        with a.test_client(user=player) as c:
            r = c.post('/ttrpg/textures/upload', data={
                'name': 'nope', 'image': (_png_bytes(), 'x.png')})
            assert r.status_code == 302   # dm_required redirects to login
            r2 = c.post('/ttrpg/textures/flagstone/delete')
            assert r2.status_code == 302

    def test_anonymous_cannot_read(self, tex_app):
        a, _, _ = tex_app
        with a.test_client() as c:
            r = c.get('/ttrpg/textures/manifest')
        assert r.status_code in (302, 401)


class TestTexturePaths:
    def test_paths_resolve_builtin_and_uploads(self, tex_app):
        import routes.textures as tex_mod
        a, dm, _ = tex_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/textures/upload', data={
                'name': 'mine', 'tile_ft': '7', 'image': (_png_bytes(), 'x.png')})
        with a.app_context(), a.test_request_context():
            paths = tex_mod.texture_paths(['flagstone', 'mine', 'ghost'])
        assert 'ghost' not in paths
        assert paths['flagstone']['path'].endswith('builtin/flagstone.jpg')
        assert os.path.exists(paths['flagstone']['path'])
        assert paths['mine']['tile_ft'] == 7.0
        assert os.path.exists(paths['mine']['path'])
