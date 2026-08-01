"""The battle map's closeup picker feed (/obs/api/closeups).

The panel exists so the DM can cut to a person BY NAME mid-sentence instead of
counting tiles to find their number key. So the two things that matter are that
every row is a valid closeup target (a benched player has no tile, and cutting
to them would just fail), and that the positions shown match the number keys.
"""
import pytest

from routes import obs as obs_routes


class Char:
    def __init__(self, cid, name):
        self.character_id = cid
        self.name = name
        self.video_feed_url = ''
        self.video_stream_id = ''


@pytest.fixture
def settings(monkeypatch):
    store = {}
    monkeypatch.setattr(obs_routes, 'appsettingGet',
                        lambda k, d='': store.get(k, d))
    monkeypatch.setattr(obs_routes, 'appsettingSet',
                        lambda k, v: store.__setitem__(k, v))
    return store


@pytest.fixture
def party(app, settings, monkeypatch):
    """Three players and no saved tile order, so _ordered_party falls back to
    sorting by name — Aldric(3), Lyra(2), Thorin(1). The expectations below
    follow that, not the order they are declared in."""
    people = [Char(1, 'Thorin'), Char(2, 'Lyra'), Char(3, 'Aldric')]
    monkeypatch.setattr(obs_routes, '_active_party', lambda: list(people))
    monkeypatch.setattr(obs_routes, 'dm_tile_enabled', lambda: False)
    monkeypatch.setattr(obs_routes, '_presence', lambda: {})
    monkeypatch.setattr(obs_routes, '_card_overrides', lambda: set())
    monkeypatch.setattr(obs_routes, '_feed_state', lambda c, p: 'ready')
    monkeypatch.setattr(obs_routes, '_tile_url',
                        lambda c, p=None, o=None: 'http://cam/' + str(c.character_id))
    monkeypatch.setattr(obs_routes, '_card_base', lambda: 'http://card')
    monkeypatch.setattr(obs_routes, 'player_name_for',
                        lambda c: {1: 'Dave', 2: 'Sam', 3: 'Priya'}[c.character_id])
    monkeypatch.setattr(obs_routes, 'featured_id', lambda: None)
    return people


def rows():
    return obs_routes._closeup_rows()


class TestCloseupRows:
    def test_lists_the_whole_party_by_default(self, party):
        assert [r['name'] for r in rows()] == ['Aldric', 'Lyra', 'Thorin']

    def test_carries_the_player_behind_the_character(self, party):
        """The point of the panel: 'get Dave on camera', not 'press 3'."""
        assert [(r['name'], r['player']) for r in rows()] == [
            ('Aldric', 'Priya'), ('Lyra', 'Sam'), ('Thorin', 'Dave')]

    def test_a_benched_player_is_not_offered(self, party):
        """They have no tile, so a closeup on them could only fail."""
        obs_routes._set_offstage(2, True)          # Lyra
        assert [r['name'] for r in rows()] == ['Aldric', 'Thorin']

    def test_positions_match_the_number_keys(self, party):
        """Benching renumbers the rotation; the panel must renumber with it."""
        obs_routes._set_offstage(1, True)
        got = rows()
        assert [r['pos'] for r in got] == [1, 2]
        assert [r['character_id'] for r in got] == obs_routes._rotation_order()

    def test_marks_who_is_already_spotlit(self, party, monkeypatch):
        monkeypatch.setattr(obs_routes, 'featured_id', lambda: 2)
        assert [r['featured'] for r in rows()] == [False, True, False]

    def test_flags_a_tile_showing_a_stat_card(self, party, monkeypatch):
        """It changes what the closeup will actually look like on stream."""
        monkeypatch.setattr(obs_routes, '_tile_url',
                            lambda c, p=None, o=None:
                            'http://card/x' if c.character_id == 3 else 'http://cam/x')
        assert [r['showing'] for r in rows()] == ['card', 'camera', 'camera']

    def test_reports_camera_state_per_row(self, party, monkeypatch):
        monkeypatch.setattr(obs_routes, '_feed_state',
                            lambda c, p: 'nofeed' if c.character_id == 1 else 'live')
        assert [r['feed'] for r in rows()] == ['live', 'live', 'nofeed']

    def test_an_empty_feed_is_reported_not_crashed(self, party):
        for cid in (1, 2, 3):
            obs_routes._set_offstage(cid, True)
        assert rows() == []


class TestCuttingToGroupEndsTheCloseup:
    """The way back from a closeup.

    Cutting to the group shot means everyone equal, so it has to clear the
    spotlight as well as switch scene — otherwise the button puts the party
    scene up still reflowed around a doubled tile and there is no route back
    to the even grid."""

    @pytest.fixture
    def obs(self, monkeypatch):
        calls = {'synced': [], 'featured': [], 'switched': []}
        monkeypatch.setattr(obs_routes, '_sync_party_scene',
                            lambda featured_id=None: calls['synced'].append(featured_id))
        monkeypatch.setattr(obs_routes, '_set_featured',
                            lambda cid: calls['featured'].append(cid))
        monkeypatch.setattr(obs_routes, '_cancel_return', lambda: None)
        monkeypatch.setattr(obs_routes, 'viewed_character_id', lambda: None)
        monkeypatch.setattr(obs_routes, '_set_viewed_character', lambda _c: None)
        monkeypatch.setattr(obs_routes, '_cut_scene_name', lambda k: 'Party')

        import obs_ws
        monkeypatch.setattr(obs_ws, 'connected', lambda: True)
        monkeypatch.setattr(obs_ws, 'scene_list', lambda **k: (['Party'], 'Party'))
        monkeypatch.setattr(obs_ws, 'switch_scene',
                            lambda name, **k: calls['switched'].append(name))
        return calls

    def _cut(self, key, app):
        with app.test_request_context():
            return obs_routes.api_cut.__wrapped__.__wrapped__(key).get_json()

    def test_levels_the_grid_when_someone_is_spotlit(self, app, obs, monkeypatch):
        monkeypatch.setattr(obs_routes, 'featured_id', lambda: 7)
        body = self._cut('party', app)
        assert body['levelled'] is True
        assert obs['synced'] == [None], 'the grid was left reflowed'
        assert obs['featured'] == [None]
        assert obs['switched'] == ['Party']

    def test_does_no_extra_work_when_nobody_is_spotlit(self, app, obs, monkeypatch):
        monkeypatch.setattr(obs_routes, 'featured_id', lambda: None)
        body = self._cut('party', app)
        assert body['levelled'] is False
        assert obs['synced'] == []
        assert obs['switched'] == ['Party']

    def test_other_cuts_leave_the_spotlight_alone(self, app, obs, monkeypatch):
        """Cutting to the map mid-closeup should not silently reset the party
        scene behind it — coming back via the group button is what does that."""
        monkeypatch.setattr(obs_routes, 'featured_id', lambda: 7)
        body = self._cut('map', app)
        assert body['levelled'] is False
        assert obs['synced'] == []
        assert obs['featured'] == []
