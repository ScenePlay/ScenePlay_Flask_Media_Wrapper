"""PDF handouts: upload validation (magic number, size), listing, rename,
delete (row + file), guarded file serving, reader page, progress bookmark,
and DM gating."""
import io
import os

import pytest
from flask import Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n'


def _make_app():
    from flask import Blueprint
    from routes.handouts import handouts_bp
    a = Flask(__name__, root_path=REPO)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    LoginManager().init_app(a)
    a.register_blueprint(handouts_bp)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient
    return a


@pytest.fixture()
def ho_app(tmp_path, monkeypatch):
    from models.user import tblUsers
    import routes.handouts as mod
    monkeypatch.setattr(mod, 'UPLOAD_FOLDER', os.path.relpath(str(tmp_path), REPO))
    a = _make_app()
    with a.app_context():
        db.create_all()

        @a.login_manager.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        pl = tblUsers(username='pl', display_name='PL', password_hash='x',
                      role='player', active=1, created_at='2026-01-01 00:00:00')
        db.session.add_all([dm, pl])
        db.session.commit()
        yield a, dm, pl, tmp_path
        db.session.remove()
        db.drop_all()


def _upload(c, data=PDF, name='Monster Manual.pdf', title=None):
    form = {'pdf': (io.BytesIO(data), name)}
    if title is not None:
        form['title'] = title
    return c.post('/handouts/upload?format=json', data=form,
                  content_type='multipart/form-data')


class TestUpload:
    def test_pdf_lands_on_disk_with_title_from_filename(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c)
            assert r.status_code == 200, r.data
            h = r.get_json()['handout']
            assert h['title'] == 'Monster Manual'
            assert h['filename'].endswith('.pdf') and len(h['filename']) == 36
            assert (tmp / h['filename']).read_bytes() == PDF
            assert h['page_count'] is None and h['last_page'] == 1

    def test_explicit_title_wins_and_is_trimmed(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='  The   Duke\'s  Letter ').get_json()['handout']
            assert h['title'] == "The Duke's Letter"

    def test_rejects_non_pdf_by_magic_not_extension(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c, data=b'\x89PNG....', name='sneaky.pdf')
            assert r.status_code == 400 and 'not a PDF' in r.get_json()['error']
            r = _upload(c, data=b'', name='empty.pdf')
            assert r.status_code == 400
            r = c.post('/handouts/upload?format=json', data={}, content_type='multipart/form-data')
            assert r.status_code == 400
        assert not [f for f in os.listdir(tmp) if f.endswith('.pdf')]

    def test_rejects_oversize(self, ho_app, monkeypatch):
        import routes.handouts as mod
        monkeypatch.setattr(mod, 'MAX_PDF_BYTES', 10)
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            r = _upload(c)
            assert r.status_code == 400 and 'larger than' in r.get_json()['error']

    def test_form_post_redirects_to_list(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            r = c.post('/handouts/upload', data={'pdf': (io.BytesIO(PDF), 'x.pdf')},
                       content_type='multipart/form-data')
            assert r.status_code == 302 and r.headers['Location'].endswith('/handouts/')


class TestManage:
    def test_file_served_inline_and_as_download(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c, title='PHB').get_json()['handout']['id']
            r = c.get(f'/handouts/{hid}/file')
            assert r.status_code == 200 and r.mimetype == 'application/pdf'
            assert r.data == PDF and 'attachment' not in (r.headers.get('Content-Disposition') or '')
            r = c.get(f'/handouts/{hid}/file?dl=1')
            assert 'attachment' in r.headers['Content-Disposition'] and 'PHB.pdf' in r.headers['Content-Disposition']
            assert c.get('/handouts/999/file').status_code == 404

    def test_reader_page_and_missing_file(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='PHB').get_json()['handout']
            r = c.get(f"/handouts/{h['id']}/read")
            assert r.status_code == 200
            body = r.data.decode()
            assert 'pdfjs/pdf.min.mjs' in body and f"/handouts/{h['id']}/file" in body
            assert 'startPage: 1' in body
            os.remove(tmp / h['filename'])
            r = c.get(f"/handouts/{h['id']}/read")
            assert r.status_code == 302                      # back to the list with a flash
            assert c.get(f"/handouts/{h['id']}/file").status_code == 404

    def test_progress_bookmark_and_clamp(self, ho_app):
        a, dm, _, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
            r = c.post(f'/handouts/{hid}/progress', json={'page_count': 320, 'page': 41})
            assert r.get_json() == {'ok': True, 'last_page': 41, 'page_count': 320}
            r = c.post(f'/handouts/{hid}/progress', json={'page': 999})
            assert r.get_json()['last_page'] == 320
            r = c.post(f'/handouts/{hid}/progress', json={'page': 'junk', 'page_count': -4})
            assert r.get_json() == {'ok': True, 'last_page': 320, 'page_count': 320}
            body = c.get(f'/handouts/{hid}/read').data.decode()
            assert 'startPage: 320' in body
            assert c.post('/handouts/999/progress', json={'page': 1}).status_code == 404

    def test_rename_delete_and_listing(self, ho_app):
        a, dm, _, tmp = ho_app
        with a.test_client(user=dm) as c:
            h = _upload(c, title='Old').get_json()['handout']
            r = c.post(f"/handouts/{h['id']}/rename", json={'title': ' New  Name '})
            assert r.get_json() == {'ok': True, 'title': 'New Name'}
            r = c.post(f"/handouts/{h['id']}/rename", json={'title': '   '})
            assert r.get_json()['title'] == 'New Name'         # blank keeps the old title
            r = c.post(f"/handouts/{h['id']}/delete?format=json")
            assert r.get_json() == {'ok': True}
            assert not (tmp / h['filename']).exists()
            assert c.post(f"/handouts/{h['id']}/delete?format=json").status_code == 404


def _forget_login():
    # The fixture holds one app context across the whole test, so Flask-Login's
    # per-context user cache (g._login_user) would otherwise carry the DM
    # into the player/anonymous clients below.
    from flask import g
    g.pop('_login_user', None)


class TestGating:
    def test_player_and_anonymous_are_bounced(self, ho_app):
        a, dm, pl, _ = ho_app
        with a.test_client(user=dm) as c:
            hid = _upload(c).get_json()['handout']['id']
        _forget_login()
        with a.test_client(user=pl) as c:
            for path in (f'/handouts/{hid}/file', f'/handouts/{hid}/read', '/handouts/'):
                r = c.get(path)
                assert r.status_code == 302 and '/login' in r.headers['Location']
            assert c.post(f'/handouts/{hid}/delete').status_code == 302
            assert _upload(c).status_code == 302
        _forget_login()
        with a.test_client() as c:
            r = c.get(f'/handouts/{hid}/file')
            assert r.status_code in (302, 401)
