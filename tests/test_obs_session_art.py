"""Per-session show art, video loops, and settings that save themselves.

Art belongs to the ACTIVE session when one is running — each session keeps its
own pre/post/title/background set — falling back to the shared default so a
session that never chose art still looks right.
"""
import io
import os

import pytest
from flask import Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db
from models.ttrpg import tblSessions

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    sets = lambda name, value: store.__setitem__(name, str(value))  # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    monkeypatch.setattr(sql, 'appsettingSet', sets)
    monkeypatch.setattr(ro, 'appsettingSet', sets)
    return store


def _session(sid=7, status='active'):
    s = tblSessions(session_id=sid, title=f'S{sid}', status=status,
                    created_at='2026-01-01 00:00:00')
    db.session.add(s)
    db.session.commit()
    return s


class TestArtSetting:
    def test_session_art_wins_over_the_shared_default(self, app, settings):
        import routes.obs as ro
        _session(7)
        settings['obs_post_image'] = 'shared.jpg'
        settings['obs_post_image:s7'] = 'mine.jpg'
        assert ro.art_setting('obs_post_image') == 'mine.jpg'

    def test_falls_back_to_the_shared_default(self, app, settings):
        """A session that never chose art must still look right."""
        import routes.obs as ro
        _session(7)
        settings['obs_post_image'] = 'shared.jpg'
        assert ro.art_setting('obs_post_image') == 'shared.jpg'

    def test_no_active_session_reads_the_shared_default(self, app, settings):
        import routes.obs as ro
        _session(7, status='ended')
        settings['obs_post_image'] = 'shared.jpg'
        settings['obs_post_image:s7'] = 'mine.jpg'
        assert ro.art_setting('obs_post_image') == 'shared.jpg', \
            'an ENDED session must not keep supplying its art'

    def test_sessions_do_not_share_overrides(self, app, settings):
        import routes.obs as ro
        _session(8)
        settings['obs_post_image:s7'] = 'other-sessions.jpg'
        settings['obs_post_image'] = 'shared.jpg'
        assert ro.art_setting('obs_post_image') == 'shared.jpg'

    def test_slot_rows_flag_whose_art_it_is(self, app, settings):
        import routes.obs as ro
        _session(7)
        settings['obs_post_image:s7'] = 'mine.mp4'
        settings['obs_title_image'] = 'shared.png'
        with app.test_request_context():
            rows = {r['slot']: r for r in ro.image_slots()}
        assert rows['post']['per_session'] is True
        assert rows['post']['is_video'] is True
        assert rows['title']['per_session'] is False
        assert rows['title']['is_video'] is False


@pytest.fixture()
def dm_app(monkeypatch, tmp_path):
    """Real blueprint + login, temp art dir, stubbed settings store."""
    from models.user import tblUsers
    import routes.obs as ro
    import sql
    from routes.obs import obs_bp

    store = {}
    monkeypatch.setattr(sql, 'appsettingGet',
                        lambda n, d=None: store.get(n, d))
    monkeypatch.setattr(ro, 'appsettingGet',
                        lambda n, d=None: store.get(n, d))
    monkeypatch.setattr(sql, 'appsettingSet',
                        lambda n, v: store.__setitem__(n, str(v)))
    monkeypatch.setattr(ro, 'appsettingSet',
                        lambda n, v: store.__setitem__(n, str(v)))
    monkeypatch.setattr(ro, 'BG_DIR', str(tmp_path))
    # Pillow is not under test here.
    import relay_broadcaster
    monkeypatch.setattr(relay_broadcaster, '_downscale_image',
                        lambda raw, ext, max_dim=1920: (raw, ext))

    a = Flask(__name__, template_folder=os.path.join(REPO, 'templates'),
              static_folder=os.path.join(REPO, 'static'))
    a.config.update(SQLALCHEMY_DATABASE_URI='sqlite://',
                    SQLALCHEMY_TRACK_MODIFICATIONS=False,
                    SECRET_KEY='test', TESTING=True)
    db.init_app(a)
    login = LoginManager()
    login.init_app(a)
    a.register_blueprint(obs_bp)
    a.test_client_class = FlaskLoginClient
    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                      role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm)
        db.session.commit()
        yield a, dm, store, tmp_path
        db.session.remove()
        db.drop_all()


