"""Genre packs: shape validation, genre names, genre-aware generation."""
import random

import pytest

from extensions import db
import char_randgen as rg
import genre_packs as gp

ALL_CLASSES = list(rg.CLASS_PRIORITIES)
ALL_RACES = ['Dragonborn', 'Dwarf', 'Elf', 'Gnome', 'Goliath', 'Half-Elf',
             'Half-Orc', 'Halfling', 'Human', 'Orc', 'Tiefling']


def _rng(seed=42):
    return random.Random(seed)


@pytest.mark.parametrize('key', list(gp.GENRE_PACKS))
def test_pack_shape(key):
    pack = gp.GENRE_PACKS[key]
    assert pack['label']
    for cls in ALL_CLASSES:
        assert pack['class_skins'][cls], (key, cls)
    for race in ALL_RACES:
        assert pack['race_skins'][race], (key, race)
    assert len(pack['art_style']) >= 3
    assert len(pack['backgrounds']) >= 5
    for bg, table in pack['backgrounds'].items():
        assert len(table['traits']) >= 2, (key, bg)
        for k in ('ideals', 'bonds', 'flaws'):
            assert len(table[k]) >= 2, (key, bg, k)


@pytest.mark.parametrize('key', list(gp.GENRE_PACKS))
def test_genre_names(key):
    rng = _rng()
    for level in (1, 10, 20):
        name = gp.generate_genre_name(key, level, rng)
        assert name and name.strip() == name


def test_rank_names_scale_with_level():
    assert gp.generate_genre_name('voidmarines', 1, _rng()).startswith('Recruit ')
    assert gp.generate_genre_name('voidmarines', 20, _rng()).startswith('Captain ')
    assert gp.generate_genre_name('spacefaring', 1, _rng()).startswith('Ensign ')


def test_genre_display_and_fallbacks():
    assert gp.genre_display('wasteland', 'Fighter', 'Human') == ('Road Warrior', 'Settler')
    assert gp.genre_display('fantasy', 'Fighter', 'Human') == ('', '')
    assert gp.generate_genre_name('fantasy', 5, _rng()) is None
    labels = gp.genre_labels()
    assert labels[0][0] == 'fantasy'
    assert len(labels) == 1 + len(gp.GENRE_PACKS)


def test_client_data_shape():
    data = gp.client_data()
    for key, entry in data.items():
        assert set(entry) == {'label', 'class_skins', 'race_skins', 'art_style'}


def test_genre_traits_from_pack_tables():
    pack = gp.GENRE_PACKS['litrpg']
    bg = 'Line Cook'
    traits = rg.generate_traits(bg, _rng(), tables=pack['backgrounds'])
    table = pack['backgrounds'][bg]
    assert all(t in table['traits'] for t in traits['personality'])
    assert traits['ideal'] in table['ideals']


# ── Full generation with a genre ───────────────────────────────────────────────

@pytest.fixture()
def library(app):
    from models.ttrpg import (
        tblClassesLibrary, tblClassLevelsLibrary, tblRacesLibrary,
    )
    db.session.add(tblClassesLibrary(
        name='Fighter', hit_die=10, created_at='2026-01-01'))
    db.session.add(tblRacesLibrary(
        name='Human', speed=30, ability_bonuses='+1 STR', created_at='2026-01-01'))
    for lvl in range(1, 21):
        db.session.add(tblClassLevelsLibrary(
            api_index=f'fighter-{lvl}', class_name='Fighter', level=lvl,
            prof_bonus=2 + (lvl - 1) // 4, features_text='',
            created_at='2026-01-01'))
    db.session.commit()


def test_generate_character_with_genre(library):
    c = rg.generate_character(min_level=8, max_level=8, rng=_rng(),
                              genre='wasteland')
    assert c['genre'] == 'wasteland'
    assert c['archetype'] == 'Road Warrior'      # Fighter skin
    assert c['species'] == 'Settler'             # Human skin
    assert c['background'] in gp.GENRE_PACKS['wasteland']['backgrounds']
    assert c['char_class'] == 'Fighter'          # mechanics stay 5e underneath
    assert 'Personality:' in c['traits_note']


def test_generate_character_fantasy_unchanged(library):
    c = rg.generate_character(min_level=3, max_level=3, rng=_rng())
    assert c['genre'] == 'fantasy'
    assert c['archetype'] == '' and c['species'] == ''
    assert c['background'] in rg.BACKGROUNDS


def test_generate_character_unknown_genre_falls_back(library):
    c = rg.generate_character(min_level=2, max_level=2, rng=_rng(),
                              genre='no-such-genre')
    assert c['genre'] == 'fantasy'
    assert c['background'] in rg.BACKGROUNDS


# ── Map prompt data (battle/travel environments per genre) ─────────────────────

def test_map_prompts_shape():
    assert set(gp.MAP_PROMPTS) == set(gp.GENRE_PACKS) | {'fantasy'}
    for key, m in gp.MAP_PROMPTS.items():
        assert m['label'], key
        assert len(m['battle_envs']) >= 6, key
        assert len(m['travel_envs']) >= 4, key
        assert len(m['flavor']) >= 2, key
        for env in m['travel_envs']:
            assert env['name'], (key, env)
            # every travel env's default scale must be a selectable option
            assert env['scale'] in gp.TRAVEL_SCALES, (key, env)


def test_map_prompt_client_data():
    data = gp.map_prompt_client_data()
    assert set(data) == {'genres', 'scales'}
    assert 'fantasy' in data['genres']
    assert data['scales'] == gp.TRAVEL_SCALES


def test_icon_prompt_client_data():
    data = gp.icon_prompt_client_data()
    assert set(data) == set(gp.MAP_PROMPTS)
    for key, entry in data.items():
        assert entry['label'], key
        assert len(entry['topdown']) >= 2, key
        assert len(entry['portrait']) >= 2, key
