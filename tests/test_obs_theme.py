"""Stream look: the accent colour and camera-bezel shape (routes.obs).

Unit level: what matters is validation (a broken colour must never reach the
pages), the default gold, and that every page's poll payload carries the theme
so a save re-skins a live stream without source reloads."""
import pytest


@pytest.fixture()
def settings(app, monkeypatch):
    store = {}
    import routes.obs as ro
    import sql
    fake = lambda name, default=None: store.get(name, default)   # noqa: E731
    monkeypatch.setattr(sql, 'appsettingGet', fake)
    monkeypatch.setattr(ro, 'appsettingGet', fake)
    return store


class TestThemeSettings:
    def test_defaults(self, app, settings):
        import routes.obs as ro
        assert ro.theme_accent() == ro.DEFAULT_ACCENT == '#c8a86e'
        assert ro.bezel_shape() == 'rounded'

    def test_good_values_pass_through(self, app, settings):
        import routes.obs as ro
        settings['obs_accent_color'] = '#9B6DFF'
        settings['obs_bezel_shape'] = 'hex'
        assert ro.theme_accent() == '#9B6DFF'
        assert ro.bezel_shape() == 'hex'

    @pytest.mark.parametrize('bad', ['red', '#fff', '#12345g', '#1234567',
                                     'javascript:x', ''])
    def test_a_broken_colour_falls_back_to_gold(self, app, settings, bad):
        import routes.obs as ro
        settings['obs_accent_color'] = bad
        assert ro.theme_accent() == ro.DEFAULT_ACCENT

    def test_an_unknown_shape_falls_back_to_rounded(self, app, settings):
        import routes.obs as ro
        settings['obs_bezel_shape'] = 'triangle'
        assert ro.bezel_shape() == 'rounded'

    def test_base2_defaults_to_base_so_solid_stays_solid(self, app, settings):
        import routes.obs as ro
        settings['obs_base_color'] = '#140a08'
        assert ro.theme_base2() == '#140a08', 'no base2 set -> same as base'
        settings['obs_base_color2'] = 'broken'
        assert ro.theme_base2() == '#140a08', 'invalid base2 -> same as base'
        settings['obs_base_color2'] = '#2c1009'
        assert ro.theme_base2() == '#2c1009'

    def test_direction_validates_and_defaults(self, app, settings):
        import routes.obs as ro
        assert ro.theme_base_dir() == '180'
        settings['obs_base_dir'] = 'sideways'
        assert ro.theme_base_dir() == '180'
        for good in ('0', '45', '90', '135', '225', '270', '315', 'radial'):
            settings['obs_base_dir'] = good
            assert ro.theme_base_dir() == good

    def test_payload_shape(self, app, settings):
        import routes.obs as ro
        settings['obs_accent_color'] = '#4a9eff'
        settings['obs_base_color'] = '#06101c'
        settings['obs_bezel_shape'] = 'circle'
        assert ro._theme_payload() == {'accent': '#4a9eff', 'base': '#06101c',
                                       'base2': '#06101c', 'dir': '180',
                                       'bezel': 'circle',
                                       'plate': '#06101c', 'plate2': '#06101c',
                                       'plate_dir': '180', 'card': 'classic',
                                       'tile': 'strip',
                                       'dm_icon': '⚔',
                                       'dm_title': 'Dungeon Master'}

    def test_base_defaults_and_validates(self, app, settings):
        import routes.obs as ro
        assert ro.theme_base() == ro.DEFAULT_BASE == '#08090d'
        settings['obs_base_color'] = 'nope'
        assert ro.theme_base() == ro.DEFAULT_BASE
        settings['obs_base_color'] = '#140A08'
        assert ro.theme_base() == '#140A08'


