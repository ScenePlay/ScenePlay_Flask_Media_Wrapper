"""Video-feed identity and the pure helpers behind the camera rotation:
VDO.ninja URL building (including the shared password), custom-URL override,
feed-readiness classification, and the feed URL validator."""
import pytest

from extensions import db
from models.ttrpg import tblCharacters, _vdo_url


@pytest.fixture()
def settings(app, monkeypatch):
    """appsettingGet talks to the real sqlite file — stub it per test.

    Both bindings have to be patched: models.ttrpg imports it lazily inside
    the function (so patching sql is enough there), but routes.obs did
    `from sql import appsettingGet` at module load and holds its own
    reference, which would otherwise keep reading the live database."""
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


def _char(**over):
    base = dict(user_id=1, name='Kara', level=1, hp_current=5, hp_max=5,
                created_at='2026-01-01 00:00:00')
    base.update(over)
    return tblCharacters(**base)


class TestVdoUrls:
    def test_push_and_view_default_params(self, settings):
        c = _char(video_stream_id='abc123')
        assert c.video_push_url() == \
            'https://vdo.ninja/?push=abc123&webcam&autostart'
        assert c.video_view_url() == \
            'https://vdo.ninja/?view=abc123&cleanoutput&transparent&autostart'

    def test_shared_password_rides_on_both_ends(self, settings):
        # The stream id alone is a capability; the table password is what
        # makes a leaked link useless.
        settings['obs_vdo_password'] = 'table secret&'
        c = _char(video_stream_id='abc123')
        assert '&password=table%20secret%26' in c.video_push_url()
        assert '&password=table%20secret%26' in c.video_view_url()

    def test_settings_override_base_and_params(self, settings):
        settings['obs_vdo_base'] = 'https://my.ninja'      # no trailing slash
        settings['obs_vdo_view_params'] = '&cleanoutput'
        c = _char(video_stream_id='xyz')
        assert c.video_view_url() == 'https://my.ninja/?view=xyz&cleanoutput'

    def test_custom_url_wins_and_suppresses_push(self, settings):
        c = _char(video_stream_id='abc123',
                  video_feed_url='https://example.com/mystream')
        assert c.video_view_url() == 'https://example.com/mystream'
        # Their feed, their start button — we don't own it.
        assert c.video_push_url() == ''

    def test_no_identity_means_no_urls(self, settings):
        c = _char()
        assert c.video_view_url() == '' and c.video_push_url() == ''
        assert c.has_feed() is False
        assert _char(video_stream_id='a').has_feed() is True
        assert _char(video_feed_url='https://x/y').has_feed() is True

    def test_stream_id_is_url_escaped(self, settings):
        c = _char(video_stream_id='a b&c')
        assert 'push=a%20b%26c' in c.video_push_url()


class TestFeedUrlValidator:
    def test_accepts_query_strings(self):
        """The relay's device validator rejects paths/queries — ours must not,
        since a VDO.ninja link IS a query string."""
        from routes.obs import _normalize_feed_url
        url = 'https://vdo.ninja/?view=abc&cleanoutput'
        assert _normalize_feed_url(url) == url

    def test_blank_clears(self):
        from routes.obs import _normalize_feed_url
        assert _normalize_feed_url('') == ''
        assert _normalize_feed_url('   ') == ''

    @pytest.mark.parametrize('bad', [
        'javascript:alert(1)',
        'data:text/html,<script>',
        'vdo.ninja/?view=abc',            # no scheme
        'ftp://example.com/x',
    ])
    def test_rejects_non_http(self, bad):
        from routes.obs import _normalize_feed_url
        with pytest.raises(ValueError):
            _normalize_feed_url(bad)

    def test_rejects_overlong(self):
        from routes.obs import _normalize_feed_url
        with pytest.raises(ValueError):
            _normalize_feed_url('https://x/' + 'a' * 600)


