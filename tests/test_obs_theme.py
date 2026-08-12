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
                                       'bezel': 'circle'}

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
                                       'bezel': 'hex'}
        assert ro._theme_session_own() is True

    def test_a_session_without_its_own_inherits_the_shared_look(
            self, app, settings, session):
        import routes.obs as ro
        settings['obs_accent_color'] = '#4a9eff'
        settings['obs_bezel_shape'] = 'circle'
        assert ro._theme_payload() == {'accent': '#4a9eff',
                                       'base': ro.DEFAULT_BASE,
                                       'base2': ro.DEFAULT_BASE, 'dir': '180',
                                       'bezel': 'circle'}
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
