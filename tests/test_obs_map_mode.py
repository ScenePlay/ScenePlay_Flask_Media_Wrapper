"""How the map source's render mode is stored and stepped.

'auto' is the interesting one: it is the default, and it is what the source
reads to decide whether it may cut to the featured player's 3D view when they
move. A mode that silently degraded to '2d' would disable that behaviour with
no visible sign, so the coercion rules get their own tests."""
import pytest

from routes.obs import MAP_MODES, map_mode


@pytest.fixture()
def settings(app, monkeypatch):
    """appsettingGet/Set talk to the real sqlite file — stub both per test.

    routes.obs did `from sql import ...` at module load and holds its own
    references, so patching sql alone would still read the live database."""
    store = {}
    import routes.obs as ro
    import sql
    get = lambda name, default=None: store.get(name, default)     # noqa: E731
    put = lambda name, value: store.__setitem__(name, value)      # noqa: E731
    for mod in (sql, ro):
        monkeypatch.setattr(mod, 'appsettingGet', get, raising=False)
        monkeypatch.setattr(mod, 'appsettingSet', put, raising=False)
    return store


class TestMapMode:
    def test_defaults_to_auto(self, settings):
        """Unset means auto — the mode that needs no attention during play."""
        assert map_mode() == 'auto'

    @pytest.mark.parametrize('stored', MAP_MODES)
    def test_round_trips_every_mode(self, settings, stored):
        settings['obs_map_mode'] = stored
        assert map_mode() == stored

    @pytest.mark.parametrize('stored', ['', '  ', 'AUTO', ' 3D ', 'garbage', None])
    def test_coerces_junk_to_a_usable_mode(self, settings, stored):
        settings['obs_map_mode'] = stored
        assert map_mode() in MAP_MODES

    def test_case_and_padding_are_not_a_different_mode(self, settings):
        settings['obs_map_mode'] = ' 3D '
        assert map_mode() == '3d'

    def test_empty_row_falls_back_to_auto(self, settings):
        """A blank row is not 'absent', so the appsettingGet default never
        fires — the explicit coercion is what has to catch it."""
        settings['obs_map_mode'] = ''
        assert map_mode() == 'auto'


class TestModeCycle:
    def test_cycle_visits_every_mode_and_returns(self):
        """The sidebar button and the V hotkey send no mode and rely on the
        server stepping this list, so it must be a closed loop."""
        seen, cur = [], MAP_MODES[0]
        for _ in range(len(MAP_MODES)):
            cur = MAP_MODES[(MAP_MODES.index(cur) + 1) % len(MAP_MODES)]
            seen.append(cur)
        assert sorted(seen) == sorted(MAP_MODES)
        assert cur == MAP_MODES[0]

    def test_auto_is_first(self):
        """Cycling starts from auto, so a DM who never touches the button
        gets the hands-off behaviour."""
        assert MAP_MODES[0] == 'auto'