class TestStreamIds:
    def test_generated_ids_are_long_and_alphanumeric(self):
        from routes.obs import _new_stream_id
        ids = {_new_stream_id() for _ in range(50)}
        assert len(ids) == 50                      # no collisions
        for sid in ids:
            assert len(sid) >= 20 and sid.isalnum() and sid.islower()


class TestFeedState:
    def _state(self, char, presence):
        from routes.obs import _feed_state
        return _feed_state(char, presence)

    def test_no_feed(self):
        assert self._state(_char(), {}) == 'nofeed'

    def test_unknown_presence_is_ready_not_offline(self):
        """A player sitting at the table has no relay presence — that must not
        read as 'offline'."""
        assert self._state(_char(video_stream_id='a'), {}) == 'ready'

    def test_recent_presence_is_live(self):
        assert self._state(_char(video_stream_id='a'), {'Kara': 5}) == 'live'

    def test_stale_presence(self):
        assert self._state(_char(video_stream_id='a'), {'Kara': 500}) == 'stale'


class TestSceneNaming:
    def test_prefixes_and_strips_control_chars(self):
        from routes.obs import _scene_name_for
        assert _scene_name_for(_char(name='Kara')) == 'Player - Kara'
        assert _scene_name_for(_char(name='Ka\x00ra\n')) == 'Player - Kara'

    def test_falls_back_when_name_is_empty(self):
        from routes.obs import _scene_name_for
        c = _char(name='')
        c.character_id = 7
        assert _scene_name_for(c) == 'Player - Player 7'


class TestRotationAndFeedPersistence:
    def test_rotation_follows_saved_order_then_newcomers(self, app, monkeypatch):
        from models.ttrpg import (tblObsSceneMap, tblSessions, tblSessionParty)
        from models.user import tblUsers
        import routes.obs as ro

        u = tblUsers(username='p', display_name='P', password_hash='x',
                     role='player', active=1, created_at='t')
        db.session.add(u)
        db.session.flush()
        chars = []
        for name in ('A', 'B', 'C'):
            c = _char(user_id=u.user_id, name=name)
            db.session.add(c)
            chars.append(c)
        db.session.flush()
        sess = tblSessions(title='S', status='active', created_at='t')
        db.session.add(sess)
        db.session.flush()
        for c in chars:
            db.session.add(tblSessionParty(session_id=sess.session_id,
                                           character_id=c.character_id,
                                           is_active=1, joined_at='t'))
        # B first, then A. C has no row yet — a character added to the party
        # after the scene was built.
        db.session.add(tblObsSceneMap(entity_type='player', entity_id=chars[1].character_id,
                                      entity_key='', scene_name='Party', sort_order=0))
        db.session.add(tblObsSceneMap(entity_type='player', entity_id=chars[0].character_id,
                                      entity_key='', scene_name='Party', sort_order=1))
        db.session.commit()

        # Exclude the DM tile here; its ordering has its own tests below.
        monkeypatch.setattr(ro, 'dm_tile_enabled', lambda: False)
        order = ro._rotation_order()
        # Saved order wins, so nobody's tile moves when the party changes...
        assert order[:2] == [chars[1].character_id, chars[0].character_id]
        # ...and a newcomer is appended rather than renumbering everyone. They
        # still get a tile (a stat card) even with no camera set up.
        assert order[2] == chars[2].character_id

    def test_special_and_scene_maps_are_independent(self, app):
        from models.ttrpg import tblObsSceneMap
        import routes.obs as ro
        ro._upsert_special_map('group', 'Group Shot')
        assert ro._special_scene('group') == 'Group Shot'
        ro._upsert_special_map('group', 'Wide Shot')          # upsert, not insert
        assert ro._special_scene('group') == 'Wide Shot'
        assert tblObsSceneMap.query.filter_by(entity_type='special').count() == 1
        assert ro._special_scene('nothing-here') == ''


