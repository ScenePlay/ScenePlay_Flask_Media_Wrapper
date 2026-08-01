"""Benching a player from the group feed.

A player who can't make this episode — or the half of a split party the stream
isn't following — comes off the party scene without leaving the session. The
rules that matter: benching removes their tile AND their turn (so the number
keys keep matching what is on screen), the Broadcast page still lists them (or
there would be no way back), and nothing about their session seat changes.
"""
import pytest

from routes import obs as obs_routes


@pytest.fixture
def settings(monkeypatch):
    """In-memory app settings, so nothing here touches a database."""
    store = {}
    monkeypatch.setattr(obs_routes, 'appsettingGet',
                        lambda k, d='': store.get(k, d))
    monkeypatch.setattr(obs_routes, 'appsettingSet',
                        lambda k, v: store.__setitem__(k, v))
    return store


class Char:
    def __init__(self, cid, name):
        self.character_id = cid
        self.name = name


@pytest.fixture
def party(app, monkeypatch):
    """Three players and no saved tile order, so they fall out by name.
    `app` gives _ordered_party a real (empty) tblObsSceneMap to query."""
    people = [Char(1, 'Alice'), Char(2, 'Bob'), Char(3, 'Cara')]
    monkeypatch.setattr(obs_routes, '_active_party', lambda: list(people))
    monkeypatch.setattr(obs_routes, 'dm_tile_enabled', lambda: False)
    return people


class TestOffstageSet:
    def test_nobody_is_benched_on_a_fresh_install(self, settings):
        assert obs_routes.offstage_ids() == set()

    def test_benching_and_restoring_round_trip(self, settings):
        obs_routes._set_offstage(2, True)
        assert obs_routes.offstage_ids() == {2}
        obs_routes._set_offstage(2, False)
        assert obs_routes.offstage_ids() == set()

    def test_the_dm_tile_can_be_benched_too(self, settings):
        """Its id is negative, which a naive isdigit() parse would drop."""
        obs_routes._set_offstage(obs_routes.DM_TILE_ID, True)
        assert obs_routes.DM_TILE_ID in obs_routes.offstage_ids()

    def test_benching_twice_does_not_duplicate(self, settings):
        obs_routes._set_offstage(2, True)
        obs_routes._set_offstage(2, True)
        assert settings['obs_offstage'] == '2'

    def test_survives_a_rubbish_setting(self, settings):
        settings['obs_offstage'] = '1,,junk, 3 ,'
        assert obs_routes.offstage_ids() == {1, 3}


class TestOrderedParty:
    def test_everyone_is_on_stream_by_default(self, settings, party):
        assert [c.name for c in obs_routes._ordered_party()] == \
               ['Alice', 'Bob', 'Cara']

    def test_a_benched_player_loses_their_tile(self, settings, party):
        obs_routes._set_offstage(2, True)
        assert [c.name for c in obs_routes._ordered_party()] == ['Alice', 'Cara']

    def test_a_benched_player_loses_their_turn(self, settings, party):
        """Otherwise pressing 2 would feature a tile that is not on screen."""
        obs_routes._set_offstage(2, True)
        assert obs_routes._rotation_order() == [1, 3]

    def test_the_broadcast_page_still_lists_them(self, settings, party):
        obs_routes._set_offstage(2, True)
        listed = obs_routes._ordered_party(include_offstage=True)
        assert [c.name for c in listed] == ['Alice', 'Bob', 'Cara']

    def test_restoring_puts_them_back_in_their_old_place(self, settings, party):
        obs_routes._set_offstage(2, True)
        obs_routes._set_offstage(2, False)
        assert obs_routes._rotation_order() == [1, 2, 3]

    def test_benching_everyone_is_survivable(self, settings, party):
        for cid in (1, 2, 3):
            obs_routes._set_offstage(cid, True)
        assert obs_routes._ordered_party() == []
        assert obs_routes._rotation_order() == []