def _upload(a, dm, slot, filename, data=b'x' * 100):
    with a.test_client(user=dm) as c:
        return c.post(f'/ttrpg/obs/image/{slot}',
                      data={'image': (io.BytesIO(data), filename)},
                      content_type='multipart/form-data')


class TestSessionUpload:
    def test_upload_with_a_session_is_that_sessions_art(self, dm_app):
        a, dm, store, tmp = dm_app
        with a.app_context():
            _session(7)
        r = _upload(a, dm, 'post', 'card.png')
        assert r.status_code == 302
        assert store.get('obs_post_image:s7') == 'post-show-s7.png'
        assert 'obs_post_image' not in store, 'the shared default is untouched'
        assert (tmp / 'post-show-s7.png').exists()

    def test_upload_without_a_session_edits_the_shared_default(self, dm_app):
        a, dm, store, tmp = dm_app
        r = _upload(a, dm, 'post', 'card.png')
        assert r.status_code == 302
        assert store.get('obs_post_image') == 'post-show.png'

    def test_video_is_accepted_and_skips_downscale(self, dm_app, monkeypatch):
        a, dm, store, tmp = dm_app
        import relay_broadcaster

        def boom(*a_, **k):
            raise AssertionError('Pillow must never see a video')
        monkeypatch.setattr(relay_broadcaster, '_downscale_image', boom)
        r = _upload(a, dm, 'party_bg', 'loop.mp4', b'v' * 500)
        assert r.status_code == 302
        assert store.get('obs_party_bg') == 'party-bg.mp4'
        assert (tmp / 'party-bg.mp4').read_bytes() == b'v' * 500

    def test_oversized_video_is_refused(self, dm_app, monkeypatch):
        a, dm, store, tmp = dm_app
        import routes.obs as ro
        monkeypatch.setattr(ro, 'VIDEO_MAX_BYTES', 100)
        r = _upload(a, dm, 'party_bg', 'big.webm', b'v' * 200)
        assert r.status_code == 302
        assert 'obs_party_bg' not in store
        assert not (tmp / 'party-bg.webm').exists()

    def test_new_format_evicts_the_old_file(self, dm_app):
        """Stable name per slot: the browser sources cache by URL, so a format
        change must not leave the old file referenced or on disk."""
        a, dm, store, tmp = dm_app
        _upload(a, dm, 'post', 'card.png')
        _upload(a, dm, 'post', 'card.mp4', b'v' * 100)
        assert store.get('obs_post_image') == 'post-show.mp4'
        assert not (tmp / 'post-show.png').exists()

    def test_clear_with_a_session_drops_only_that_sessions_art(self, dm_app):
        a, dm, store, tmp = dm_app
        with a.app_context():
            _session(7)
        store['obs_post_image'] = 'shared.jpg'
        store['obs_post_image:s7'] = 'mine.jpg'
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/obs/image/post', data={'clear': '1'})
        assert store['obs_post_image:s7'] == ''
        assert store['obs_post_image'] == 'shared.jpg', \
            'the shared default must survive a session-level clear'


class TestAutoSave:
    def test_fetch_save_answers_json_instead_of_redirecting(self, dm_app):
        a, dm, store, _tmp = dm_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/save-config',
                       data={'obs_vdo_room': 'my room!'},
                       headers={'X-Requested-With': 'fetch'})
        assert r.status_code == 200
        d = r.get_json()
        assert d['ok'] is True
        assert d['room'] == 'myroom', \
            'the cleaned name comes back so the page can show what was kept'

    def test_plain_form_post_still_redirects(self, dm_app):
        """The no-JS fallback."""
        a, dm, store, _tmp = dm_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/save-config', data={})
        assert r.status_code == 302