class TestRelayFeedPush:
    """push_character_feeds sends each party member's camera link to the relay.
    The links are per-player capabilities, so they must ride their OWN payload
    — never the character payload every player receives."""

    def _setup_party(self):
        from models.ttrpg import tblSessions, tblSessionParty
        from models.user import tblUsers
        u = tblUsers(username='kara', display_name='Kara', password_hash='x',
                     role='player', active=1, created_at='t')
        db.session.add(u)
        db.session.flush()
        a = _char(user_id=u.user_id, name='Kara', video_stream_id='karastream')
        b = _char(user_id=u.user_id, name='Fenn',
                  video_feed_url='https://example.com/fenn')
        db.session.add_all([a, b])
        db.session.flush()
        sess = tblSessions(title='S', status='active', created_at='t')
        db.session.add(sess)
        db.session.flush()
        for c in (a, b):
            db.session.add(tblSessionParty(session_id=sess.session_id,
                                           character_id=c.character_id,
                                           is_active=1, joined_at='t'))
        db.session.commit()
        return a, b

    def test_payload_shape(self, app, monkeypatch, settings):
        import relay_broadcaster as rb
        self._setup_party()
        sent = {}
        monkeypatch.setattr(rb, '_active', lambda: {'session_id': 'S1'})
        monkeypatch.setattr(rb, '_exec_cfg', lambda: {'session_id': 'S1'})
        monkeypatch.setattr(rb, '_post', lambda path, payload, cfg: sent.update(
            {'path': path, 'payload': payload}))
        monkeypatch.setattr(rb, '_enqueue', lambda key, fn: fn())

        rb.push_character_feeds()

        assert sent['path'] == '/api/v1/session/S1/feeds'
        feeds = {f['player_name']: f for f in sent['payload']['feeds']}
        assert set(feeds) == {'Kara', 'Fenn'}
        # generated link carries the stream id; username lets the relay scope it
        assert 'karastream' in feeds['Kara']['push_url']
        assert feeds['Kara']['username'] == 'kara'
        assert feeds['Kara']['feed_url'] == ''
        # a custom feed is the player's own to start: no push link from us
        assert feeds['Fenn']['push_url'] == ''
        assert feeds['Fenn']['feed_url'] == 'https://example.com/fenn'

    def test_old_relay_without_the_endpoint_is_not_retried(self, app, monkeypatch, settings):
        """A relay that predates /feeds answers 404 — that must be swallowed,
        not retried for two minutes."""
        import relay_broadcaster as rb
        self._setup_party()

        class Resp:
            status_code = 404

        class Boom(Exception):
            response = Resp()

        def _post(path, payload, cfg):
            raise Boom('404 Not Found')

        monkeypatch.setattr(rb, '_active', lambda: {'session_id': 'S1'})
        monkeypatch.setattr(rb, '_exec_cfg', lambda: {'session_id': 'S1'})
        monkeypatch.setattr(rb, '_post', _post)
        captured = {}
        monkeypatch.setattr(rb, '_enqueue', lambda key, fn: captured.setdefault('fn', fn))
        rb.push_character_feeds()
        captured['fn']()          # must NOT raise

    def test_no_active_session_sends_nothing(self, app, monkeypatch, settings):
        import relay_broadcaster as rb
        monkeypatch.setattr(rb, '_active', lambda: {'session_id': 'S1'})
        calls = []
        monkeypatch.setattr(rb, '_enqueue', lambda key, fn: calls.append(key))
        rb.push_character_feeds()
        assert calls == []