class TestPerSessionTheme:
    """The look follows the show-art ownership idiom: a session's own values
    live under 'obs_accent_color:s<id>' and win over the shared defaults."""

    @pytest.fixture()
    def session(self, app):
        from extensions import db
        from models.ttrpg import tblSessions
        s = tblSessions(title='Night 12', status='active',
                        created_at='2026-01-01 00:00:00')
        db.session.add(s)
        db.session.commit()
        return s

    def test_a_sessions_own_look_wins(self, app, settings, session):
        import routes.obs as ro
        settings['obs_accent_color'] = '#4a9eff'
        settings['obs_bezel_shape'] = 'square'
        settings[f'obs_accent_color:s{session.session_id}'] = '#9b6dff'
        settings[f'obs_base_color:s{session.session_id}'] = '#0c081a'
        settings[f'obs_bezel_shape:s{session.session_id}'] = 'hex'
        assert ro._theme_payload() == {'accent': '#9b6dff', 'base': '#0c081a',
                                       'base2': '#0c081a', 'dir': '180',
                                       'bezel': 'hex',
                                       'plate': '#0c081a', 'plate2': '#0c081a',
                                       'plate_dir': '180', 'card': 'classic',
                                       'tile': 'strip',
                                       'dm_icon': '⚔',
                                       'dm_title': 'Dungeon Master'}
        assert ro._theme_session_own() is True

    def test_a_session_without_its_own_inherits_the_shared_look(
            self, app, settings, session):
        import routes.obs as ro
        settings['obs_accent_color'] = '#4a9eff'
        settings['obs_bezel_shape'] = 'circle'
        assert ro._theme_payload() == {'accent': '#4a9eff',
                                       'base': ro.DEFAULT_BASE,
                                       'base2': ro.DEFAULT_BASE, 'dir': '180',
                                       'bezel': 'circle',
                                       'plate': ro.DEFAULT_BASE,
                                       'plate2': ro.DEFAULT_BASE,
                                       'plate_dir': '180', 'card': 'classic',
                                       'tile': 'strip',
                                       'dm_icon': '⚔',
                                       'dm_title': 'Dungeon Master'}
        assert ro._theme_session_own() is False

    def test_a_blanked_override_falls_back(self, app, settings, session):
        """What 'Back to the shared look' writes: empty strings."""
        import routes.obs as ro
        settings['obs_accent_color'] = '#4a9eff'
        settings[f'obs_accent_color:s{session.session_id}'] = ''
        settings[f'obs_bezel_shape:s{session.session_id}'] = ''
        assert ro._theme_payload()['accent'] == '#4a9eff'
        assert ro._theme_session_own() is False

    def test_no_active_session_reads_the_shared_look(self, app, settings):
        import routes.obs as ro
        settings['obs_accent_color'] = '#e05545'
        settings['obs_accent_color:s7'] = '#9b6dff'   # some ended session's
        assert ro._theme_payload()['accent'] == '#e05545'


