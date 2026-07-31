"""How often a stat card re-checks HP and conditions.

Worth its own tests because the cost is paid per card: every player in the
party scene runs this loop in a separate browser source, so the served request
rate is the interval divided by the size of the table. A silent fallback to a
small number would quietly put that back."""
import pytest

from routes.obs import CARD_POLL_DEFAULT, card_poll_s


@pytest.fixture()
def settings(app, monkeypatch):
    """routes.obs holds its own reference from `from sql import ...`, so
    patching sql alone would still read the live database."""
    store = {}
    import routes.obs as ro
    import sql
    get = lambda name, default=None: store.get(name, default)     # noqa: E731
    for mod in (sql, ro):
        monkeypatch.setattr(mod, 'appsettingGet', get, raising=False)
    return store


class TestCardPoll:
    def test_default_is_slow_enough_to_be_free(self, settings):
        """HP and conditions move at the pace of a turn, not a frame."""
        assert card_poll_s() == CARD_POLL_DEFAULT
        assert CARD_POLL_DEFAULT >= 10

    @pytest.mark.parametrize('raw,want', [
        ('30', 30.0),
        ('2', 2.0),
        ('15.5', 15.5),
    ])
    def test_honours_a_valid_setting(self, settings, raw, want):
        settings['obs_card_poll_s'] = raw
        assert card_poll_s() == want

    @pytest.mark.parametrize('raw', ['0', '0.5', '-5'])
    def test_clamps_up_off_a_hammering_value(self, settings, raw):
        """A typo of 0 must not turn every card into a busy loop."""
        settings['obs_card_poll_s'] = raw
        assert card_poll_s() == 2

    def test_clamps_down_an_absurd_value(self, settings):
        settings['obs_card_poll_s'] = '9999'
        assert card_poll_s() == 120

    @pytest.mark.parametrize('raw', ['', '   ', 'junk', None])
    def test_junk_falls_back_to_the_default(self, settings, raw):
        """A blank row is not 'absent', so appsettingGet's own default never
        fires — the explicit coercion is what has to catch it."""
        settings['obs_card_poll_s'] = raw
        assert card_poll_s() == CARD_POLL_DEFAULT

    def test_whitespace_is_not_a_different_value(self, settings):
        settings['obs_card_poll_s'] = ' 20 '
        assert card_poll_s() == 20.0