class TestFeedMutation:
    """A portal player setting their own URL comes back as a mutation."""

    def _apply(self, char, data):
        import relay_receiver as rr
        rr._apply_mutation(char, 'video_feed_set', data, 'http://relay', db)

    def test_sets_url(self, app):
        c = _char(video_stream_id='abc')
        db.session.add(c)
        db.session.commit()
        self._apply(c, {'feed_url': 'https://vdo.ninja/?view=mine'})
        assert c.video_feed_url == 'https://vdo.ninja/?view=mine'

    def test_clearing_restores_the_generated_link(self, app, settings):
        c = _char(video_stream_id='abc', video_feed_url='https://x/y')
        db.session.add(c)
        db.session.commit()
        self._apply(c, {'feed_url': ''})
        assert c.video_feed_url == ''
        assert 'abc' in c.video_view_url()     # back to the ScenePlay link

    @pytest.mark.parametrize('bad', ['javascript:alert(1)', 'ftp://x/y', 'x' * 600])
    def test_rejects_bad_urls_at_the_local_boundary(self, app, bad):
        """The relay validates too, but this is where portal input becomes
        local data — re-check rather than trust."""
        c = _char(video_feed_url='https://good/existing')
        db.session.add(c)
        db.session.commit()
        self._apply(c, {'feed_url': bad})
        assert c.video_feed_url == 'https://good/existing'


class TestTileFallback:
    """A dropped camera must give way to that player's stat card — and give it
    back when they return. The tile's cell never changes, only its URL."""

    def _char(self, app, **over):
        c = _char(**over)
        db.session.add(c)
        db.session.commit()
        return c

    def test_no_feed_uses_the_card(self, app, settings):
        import routes.obs as ro
        c = self._char(app)
        with app.test_request_context():
            assert '/ttrpg/obs/card/' in ro._tile_url(c, {}, set())

    def test_healthy_camera_is_used(self, app, settings):
        import routes.obs as ro
        c = self._char(app, video_stream_id='abc123')
        with app.test_request_context():
            url = ro._tile_url(c, {'Kara': 5}, set())
        assert 'abc123' in url and '/card/' not in url

    def test_unknown_presence_keeps_the_camera(self, app, settings):
        """A LAN player never reports presence — that must not be read as a
        drop, or their camera would be replaced the moment it works."""
        import routes.obs as ro
        c = self._char(app, video_stream_id='abc123')
        with app.test_request_context():
            assert 'abc123' in ro._tile_url(c, {}, set())

    def test_stale_presence_falls_back_to_the_card(self, app, settings):
        import routes.obs as ro
        c = self._char(app, video_stream_id='abc123')
        with app.test_request_context():
            url = ro._tile_url(c, {'Kara': 999}, set())
        assert '/ttrpg/obs/card/' in url

    def test_camera_returns_when_presence_recovers(self, app, settings):
        import routes.obs as ro
        c = self._char(app, video_stream_id='abc123')
        with app.test_request_context():
            assert '/card/' in ro._tile_url(c, {'Kara': 999}, set())
            assert 'abc123' in ro._tile_url(c, {'Kara': 3}, set())

    def test_manual_pin_wins_over_a_healthy_camera(self, app, settings):
        import routes.obs as ro
        c = self._char(app, video_stream_id='abc123')
        with app.test_request_context():
            url = ro._tile_url(c, {'Kara': 1}, {c.character_id})
        assert '/ttrpg/obs/card/' in url

    def test_override_set_round_trips(self, app, settings, monkeypatch):
        """monkeypatch, never bare assignment: routes.obs imported these names
        directly, so a hand-rolled swap leaks into every later test in the
        session (it broke the password-recovery suite once)."""
        import routes.obs as ro
        store = {'obs_card_override': ''}
        monkeypatch.setattr(ro, 'appsettingGet',
                            lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet',
                            lambda n, v, typevalue='text': store.__setitem__(n, v))

        ro._set_card_override(7, True)
        assert ro._card_overrides() == {7}
        ro._set_card_override(9, True)
        assert ro._card_overrides() == {7, 9}
        ro._set_card_override(7, False)
        assert ro._card_overrides() == {9}


