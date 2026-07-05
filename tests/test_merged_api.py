"""Merged 2024+2014 API fetch layer (routes/reference.py).

requests and get_api_base are monkeypatched, so these run offline and never
touch the app database.
"""

import pytest

import routes.reference as ref


class FakeResp:
    def __init__(self, payload=None, ok=True):
        self._payload = payload or {}
        self.ok = ok
        self.content = b'x' if ok else b''

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError('http error')

    def json(self):
        return self._payload


def fake_requests(routes):
    """Stub for the `requests` module: routes maps url -> payload dict,
    anything else raises like a network failure."""
    class _R:
        @staticmethod
        def get(url, timeout=None):
            if url in routes:
                return FakeResp(routes[url])
            raise RuntimeError(f'404 {url}')
    return _R


def entries(base, *indexes):
    return {'results': [{'index': i, 'name': i.title()} for i in indexes]}


@pytest.fixture
def merged_mode(monkeypatch):
    monkeypatch.setattr(ref, 'get_api_base', lambda: ref.MERGED_API)


class TestMergedResourceList:
    def test_2024_wins_and_2014_fills_gaps(self, merged_mode, monkeypatch):
        monkeypatch.setattr(ref, 'requests', fake_requests({
            f'{ref.API_2024}/feats': entries(ref.API_2024, 'alert', 'grappler'),
            f'{ref.API_2014}/feats': entries(ref.API_2014, 'grappler', 'lucky'),
        }))
        out, err = ref.merged_resource_list('feats')
        assert err is None
        got = {e['index']: base for e, base in out}
        assert got == {'alert': ref.API_2024,
                       'grappler': ref.API_2024,   # duplicate index -> 2024 wins
                       'lucky': ref.API_2014}

    def test_endpoint_missing_on_2024_falls_back(self, merged_mode, monkeypatch):
        # 2024 has no /spells at all — everything comes from 2014, no error
        monkeypatch.setattr(ref, 'requests', fake_requests({
            f'{ref.API_2014}/spells': entries(ref.API_2014, 'fireball', 'shield'),
        }))
        out, err = ref.merged_resource_list('spells')
        assert err is None
        assert [e['index'] for e, _ in out] == ['fireball', 'shield']
        assert all(base == ref.API_2014 for _, base in out)

    def test_all_sources_down_reports_error(self, merged_mode, monkeypatch):
        monkeypatch.setattr(ref, 'requests', fake_requests({}))
        out, err = ref.merged_resource_list('spells')
        assert out == [] and err

    def test_single_base_mode_only_uses_that_base(self, monkeypatch):
        monkeypatch.setattr(ref, 'get_api_base', lambda: ref.API_2014)
        monkeypatch.setattr(ref, 'requests', fake_requests({
            f'{ref.API_2014}/feats': entries(ref.API_2014, 'grappler'),
            f'{ref.API_2024}/feats': entries(ref.API_2024, 'alert'),
        }))
        out, err = ref.merged_resource_list('feats')
        assert err is None
        assert [e['index'] for e, _ in out] == ['grappler']

    def test_races_alias_hits_species_on_2024(self, merged_mode, monkeypatch):
        monkeypatch.setattr(ref, 'requests', fake_requests({
            f'{ref.API_2024}/species': entries(ref.API_2024, 'dwarf'),
            f'{ref.API_2014}/races':   entries(ref.API_2014, 'dwarf', 'gnome'),
        }))
        out, err = ref.merged_resource_list('races')
        assert err is None
        got = {e['index']: base for e, base in out}
        assert got['dwarf'] == ref.API_2024 and got['gnome'] == ref.API_2014


class TestMergedCategoryList:
    def test_per_version_category_slug(self, merged_mode, monkeypatch):
        monkeypatch.setattr(ref, 'requests', fake_requests({
            f'{ref.API_2024}/equipment-categories/weapons':
                {'equipment': [{'index': 'longsword', 'name': 'Longsword'}]},
            f'{ref.API_2014}/equipment-categories/weapon':
                {'equipment': [{'index': 'longsword', 'name': 'Longsword'},
                               {'index': 'club', 'name': 'Club'}]},
        }))
        out, err = ref.merged_category_list({'2014': 'weapon', '2024': 'weapons'})
        assert err is None
        got = {e['index']: base for e, base in out}
        assert got == {'longsword': ref.API_2024, 'club': ref.API_2014}


class TestShapeHelpers:
    def test_desc_text_variants(self):
        assert ref._desc_text({'desc': ['a', 'b']}) == 'a\nb'
        assert ref._desc_text({'desc': 'plain string'}) == 'plain string'
        assert ref._desc_text({'description': 'from 2024'}) == 'from 2024'
        assert ref._desc_text({}) == ''

    def test_feature_level_variants(self):
        assert ref._feature_level({'level': 3}) == 3
        assert ref._feature_level({'level': {'index': 'barbarian-4'}}) == 4
        assert ref._feature_level({'level': {'index': 'barbarian-4-nyi'}}) == 4
        assert ref._feature_level({}) == 0

    def test_resource_path_alias(self):
        assert ref._resource_path(ref.API_2024, 'races') == 'species'
        assert ref._resource_path(ref.API_2014, 'races') == 'races'
        assert ref._resource_path(ref.API_2024, 'conditions') == 'conditions'
