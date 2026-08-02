"""Token gates must reject cleanly, never crash.

hmac.compare_digest raises TypeError on non-ASCII strings, so a URL carrying
one turned a wrong token into a 500. A 500 on a broadcast endpoint is worse
than it looks: it is indistinguishable from the app being broken, which is
exactly the wrong signal while diagnosing a blank source."""
import pytest

from routes.obs import token_ok


class TestTokenOk:
    def test_matching_token_passes(self):
        assert token_ok('abc123', 'abc123')

    def test_wrong_token_fails(self):
        assert not token_ok('abc123', 'def456')

    @pytest.mark.parametrize('given', [
        '…',            # the ellipsis a copy-paste leaves behind
        'tok…en',
        'café',
        '\U0001f600',        # emoji
    ])
    def test_non_ascii_is_rejected_not_raised(self, given):
        assert token_ok(given, 'abc123') is False

    @pytest.mark.parametrize('given,expected', [
        (None, 'abc'), ('abc', None), (None, None), ('', ''), ('', 'abc'),
    ])
    def test_missing_values_never_raise(self, given, expected):
        assert token_ok(given, expected) in (True, False)

    def test_empty_matches_empty(self):
        """Not a security hole: the expected token is never empty in practice
        (it is an HMAC hex digest), so this only documents the edge."""
        assert token_ok('', '') is True

    def test_length_difference_is_not_an_error(self):
        assert not token_ok('short', 'a-much-longer-token-value')