class TestDmTile:
    """The DM narrates and plays every NPC, so they get a tile like anyone
    else — with no character row behind it."""

    def _party_of_one(self):
        from models.ttrpg import tblSessions, tblSessionParty
        from models.user import tblUsers
        dm = tblUsers(username='thegm', display_name='Game Master', password_hash='x',
                      role='dm', active=1, created_at='t')
        pl = tblUsers(username='pp', display_name='P', password_hash='x',
                      role='player', active=1, created_at='t')
        db.session.add_all([dm, pl]); db.session.flush()
        c = _char(user_id=pl.user_id, name='Kara')
        db.session.add(c); db.session.flush()
        sess = tblSessions(title='S', status='active', created_at='t')
        db.session.add(sess); db.session.flush()
        db.session.add(tblSessionParty(session_id=sess.session_id,
                                       character_id=c.character_id,
                                       is_active=1, joined_at='t'))
        db.session.commit()
        return c

    def test_dm_leads_the_rotation_and_is_featurable(self, app, settings):
        import routes.obs as ro
        c = self._party_of_one()
        settings['obs_dm_enabled'] = '1'
        order = ro._rotation_order()
        assert order == [ro.DM_TILE_ID, c.character_id], order

    def test_dm_can_be_turned_off(self, app, settings):
        import routes.obs as ro
        c = self._party_of_one()
        settings['obs_dm_enabled'] = '0'
        assert ro._rotation_order() == [c.character_id]

    def test_dm_is_on_by_default(self, app, settings):
        import routes.obs as ro
        self._party_of_one()
        assert ro.dm_tile_enabled() is True         # absent setting -> on

    def test_dm_name_comes_from_the_dm_account(self, app, settings):
        import routes.obs as ro
        self._party_of_one()
        assert ro.dm_name() == 'Game Master'

    def test_dm_name_falls_back_without_a_dm_account(self, app, settings):
        import routes.obs as ro
        assert ro.dm_name() == 'Dungeon Master'

    def test_dm_source_name_is_distinct_from_players(self, app, settings):
        """Pruning only removes tiles ScenePlay manages, so the DM prefix has
        to be one of the recognised ones."""
        import routes.obs as ro
        name = ro._scene_name_for(ro.dm_tile())
        assert name.startswith('DM - ')
        assert name.startswith(ro._MANAGED_PREFIXES)
        assert ro._scene_name_for(_char(name='Kara')).startswith('Player - ')

    def test_dm_feed_urls_use_the_shared_vdo_settings(self, app, settings):
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmstream'
        settings['obs_vdo_password'] = 'tablepw'
        tile = ro.dm_tile()
        assert tile.has_feed() is True
        assert 'dmstream' in tile.video_view_url()
        assert '&password=tablepw' in tile.video_push_url()

    def test_dm_custom_url_wins(self, app, settings):
        import routes.obs as ro
        settings['obs_dm_stream_id'] = 'dmstream'
        settings['obs_dm_feed_url'] = 'https://example.com/dm'
        tile = ro.dm_tile()
        assert tile.video_view_url() == 'https://example.com/dm'
        assert tile.video_push_url() == ''

    def test_dm_with_no_camera_gets_a_card(self, app, settings):
        import routes.obs as ro
        with app.test_request_context():
            url = ro._tile_url(ro.dm_tile(), {}, set())
        # negative ids can't ride an <int:> route, so the DM card has its own
        assert url.endswith('/card/dm?t=' + ro._card_token(ro.DM_TILE_ID))

    def test_dm_card_override_id_survives_the_parser(self, app, settings, monkeypatch):
        """The override list is parsed from a CSV of ids — a naive isdigit()
        check would silently drop the DM's negative id."""
        import routes.obs as ro
        store = {'obs_card_override': ''}
        monkeypatch.setattr(ro, 'appsettingGet', lambda n, d=None: store.get(n, d))
        monkeypatch.setattr(ro, 'appsettingSet',
                            lambda n, v, typevalue='text': store.__setitem__(n, v))
        ro._set_card_override(ro.DM_TILE_ID, True)
        assert ro.DM_TILE_ID in ro._card_overrides()