class TestStreamNamesNeverShowLogins:
    """The overlay's second line is the human's DISPLAY name. Logins are
    credentials; they must never reach a page that goes out on stream."""

    def test_player_without_display_name_gets_no_line(self, app):
        from routes.obs import player_name_for
        from extensions import db
        from models.user import tblUsers
        from models.ttrpg import tblCharacters
        u = tblUsers(username='secretlogin', display_name='', password_hash='x',
                     role='player', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(u)
        db.session.flush()
        c = tblCharacters(user_id=u.user_id, name='Kara', level=1,
                          hp_current=1, hp_max=1,
                          created_at='2026-01-01 00:00:00')
        db.session.add(c)
        db.session.commit()
        assert player_name_for(c) == '', 'login must not leak as a fallback'

    def test_display_name_still_shows(self, app):
        from routes.obs import player_name_for
        from extensions import db
        from models.user import tblUsers
        from models.ttrpg import tblCharacters
        u = tblUsers(username='secretlogin', display_name='Sam the Bold',
                     password_hash='x', role='player', active=1,
                     created_at='2026-01-01 00:00:00')
        db.session.add(u)
        db.session.flush()
        c = tblCharacters(user_id=u.user_id, name='Kara', level=1,
                          hp_current=1, hp_max=1,
                          created_at='2026-01-01 00:00:00')
        db.session.add(c)
        db.session.commit()
        assert player_name_for(c) == 'Sam the Bold'

    def test_dm_line_is_display_name_never_login(self, app):
        from routes.obs import dm_player_name
        from extensions import db
        from models.user import tblUsers
        u = tblUsers(username='dmlogin', display_name='', password_hash='x',
                     role='dm', active=1, created_at='2026-01-01 00:00:00')
        db.session.add(u)
        db.session.commit()
        assert dm_player_name() == '', 'DM login must stay off the stream'

    def test_dm_display_name_not_repeated_under_the_title(self, app):
        """dm_name() already titles the tile with the display name; the second
        line saying it again is noise, so it stays empty."""
        from routes.obs import dm_player_name, dm_name
        from extensions import db
        from models.user import tblUsers
        u = tblUsers(username='dmlogin', display_name='Eric the DM',
                     password_hash='x', role='dm', active=1,
                     created_at='2026-01-01 00:00:00')
        db.session.add(u)
        db.session.commit()
        assert dm_name() == 'Eric the DM'
        assert dm_player_name() == ''


class TestArtUrlCacheBusting:
    """Art filenames are stable per slot (re-uploads overwrite in place), so
    every served URL must carry the file's mtime — that is what makes a
    re-upload visible to browser sources that cache by URL."""

    def test_url_carries_the_mtime_and_tracks_changes(self, app, monkeypatch,
                                                      tmp_path):
        import routes.obs as ro
        art = tmp_path / 'party-bg.jpg'
        art.write_bytes(b'x')
        monkeypatch.setattr(ro, 'BG_DIR', str(tmp_path))
        monkeypatch.setattr(ro, '_card_base', lambda: 'http://host:8086')
        u1 = ro._art_url('party-bg.jpg')
        assert u1.startswith('http://host:8086/static/uploads/obs/party-bg.jpg?v=')
        import os
        os.utime(art, (1, 1))            # a "re-upload" changes the mtime
        u2 = ro._art_url('party-bg.jpg')
        assert u1 != u2, 're-upload must produce a NEW url'

    def test_missing_file_still_yields_a_url(self, app, monkeypatch, tmp_path):
        import routes.obs as ro
        monkeypatch.setattr(ro, 'BG_DIR', str(tmp_path))
        monkeypatch.setattr(ro, '_card_base', lambda: 'http://host:8086')
        assert ro._art_url('gone.jpg').endswith('?v=0')
        assert ro._art_url('') == ''


class TestPlateAndCardDesign:
    """The camera tiles' name plate pair + the stat cards' layout pick."""

    def test_plate_follows_the_base_pair_until_set(self, app, settings):
        import routes.obs as ro
        settings['obs_base_color'] = '#140a08'
        settings['obs_base_color2'] = '#2c1009'
        assert ro.theme_plate() == '#140a08'
        assert ro.theme_plate2() == '#2c1009'

    def test_a_plate_colour_alone_renders_solid(self, app, settings):
        import routes.obs as ro
        settings['obs_plate_color'] = '#123456'
        assert ro.theme_plate() == '#123456'
        assert ro.theme_plate2() == '#123456', 'no second colour -> solid'

    def test_a_full_plate_pair_wins(self, app, settings):
        import routes.obs as ro
        settings['obs_plate_color'] = '#123456'
        settings['obs_plate_color2'] = '#654321'
        settings['obs_plate_dir'] = '90'
        assert ro.theme_plate2() == '#654321'
        assert ro.theme_plate_dir() == '90'

    def test_card_design_validates(self, app, settings):
        import routes.obs as ro
        assert ro.card_design() == 'classic'
        settings['obs_card_design'] = 'holographic'
        assert ro.card_design() == 'classic'
        for good in ('banner', 'trading'):
            settings['obs_card_design'] = good
            assert ro.card_design() == good


    def test_tile_design_validates(self, app, settings):
        import routes.obs as ro
        assert ro.tile_design() == 'strip'
        settings['obs_tile_design'] = 'billboard'
        assert ro.tile_design() == 'strip'
        for good in ('tag', 'third'):
            settings['obs_tile_design'] = good
            assert ro.tile_design() == good


    def test_dm_icon_and_title_validate(self, app, settings):
        import routes.obs as ro
        assert ro.dm_icon() == '⚔'
        settings['obs_dm_icon'] = '<script>'
        assert ro.dm_icon() == '⚔', 'off-roster symbols are refused'
        settings['obs_dm_icon'] = '⚙'
        assert ro.dm_icon() == '⚙'
        assert ro.dm_title() == 'Dungeon Master'
        settings['obs_dm_title'] = '  The AI  '
        assert ro.dm_title() == 'The AI'
        settings['obs_dm_title'] = 'x' * 99
        assert len(ro.dm_title()) == 40, 'capped'
