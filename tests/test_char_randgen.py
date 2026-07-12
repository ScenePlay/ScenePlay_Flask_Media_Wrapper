"""Random character generator: stat math, leveling, names, traits."""
import random

import pytest

from extensions import db
import char_randgen as rg


def _rng(seed=42):
    return random.Random(seed)


# ── Dice and stat assignment ───────────────────────────────────────────────────

def test_4d6_drop_lowest_range():
    rng = _rng()
    rolls = [rg.roll_4d6_drop_lowest(rng) for _ in range(2000)]
    assert all(3 <= r <= 18 for r in rolls)
    avg = sum(rolls) / len(rolls)
    assert 11.5 < avg < 13.0          # expected mean ~12.24


def test_stats_go_to_class_priorities():
    rng = _rng()
    for _ in range(50):
        rolls = rg.roll_stat_set(rng)
        stats = rg.assign_stats(rolls, 'Wizard', rng)
        assert stats['int'] == rolls[0]          # primary gets the best roll
        assert stats['con'] == rolls[1]
        assert sorted(stats.values(), reverse=True) == rolls


def test_racial_bonus_parsing():
    stats = dict.fromkeys(rg.ABILITIES, 10)
    rg.apply_racial_bonuses(stats, '+2 STR, +1 CHA')
    assert stats['str'] == 12 and stats['cha'] == 11
    assert stats['dex'] == 10


def test_asi_pumps_primary_then_overflows():
    stats = dict.fromkeys(rg.ABILITIES, 10)
    stats['str'] = 16
    rg.apply_asis(stats, 'Fighter', 2)           # 4 points
    assert stats['str'] == 20                    # 16 -> 20
    rg.apply_asis(stats, 'Fighter', 1)           # overflow to CON
    assert stats['str'] == 20 and stats['con'] == 12


def test_hp_formula():
    assert rg.hp_for(1, 10, 2) == 12             # max die + con
    assert rg.hp_for(10, 12, 3) == 12 + 9 * 7 + 30   # L10 barbarian, CON +3
    assert rg.hp_for(1, 6, -5) >= 1              # never below 1


def test_prof_bonus_fallback():
    assert [rg.prof_bonus_for(l) for l in (1, 4, 5, 9, 13, 17, 20)] == \
           [2, 2, 3, 4, 5, 6, 6]


# ── Names ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('race', list(rg.NAME_PARTS) + ['Half-Elf', 'Nonsense'])
def test_names_are_first_last(race):
    rng = _rng()
    for _ in range(20):
        name = rg.generate_name(race, rng)
        first, last = name.split(' ')
        assert first[0].isupper() and last[0].isupper()


def test_names_are_race_flavored():
    rng = _rng()
    dwarf = rg.generate_name('Dwarf', rng)
    starts, _ = rg.NAME_PARTS['Dwarf']['first']
    assert any(dwarf.startswith(s) for s in starts)


# ── Traits ─────────────────────────────────────────────────────────────────────

def test_trait_tables_shape():
    assert len(rg.TRAIT_TABLES) == 13
    for bg, table in rg.TRAIT_TABLES.items():
        assert len(table['traits']) == 8, bg
        for key in ('ideals', 'bonds', 'flaws'):
            assert len(table[key]) == 6, (bg, key)


def test_generate_traits():
    traits = rg.generate_traits('Soldier', _rng())
    assert len(traits['personality']) == 2
    assert traits['personality'][0] != traits['personality'][1]
    note = rg.format_traits_note(traits)
    for label in ('Personality:', 'Ideal:', 'Bond:', 'Flaw:'):
        assert label in note
    fallback = rg.generate_traits('No Such Background', _rng())
    assert fallback['ideal']


# ── Full assembly against seeded library tables ───────────────────────────────

@pytest.fixture()
def library(app):
    from models.ttrpg import (
        tblClassesLibrary, tblClassLevelsLibrary, tblRacesLibrary,
        tblSubclassesLibrary,
    )
    db.session.add(tblClassesLibrary(
        name='Fighter', hit_die=10, created_at='2026-01-01'))
    db.session.add(tblRacesLibrary(
        name='Dwarf', speed=25, ability_bonuses='+2 CON', created_at='2026-01-01'))
    db.session.add(tblSubclassesLibrary(
        name='Champion', class_name='Fighter', created_at='2026-01-01'))
    for lvl in range(1, 21):
        feats = 'Ability Score Improvement' if lvl in (4, 6, 8, 12, 14, 16, 19) else ''
        db.session.add(tblClassLevelsLibrary(
            api_index=f'fighter-{lvl}', class_name='Fighter', level=lvl,
            prof_bonus=2 + (lvl - 1) // 4, features_text=feats,
            created_at='2026-01-01'))
    db.session.commit()


def test_generate_character_full(library):
    c = rg.generate_character(min_level=10, max_level=10, rng=_rng())
    assert c['level'] == 10
    assert c['char_class'] == 'Fighter' and c['race'] == 'Dwarf'
    assert c['subclass'] == 'Champion'
    assert c['speed'] == 25

    con_mod = (c['con_val'] - 10) // 2
    assert c['hp_max'] == 10 + 9 * 6 + con_mod * 10   # d10, official average
    assert c['prof_bonus'] == 4
    assert c['ac'] == 10 + (c['dex_val'] - 10) // 2
    assert c['passive_perception'] == 10 + (c['wis_val'] - 10) // 2
    assert 'Personality:' in c['traits_note']
    assert len(c['name'].split(' ')) == 2


def test_generate_character_level1_no_subclass(library):
    c = rg.generate_character(min_level=1, max_level=1, rng=_rng())
    assert c['level'] == 1
    assert c['subclass'] == ''
    con_mod = (c['con_val'] - 10) // 2
    assert c['hp_max'] == 10 + con_mod


def test_generate_character_asis_raise_primary(library):
    lo = rg.generate_character(min_level=1, max_level=1, rng=_rng(7))
    hi = rg.generate_character(min_level=20, max_level=20, rng=_rng(7))
    # same seed -> same rolls; the level-20 version has 7 ASIs (14 points)
    assert hi['str_val'] >= min(20, lo['str_val'] + 4)