class TestMuteApi:
    """Muting one voice, or the whole table, from the app — persisted so a
    rebuild cannot silently lift it."""

    def _post(self, a, dm, payload):
        with a.test_client(user=dm) as c:
            return c.post('/ttrpg/obs/api/mute', json=payload)

    def test_mute_one_player_persists(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        from models.ttrpg import tblCharacters
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            db.session.add(tblCharacters(
                character_id=7, user_id=1, name='Kara', level=1, hp_current=1,
                hp_max=1, created_at='2026-01-01 00:00:00'))
            db.session.commit()
        d = self._post(a, dm, {'character_id': 7, 'muted': True}).get_json()
        assert d['ok'] is True and d['muted_ids'] == [7]
        assert store['obs_muted_ids'] == '7'
        d = self._post(a, dm, {'character_id': 7, 'muted': False}).get_json()
        assert d['muted_ids'] == []

    def test_mute_all_spares_the_dm(self, dm_app, monkeypatch):
        """'Mute the table' and 'mute myself' are different acts."""
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        from models.ttrpg import tblCharacters
        muted = []
        monkeypatch.setattr(obs_ws, 'connected', lambda: True)
        monkeypatch.setattr(obs_ws, 'set_input_mute',
                            lambda n, m, **k: muted.append((n, m)))
        with a.app_context():
            kara = tblCharacters(character_id=7, user_id=1, name='Kara',
                                 level=1, hp_current=1, hp_max=1,
                                 created_at='2026-01-01 00:00:00')
            monkeypatch.setattr(ro, '_ordered_party',
                                lambda *a_, **k: [kara, ro.dm_tile()])
            d = self._post(a, dm, {'all': True, 'muted': True}).get_json()
        assert d['muted_ids'] == [7], 'the DM must not be swept up in "all"'
        assert muted == [('Player - Kara Cam', True)]

    def test_the_dm_can_be_muted_individually(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        d = self._post(a, dm,
                       {'character_id': ro.DM_TILE_ID, 'muted': True}).get_json()
        assert ro.DM_TILE_ID in d['muted_ids']

    def test_disconnected_obs_still_persists_the_mute(self, dm_app,
                                                      monkeypatch):
        """The setting is the truth; the next build applies it."""
        a, dm, store, _tmp = dm_app
        import obs_ws
        from models.ttrpg import tblCharacters
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            db.session.add(tblCharacters(
                character_id=9, user_id=1, name='Ben', level=1, hp_current=1,
                hp_max=1, created_at='2026-01-01 00:00:00'))
            db.session.commit()
        d = self._post(a, dm, {'character_id': 9, 'muted': True}).get_json()
        assert d['ok'] is True and store['obs_muted_ids'] == '9'


class TestMuteEveryone:
    def test_everyone_includes_the_dm(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        from models.ttrpg import tblCharacters
        muted = []
        monkeypatch.setattr(obs_ws, 'connected', lambda: True)
        monkeypatch.setattr(obs_ws, 'set_input_mute',
                            lambda n, m, **k: muted.append((n, m)))
        with a.app_context():
            kara = tblCharacters(character_id=7, user_id=1, name='Kara',
                                 level=1, hp_current=1, hp_max=1,
                                 created_at='2026-01-01 00:00:00')
            monkeypatch.setattr(ro, '_ordered_party',
                                lambda *a_, **k: [kara, ro.dm_tile()])
            with a.test_client(user=dm) as c:
                d = c.post('/ttrpg/obs/api/mute',
                           json={'all': 'everyone', 'muted': True}).get_json()
        assert ro.DM_TILE_ID in d['muted_ids'] and 7 in d['muted_ids']
        # The DM source is named after their display name ('GM' here).
        assert any(n.startswith('DM - ') and m for n, m in muted), muted

    def test_legacy_true_still_spares_the_dm(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            monkeypatch.setattr(ro, '_ordered_party',
                                lambda *a_, **k: [ro.dm_tile()])
            with a.test_client(user=dm) as c:
                d = c.post('/ttrpg/obs/api/mute',
                           json={'all': True, 'muted': True}).get_json()
        assert d['muted_ids'] == []


class TestSceneAudioPolicy:
    """A ScenePlay scene can carry a stream-audio policy: PreShow mutes
    everyone so the table talks freely off-air, the opening scene unmutes."""

    def test_policy_is_stored_and_read_back(self, dm_app):
        a, dm, store, _tmp = dm_app
        import routes.obs as ro
        with a.test_client(user=dm) as c:
            d = c.post('/ttrpg/obs/api/scene-audio',
                       json={'scene_id': 25, 'policy': 'mute_all'}).get_json()
        assert d['ok'] is True
        assert store['obs_scene_audio:25'] == 'mute_all'
        with a.app_context():
            assert ro.scene_audio_policy(25) == 'mute_all'

    def test_junk_policy_is_rejected(self, dm_app):
        a, dm, store, _tmp = dm_app
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/api/scene-audio',
                       json={'scene_id': 25, 'policy': 'explode'})
        assert r.status_code == 400
        assert 'obs_scene_audio:25' not in store

    def _party(self, monkeypatch, ro):
        from models.ttrpg import tblCharacters
        kara = tblCharacters(character_id=7, user_id=1, name='Kara', level=1,
                             hp_current=1, hp_max=1,
                             created_at='2026-01-01 00:00:00')
        monkeypatch.setattr(ro, '_ordered_party',
                            lambda *a_, **k: [kara, ro.dm_tile()])

    def test_activating_a_mute_all_scene_silences_everyone(self, dm_app,
                                                           monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        store.update({'obs_enabled': '1', 'obs_scene_audio:25': 'mute_all'})
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            self._party(monkeypatch, ro)
            assert ro.apply_scene_audio(25) == 'mute_all'
        got = set(int(x) for x in store['obs_muted_ids'].split(','))
        assert got == {7, ro.DM_TILE_ID}

    def test_mute_players_spares_the_dm(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        store.update({'obs_enabled': '1',
                      'obs_scene_audio:25': 'mute_players'})
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            self._party(monkeypatch, ro)
            ro.apply_scene_audio(25)
        assert store['obs_muted_ids'] == '7'

    def test_unmute_all_clears_the_set(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import obs_ws
        import routes.obs as ro
        store.update({'obs_enabled': '1', 'obs_muted_ids': '-1,7',
                      'obs_scene_audio:25': 'unmute_all'})
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.app_context():
            self._party(monkeypatch, ro)
            ro.apply_scene_audio(25)
        assert store['obs_muted_ids'] == ''

    def test_no_policy_touches_nothing(self, dm_app, monkeypatch):
        a, dm, store, _tmp = dm_app
        import routes.obs as ro
        store.update({'obs_enabled': '1', 'obs_muted_ids': '7'})
        with a.app_context():
            assert ro.apply_scene_audio(25) == ''
        assert store['obs_muted_ids'] == '7'

    def test_obs_disabled_leaves_mutes_alone(self, dm_app, monkeypatch):
        """A scene must activate identically with the whole OBS feature off."""
        a, dm, store, _tmp = dm_app
        import routes.obs as ro
        store.update({'obs_enabled': '0', 'obs_scene_audio:25': 'mute_all'})
        with a.app_context():
            assert ro.apply_scene_audio(25) == ''
        assert 'obs_muted_ids' not in store

    def test_activation_never_raises(self, dm_app, monkeypatch):
        import routes.obs as ro
        a, dm, store, _tmp = dm_app
        store.update({'obs_enabled': '1', 'obs_scene_audio:25': 'mute_all'})
        monkeypatch.setattr(ro, '_ordered_party',
                            lambda *a_, **k: (_ for _ in ()).throw(
                                RuntimeError('db gone')))
        with a.app_context():
            assert ro.apply_scene_audio(25) == ''   # swallowed, logged


class TestPanelNoteLibrary:
    """Pre-saved messages for the information panel: prepped before the
    stream, scoped to one session (or shared with all), shown with one click."""

    def _save(self, a, dm, payload):
        with a.test_client(user=dm) as c:
            return c.post('/ttrpg/obs/api/panel-notes', json=payload)

    def test_save_binds_the_note_to_the_active_session(self, dm_app):
        a, dm, store, _tmp = dm_app
        from models.ttrpg import tblObsPanelNotes
        with a.app_context():
            _session(7)
        r = self._save(a, dm, {'title': 'Break', 'body': '<b>Back in 10</b>'})
        d = r.get_json()
        assert r.status_code == 200 and d['ok'] is True
        with a.app_context():
            row = db.session.get(tblObsPanelNotes, d['note_id'])
            assert row.session_id == 7
            assert row.body == '<b>Back in 10</b>'
        assert d['notes'] == [{'id': d['note_id'], 'title': 'Break',
                               'shared': False}]

    def test_shared_note_reaches_every_session(self, dm_app):
        a, dm, store, _tmp = dm_app
        r = self._save(a, dm, {'title': 'BRB', 'body': 'Right back',
                               'shared': True})
        d = r.get_json()
        assert d['notes'][0]['shared'] is True
        # Visible with NO active session, and still there once one starts.
        with a.app_context():
            _session(7)
            import routes.obs as ro
            titles = [n['title'] for n in ro.panel_note_rows()]
        assert titles == ['BRB']

    def test_another_sessions_notes_stay_out_of_the_library(self, dm_app):
        a, dm, store, _tmp = dm_app
        from models.ttrpg import tblObsPanelNotes
        with a.app_context():
            _session(7)
            db.session.add(tblObsPanelNotes(
                session_id=None, title='Everywhere', body='x',
                created_at='2026-01-01 00:00:00',
                updated_at='2026-01-01 00:00:00'))
            db.session.add(tblObsPanelNotes(
                session_id=99, title='Elsewhere', body='x',
                created_at='2026-01-01 00:00:00',
                updated_at='2026-01-01 00:00:00'))
            db.session.commit()
            import routes.obs as ro
            titles = [n['title'] for n in ro.panel_note_rows()]
        assert titles == ['Everywhere'], \
            "another session's prep must not clutter tonight's library"

    def test_show_puts_the_note_text_on_stream(self, dm_app):
        a, dm, store, _tmp = dm_app
        d = self._save(a, dm, {'title': 'Break', 'body': 'Back in 10',
                               'shared': True}).get_json()
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/api/panel-notes/show',
                       json={'note_id': d['note_id']})
        body = r.get_json()
        assert body['ok'] is True and body['body'] == 'Back in 10'
        assert store['obs_info_text'] == 'Back in 10', \
            'showing a note IS setting the panel text — the watcher pops it'

    def test_saving_under_the_same_id_updates_in_place(self, dm_app):
        a, dm, store, _tmp = dm_app
        from models.ttrpg import tblObsPanelNotes
        d = self._save(a, dm, {'title': 'Break', 'body': 'v1',
                               'shared': True}).get_json()
        d2 = self._save(a, dm, {'title': 'Break', 'body': 'v2',
                                'shared': True,
                                'note_id': d['note_id']}).get_json()
        assert d2['note_id'] == d['note_id']
        with a.app_context():
            assert db.session.query(tblObsPanelNotes).count() == 1
            assert db.session.get(tblObsPanelNotes, d['note_id']).body == 'v2'

    def test_delete_removes_the_note(self, dm_app):
        a, dm, store, _tmp = dm_app
        from models.ttrpg import tblObsPanelNotes
        d = self._save(a, dm, {'title': 'Break', 'body': 'x',
                               'shared': True}).get_json()
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/api/panel-notes/delete',
                       json={'note_id': d['note_id']})
        assert r.get_json()['ok'] is True
        assert r.get_json()['notes'] == []
        with a.app_context():
            assert db.session.query(tblObsPanelNotes).count() == 0

    def test_a_note_needs_a_name_and_a_body(self, dm_app):
        a, dm, store, _tmp = dm_app
        assert self._save(a, dm, {'title': '', 'body': 'x'}).status_code == 400
        assert self._save(a, dm, {'title': 'T', 'body': '  '}).status_code == 400


class TestYouTubeGoLiveApi:
    """The one-click go-live: broadcast created with the saved front matter,
    OBS re-pointed at its ingestion, stream started."""

    def test_golive_requires_obs(self, dm_app, monkeypatch):
        import obs_ws
        a, dm, store, _tmp = dm_app
        monkeypatch.setattr(obs_ws, 'connected', lambda: False)
        with a.test_client(user=dm) as c:
            assert c.post('/ttrpg/obs/api/yt/golive').status_code == 503

    def test_golive_points_obs_and_starts_the_stream(self, dm_app,
                                                     monkeypatch):
        import obs_ws
        import youtube_live as yt
        a, dm, store, _tmp = dm_app
        store.update({'yt_title': 'Night 12', 'yt_privacy': 'public',
                      'yt_category': '24', 'yt_kids': '1'})
        sent = {}
        monkeypatch.setattr(obs_ws, 'connected', lambda: True)
        monkeypatch.setattr(obs_ws, 'request',
                            lambda t, p=None: sent.__setitem__('svc', (t, p)))

        def fake_start(kind, want):
            sent['start'] = (kind, want)
            return True
        monkeypatch.setattr(obs_ws, 'set_output_active', fake_start)

        def fake_golive(title, description, privacy, category, kids,
                        thumb=None, start_iso=None):
            sent['meta'] = {'title': title, 'privacy': privacy,
                            'category': category, 'kids': kids}
            return {'broadcast_id': 'B1', 'watch_url': 'https://youtu.be/B1',
                    'server': 'rtmp://in', 'key': 'key-1',
                    'thumb_warning': ''}
        monkeypatch.setattr(yt, 'go_live', fake_golive)
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/api/yt/golive')
        d = r.get_json()
        assert d['ok'] is True and d['watch_url'].endswith('/B1')
        assert sent['meta'] == {'title': 'Night 12', 'privacy': 'public',
                                'category': '24', 'kids': True}
        assert sent['svc'][0] == 'SetStreamServiceSettings'
        assert sent['svc'][1]['streamServiceSettings'] == {
            'server': 'rtmp://in', 'key': 'key-1', 'use_auth': False}
        assert sent['start'] == ('stream', True)

    def test_broadcast_survives_an_obs_refusal(self, dm_app, monkeypatch):
        """The video exists on YouTube even if OBS balks — the error must
        carry the watch link so the DM can start the output by hand."""
        import obs_ws
        import youtube_live as yt
        a, dm, store, _tmp = dm_app
        store['yt_title'] = 'T'
        monkeypatch.setattr(obs_ws, 'connected', lambda: True)

        def refuse(t, p=None):
            raise obs_ws.ObsRejected(207, 'an output is active')
        monkeypatch.setattr(obs_ws, 'request', refuse)
        monkeypatch.setattr(yt, 'go_live',
                            lambda *a_, **k: {'broadcast_id': 'B1',
                                              'watch_url': 'https://youtu.be/B1',
                                              'server': 's', 'key': 'k',
                                              'thumb_warning': ''})
        with a.test_client(user=dm) as c:
            r = c.post('/ttrpg/obs/api/yt/golive')
        d = r.get_json()
        assert r.status_code == 502 and d['ok'] is False
        assert d['watch_url'] == 'https://youtu.be/B1'
        assert 'youtu.be/B1' in d['error']

    def test_save_config_persists_the_front_matter(self, dm_app):
        a, dm, store, _tmp = dm_app
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/obs/save-config', data={
                'yt_client_id': 'cid', 'yt_client_secret': 's3cret',
                'yt_title': 'Night 12', 'yt_description': 'plot',
                'yt_privacy': 'public', 'yt_category': '24', 'yt_kids': '1'})
        assert store['yt_client_id'] == 'cid'
        assert store['yt_client_secret'] == 's3cret'
        assert store['yt_title'] == 'Night 12'
        assert store['yt_privacy'] == 'public'
        assert store['yt_category'] == '24'
        assert store['yt_kids'] == '1'
        # Unticking kids clears it; a blank secret keeps the saved one.
        with a.test_client(user=dm) as c:
            c.post('/ttrpg/obs/save-config',
                   data={'yt_client_id': 'cid', 'yt_client_secret': ''})
        assert store['yt_kids'] == '0'
        assert store['yt_client_secret'] == 's3cret'

    def test_unlink_forgets_the_account(self, dm_app):
        a, dm, store, _tmp = dm_app
        store.update({'yt_refresh_token': 'ref', 'yt_channel': 'Me',
                      'yt_stream_id': 'S1'})
        import youtube_live as yt
        # The route calls youtube_live, which reads ITS OWN appsettings
        # import — point it at the same store this fixture stubs.
        yt_get = yt.appsettingGet, yt.appsettingSet
        yt.appsettingGet = lambda n, d=None: store.get(n, d)
        yt.appsettingSet = lambda n, v: store.__setitem__(n, str(v))
        try:
            with a.test_client(user=dm) as c:
                assert c.post('/ttrpg/obs/api/yt/unlink').get_json()['ok']
        finally:
            yt.appsettingGet, yt.appsettingSet = yt_get
        assert store['yt_refresh_token'] == ''
        assert store['yt_stream_id'] == ''
