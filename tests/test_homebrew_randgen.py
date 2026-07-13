"""Homebrew randomizer: monsters, vehicles, assets across genres and tiers."""
import random

import pytest

import homebrew_randgen as hr

FORM_FIELDS = {'name', 'monster_type', 'size', 'alignment', 'speed', 'cr', 'xp',
               'hp_max', 'ac', 'languages', 'notes',
               'str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val'}


def _rng(seed=42):
    return random.Random(seed)


@pytest.mark.parametrize('kind', ['monster', 'vehicle', 'asset'])
@pytest.mark.parametrize('genre', list(hr.GENRE_DATA))
def test_all_kinds_and_genres(kind, genre):
    d = hr.generate_homebrew(kind=kind, genre=genre, tier='standard', rng=_rng())
    assert FORM_FIELDS <= set(d)
    assert d['kind'] == kind and d['genre'] == genre
    assert d['name'].strip() and d['monster_type'].strip() and d['notes'].strip()
    assert d['hp_max'] >= 5 and 11 <= d['ac'] <= 19
    assert '{' not in d['notes']            # every template slot filled
    for a in hr.ABILITIES:
        assert 0 <= d[a] <= 30


@pytest.mark.parametrize('tier,pool', list(hr.TIERS.items()))
def test_tier_cr_and_xp(tier, pool):
    for seed in range(10):
        d = hr.generate_homebrew(tier=tier, rng=_rng(seed))
        assert d['cr'] in pool
        assert d['xp'] == hr.XP_BY_CR[d['cr']]


def test_kind_conventions():
    v = hr.generate_homebrew(kind='vehicle', rng=_rng())
    assert v['monster_type'].startswith('vehicle')
    assert v['name'].startswith('The ')
    assert v['size'] in ('Large', 'Huge', 'Gargantuan')
    a = hr.generate_homebrew(kind='asset', rng=_rng())
    assert a['monster_type'].startswith('object')
    assert a['speed'] == '0'


def test_fallbacks():
    d = hr.generate_homebrew(kind='nope', genre='nope', tier='nope', rng=_rng())
    assert d['kind'] == 'monster' and d['genre'] == 'fantasy'
    assert d['cr'] in hr.TIERS['standard']


def test_scaling_boss_tougher_than_minion():
    lo = hr.generate_homebrew(tier='minion', rng=_rng(7))
    hi = hr.generate_homebrew(tier='legendary', rng=_rng(7))
    assert hi['hp_max'] > lo['hp_max'] and hi['xp'] > lo['xp']
