"""Which character the 3D view stands in.

The rule is "whoever moved last", read off tblBattleMapTokens.updated_at. The
awkward part is that updated_at is stamped by things that are NOT moves —
activating a map stamps every token at once, a grid resize stamps each token
it clamps — so the tests below are mostly about not mistaking those for a
move and pointing the camera somewhere arbitrary mid-broadcast."""
import pytest

from routes.obs import _last_moved_token_id


class _Tok:
    def __init__(self, token_id, entity_type='player', updated_at=''):
        self.token_id = token_id
        self.entity_type = entity_type
        self.updated_at = updated_at


class _Map:
    def __init__(self, tokens):
        self.tokens = tokens


def _bm(*tokens):
    return _Map(list(tokens))


class TestLastMoved:
    def test_picks_the_newest_stamp(self):
        bm = _bm(_Tok(1, updated_at='2026-07-30T10:00:00+00:00'),
                 _Tok(2, updated_at='2026-07-30T12:00:00+00:00'),
                 _Tok(3, updated_at='2026-07-30T11:00:00+00:00'))
        assert _last_moved_token_id(bm) == 2

    def test_map_activation_is_not_a_move(self):
        """Activating a map stamps every token with one timestamp. Treating
        that as a move would drop the camera into a random character the
        instant a map goes live."""
        ts = '2026-07-30T12:00:00+00:00'
        bm = _bm(_Tok(1, updated_at=ts), _Tok(2, updated_at=ts), _Tok(3, updated_at=ts))
        assert _last_moved_token_id(bm) is None

    def test_a_tie_at_the_top_is_not_a_move(self):
        """A resize clamps several tokens at once — same signature as above,
        even when older tokens sit below the tie."""
        ts = '2026-07-30T12:00:00+00:00'
        bm = _bm(_Tok(1, updated_at='2026-07-30T09:00:00+00:00'),
                 _Tok(2, updated_at=ts), _Tok(3, updated_at=ts))
        assert _last_moved_token_id(bm) is None

    def test_monsters_never_become_the_viewpoint(self):
        """Standing in a monster's shoes would leak where the DM hid it: the
        token is filtered out of the payload, but the camera position would
        give it away regardless."""
        bm = _bm(_Tok(1, updated_at='2026-07-30T10:00:00+00:00'),
                 _Tok(9, entity_type='monster', updated_at='2026-07-30T23:00:00+00:00'))
        assert _last_moved_token_id(bm) == 1

    def test_monster_tie_does_not_suppress_a_player_move(self):
        """Monsters are dropped BEFORE the tie check, so two monsters sharing
        the newest stamp must not blank out the player who actually moved."""
        ts = '2026-07-30T23:00:00+00:00'
        bm = _bm(_Tok(1, updated_at='2026-07-30T10:00:00+00:00'),
                 _Tok(8, entity_type='monster', updated_at=ts),
                 _Tok(9, entity_type='monster', updated_at=ts))
        assert _last_moved_token_id(bm) == 1

    @pytest.mark.parametrize('stamp', ['', '   ', None])
    def test_unstamped_tokens_are_ignored(self, stamp):
        bm = _bm(_Tok(1, updated_at=stamp),
                 _Tok(2, updated_at='2026-07-30T10:00:00+00:00'))
        assert _last_moved_token_id(bm) == 2

    def test_nothing_stamped_falls_back(self):
        """None means map_state uses the featured player instead."""
        assert _last_moved_token_id(_bm(_Tok(1), _Tok(2))) is None

    def test_empty_map(self):
        assert _last_moved_token_id(_bm()) is None

    def test_only_monsters(self):
        bm = _bm(_Tok(9, entity_type='monster', updated_at='2026-07-30T10:00:00+00:00'))
        assert _last_moved_token_id(bm) is None

    def test_stamps_compare_chronologically_as_strings(self):
        """Both writers use datetime.isoformat() in UTC, so plain string
        ordering is chronological — including across a day boundary, where a
        naive comparison of unpadded values would fail."""
        bm = _bm(_Tok(1, updated_at='2026-07-30T23:59:59+00:00'),
                 _Tok(2, updated_at='2026-07-31T00:00:01+00:00'))
        assert _last_moved_token_id(bm) == 2
