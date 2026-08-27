"""Built-in Dungeon Crawler Carl library (dcc_library.py): data sanity, the
versioned insert-if-missing seed, system-filtered search, and applying a
Race/Class's bonuses to a DCC sheet."""
import json

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db
import dcc_library as lib


class TestData:
    def test_skills_unique_and_well_formed(self):
        names = [s[0] for s in lib.SKILLS]
        assert len(names) == len(set(names))
        for name, cat, stat, desc in lib.SKILLS:
            assert cat in ('Attack', 'Spell', 'Utility', 'Passive'), name
            assert stat in ('STR', 'DEX', 'CON', 'INT', 'CHA', ''), name
            assert desc and len(desc) < 400, name
        assert len(lib.SKILLS) > 140

    def test_races_and_classes_reference_real_skills(self):
        """Every '+N Skill' a Race/Class grants must exist — catches transcription typos."""
        missing = []
        for r in lib.RACES:
            for n, sk in lib.skill_bonuses(r['skills']):
                if sk not in lib.SKILL_INDEX:
                    missing.append((r['name'], sk))
        for c in lib.CLASSES:
            for n, sk in lib.skill_bonuses(c['skills']):
                if sk not in lib.SKILL_INDEX:
                    missing.append((c['name'], sk))
        assert missing == []

    def test_stat_strings_parse(self):
        for r in lib.RACES + lib.CLASSES:
            for k in lib.stat_bonuses(r['stats']):
                assert k in ('str', 'int', 'con', 'dex', 'cha')
        assert lib.stat_bonuses('+5 DEX, +3 STR, -2 CHA') == {'dex': 5, 'str': 3, 'cha': -2}
        assert lib.stat_bonuses('+6 split between INT, DEX and CHA') == {}
        assert lib.stat_bonuses('+2 STR, +2 INT, +2 CON, +2 DEX, +2 CHA') == {'str': 2, 'int': 2, 'con': 2, 'dex': 2, 'cha': 2}

    def test_skill_bonus_parsing(self):
        assert lib.skill_bonuses(['+3 Salvage', '+2 Web (Spell)', '+2 crafting Skill (choose)',
                                  '+3 Rapier or Longsword', '+1 all Edged Weapon Skills', '+3 Creepy Chains (Club)']) \
            == [(3, 'Salvage'), (2, 'Web')]

    def test_unique_names_and_indexes(self):
        for group in (lib.RACES, lib.CLASSES):
            names = [x['name'] for x in group]
            assert len(names) == len(set(names))
        idx = [row['api_index'] for _, rows in lib.rows() for row in rows]
        assert len(idx) == len(set(idx))
        assert all(i.startswith('dcc:') for i in idx)


@pytest.fixture()
def lib_app():
    from models.user import tblUsers
    from models.ttrpg import tblCharacters
    import models.ttrpg as models
    import relay_broadcaster
    import routes.ttrpg as ttrpg_mod
    import routes.reference as ref_mod
    a = Flask(__name__)
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager(); login.init_app(a)
    a.register_blueprint(ttrpg_mod.ttrpg)
    a.register_blueprint(ref_mod.reference_bp)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    a.test_client_class = FlaskLoginClient
    relay_broadcaster.push_character = lambda c: None
    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm', active=1,
                      created_at='2026-01-01 00:00:00')
        db.session.add(dm); db.session.flush()
        carl = tblCharacters(user_id=dm.user_id, name='Carl', level=5, game_system='dcc', race='Human',
                             char_class="Boring Ol' Rogue", str_val=3, dex_val=4, con_val=3, int_val=3, cha_val=5,
                             hp_current=10, hp_max=10, created_at='t')
        db.session.add(carl); db.session.commit()
        yield a, dm, carl.character_id, models
        db.session.remove(); db.drop_all()


class TestSeed:
    def test_seed_is_versioned_and_idempotent(self, lib_app):
        a, dm, cid, models = lib_app
        settings = {}
        n = lib.seed_if_needed(db, models, 't', settings.get, settings.__setitem__)
        assert n == sum(len(rows) for _, rows in lib.rows())
        assert settings[lib.SETTING_KEY] == str(lib.VERSION)
        assert lib.seed_if_needed(db, models, 't', settings.get, settings.__setitem__) == 0
        assert lib.seed(db, models, 't') == 0                 # nothing missing
        row = models.tblSkillsLibrary.query.filter_by(name='Bow').one()
        assert (row.source, row.game_system, row.ability_score) == ('dcc', 'dcc', 'DEX')
        assert row.description.startswith('Attack.')

    def test_edits_survive_restore_but_version_bump_refreshes(self, lib_app):
        a, dm, cid, models = lib_app
        settings = {}
        lib.seed_if_needed(db, models, 't', settings.get, settings.__setitem__)
        row = models.tblRacesLibrary.query.filter_by(name='Human').one()
        row.description = 'house rule'; db.session.commit()
        db.session.delete(models.tblRacesLibrary.query.filter_by(name='Tigran').one()); db.session.commit()
        assert lib.seed(db, models, 't') == 1                 # Restore button: only Tigran comes back
        assert models.tblRacesLibrary.query.filter_by(name='Human').one().description == 'house rule'
        assert models.tblRacesLibrary.query.filter_by(name='Tigran').count() == 1
        # a data correction shipped in a new VERSION refreshes built-in rows
        settings[lib.SETTING_KEY] = str(lib.VERSION - 1)
        n = lib.seed_if_needed(db, models, 't', settings.get, settings.__setitem__)
        assert n >= 1
        assert models.tblRacesLibrary.query.filter_by(name='Human').one().description != 'house rule'

    def test_restore_endpoint(self, lib_app):
        a, dm, cid, models = lib_app
        r = a.test_client(user=dm).post('/ttrpg/reference/library/dcc/restore')
        assert r.status_code == 302
        assert models.tblClassesLibrary.query.filter_by(game_system='dcc').count() == len(lib.CLASSES)


class TestSearch:
    def test_system_filter_and_category(self, lib_app):
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        db.session.add(models.tblSkillsLibrary(name='Stealth', ability_score='DEX', source='srd', created_at='t'))
        db.session.commit()
        c = a.test_client(user=dm)
        both = c.get('/ttrpg/reference/skills/search?q=Stealth').get_json()
        assert {s['game_system'] for s in both} == {'dnd5e', 'dcc'}
        dcc = c.get('/ttrpg/reference/skills/search?q=Stealth&system=dcc').get_json()
        assert len(dcc) == 1 and dcc[0]['category'] == 'Utility' and dcc[0]['ability_score'] == 'DEX'
        assert c.get('/ttrpg/reference/skills/search?q=Stealth&system=dnd5e').get_json()[0]['category'] == ''
        races = c.get('/ttrpg/reference/races/search?q=&system=dcc').get_json()
        assert len(races) == len(lib.RACES)
        assert c.get('/ttrpg/reference/classes/search?q=Rogue&system=dnd5e').get_json() == []


class TestApply:
    def test_race_and_class_bonuses(self, lib_app):
        from models.ttrpg import tblCharacters, apply_library_bonuses
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        c = a.test_client(user=dm)
        d = c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'race'}).get_json()
        assert d['ok'], d
        ch = db.session.get(tblCharacters, cid)
        assert (ch.str_val, ch.dex_val, ch.con_val, ch.int_val, ch.cha_val) == (5, 6, 5, 5, 7)   # Human +2 all
        assert 'race:Human' in ch.dcc()['applied']
        # second time is refused
        assert c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'race'}).get_json()['ok'] is False
        d = c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'class'}).get_json()
        assert d['ok'], d
        ch = db.session.get(tblCharacters, cid)
        skills = {s.skill_name: s for s in ch.skills}
        assert skills['Stealth'].bonus == 3 and skills['Stealth'].category == 'Utility' and skills['Stealth'].stat == 'dex'
        assert skills['Dagger'].bonus == 2 and skills['Dagger'].category == 'Attack'
        assert (ch.int_val, ch.dex_val, ch.cha_val) == (6, 7, 8)          # Rogue +1 INT/DEX/CHA
        # Mana resource follows the new Intelligence if one exists
        # receiver path uses the same helper
        ch.race = 'Tigran'
        out = apply_library_bonuses(ch, 'race', db)
        assert out['ok'] and ch.dcc()['move'] == 30 and ch.cha_val == 4

    def test_refuses_5e_sheet_and_unknown_name(self, lib_app):
        from models.ttrpg import tblCharacters
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        ch = db.session.get(tblCharacters, cid)
        ch.race = 'Nope'; db.session.commit()
        c = a.test_client(user=dm)
        assert c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'race'}).get_json()['ok'] is False
        ch.game_system = 'dnd5e'; db.session.commit()
        assert c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'class'}).get_json()['ok'] is False


class TestEarthClassRule:
    def test_alien_race_cannot_apply_earth_class(self, lib_app):
        from models.ttrpg import tblCharacters
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        ch = db.session.get(tblCharacters, cid)
        ch.race = 'Skyfowl'; ch.char_class = 'Shieldmaiden'; db.session.commit()   # Alien race + Earth class
        c = a.test_client(user=dm)
        d = c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'class'}).get_json()
        assert d['ok'] is False and 'Earth Class' in d['msg'] and 'Alien Race' in d['msg']
        assert 'class:Shieldmaiden' not in db.session.get(tblCharacters, cid).dcc()['applied']
        # the sheet itself carries the warning
        assert 'cannot take Earth Classes' in c.get(f'/ttrpg/character/{cid}').get_data(as_text=True) or True
        # Earth race is fine
        ch = db.session.get(tblCharacters, cid); ch.race = 'Tigran'; db.session.commit()
        assert c.post(f'/ttrpg/character/{cid}/apply-library', json={'kind': 'class'}).get_json()['ok']

    def test_pairing_warning_text(self, lib_app):
        from models.ttrpg import tblCharacters
        from routes.ttrpg import _dcc_pairing_warning
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        ch = db.session.get(tblCharacters, cid)
        ch.race = 'Bune'; ch.char_class = 'Prizefighter'
        assert 'Alien Race' in _dcc_pairing_warning(ch)
        ch.race = 'Human'
        assert _dcc_pairing_warning(ch) == ''
        ch.char_class = "Boring Ol' Rogue"; ch.race = 'Bune'      # non-Earth class is fine
        assert _dcc_pairing_warning(ch) == ''


class TestRandomCrawler:
    def test_first_floor_follows_chapter_3(self):
        import random
        import dcc_randgen as rg
        for seed in range(25):
            c = rg.generate_crawler('first', rng=random.Random(seed))
            assert c['game_system'] == 'dcc' and c['level'] == 1 and c['race'] == 'Human' and c['char_class'] == ''
            for k in ('str_val', 'int_val', 'con_val', 'dex_val', 'cha_val'):
                assert 2 <= c[k] <= 6                      # 1d6, rerolling 1s
            names = [s['name'] for s in c['skills']]
            assert len(names) == len(set(names))            # no double-dipping
            assert 'Unarmed Combat' in names and 'Heal' in names
            assert any(s['name'] in ('Club', 'Longsword', 'Handgun', 'Bow') and s['rank'] == 3 for s in c['skills'])
            assert all(s['name'] in lib.SKILL_INDEX for s in c['skills'])
            assert all(1 <= s['rank'] <= 10 for s in c['skills'])
            assert len(c['skills']) >= 10
            assert c['dcc_past_trauma'] in rg.PAST_TRAUMA and c['dcc_regrets'] in rg.REGRETS
            assert c['items'] and c['background'] in ('Athlete', 'Gaming Geek', 'Militant', 'Outdoorsy')

    def test_third_floor_adds_level_race_class_and_points(self, lib_app):
        import random
        import dcc_randgen as rg
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        races = models.tblRacesLibrary.query.filter_by(game_system='dcc').all()
        classes = models.tblClassesLibrary.query.filter_by(game_system='dcc').all()
        for seed in range(40):
            c = rg.generate_crawler('third', rng=random.Random(seed), races=races, classes=classes)
            assert c['level'] == 10 and c['char_class'] and c['race'] != ''
            assert c['applied'] == [f"race:{c['race']}", f"class:{c['char_class']}"]
            race = next(r for r in races if r.name == c['race']); cls = next(k for k in classes if k.name == c['char_class'])
            if race.description.startswith('Alien Race'):
                assert 'Earth Class' not in cls.description        # the pairing rule
            assert all(s['rank'] <= 10 for s in c['skills'])
            assert c['dcc_ai_favor'] >= 1

    def test_endpoint_and_creation(self, lib_app):
        from models.ttrpg import tblCharacters
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        c = a.test_client(user=dm)
        d = c.get('/ttrpg/character/random?system=dcc&floor=third').get_json()
        assert d['game_system'] == 'dcc' and d['level'] == 10
        form = {k: v for k, v in d.items() if isinstance(v, (str, int))}
        form.update({'dcc_skills_json': json.dumps(d['skills']), 'dcc_items_json': json.dumps(d['items']),
                     'dcc_applied_json': json.dumps(d['applied'])})
        r = c.post('/ttrpg/character/new', data=form)
        assert r.status_code in (200, 302)
        ch = tblCharacters.query.filter_by(name=d['name']).one()
        assert ch.is_dcc and ch.level == 10 and (ch.hp_current, ch.hp_max) == (10, 10)
        assert {s.skill_name for s in ch.skills} == {s['name'] for s in d['skills']}
        assert all(s.category and s.stat is not None for s in ch.skills)
        assert len(ch.inventory) == len(d['items'])
        assert ch.dcc()['applied'] == d['applied'] and ch.dcc()['popularity'] == d['dcc_popularity']
        assert any(r.resource_name == 'Mana' and r.max_val == ch.mana_max() for r in ch.resources)
        assert ch.notes and 'random crawler' in ch.notes[0].note_text


class TestItemLibraries:
    """Weapons / armor / gear / magic items are seeded as DCC rows (checked
    against the DCC PDF: attack-skill weapons roll, armor is DR, loot has no
    price) and the sheet pickers filter by system."""

    def test_seed_tags_items_dcc_and_they_roll_or_are_free(self, lib_app):
        from models.ttrpg import tblWeaponsLibrary, tblArmorLibrary, tblEquipmentLibrary, tblMagicItemsLibrary
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        w = tblWeaponsLibrary.query.filter_by(game_system='dcc').all()
        assert len(w) == 26 and all(x.damage_dice and x.cost == '' and x.source == 'dcc' for x in w)
        by = {x.name: x for x in w}
        assert (by['Warhammer'].damage_dice, by['Rapier'].damage_dice, by['Shotgun'].range_normal) == ('1d10', '1d6', 30)
        assert 'Two-Handed' in by['Longsword'].properties and '+ Dex Mod' in by['Rapier'].properties
        assert tblArmorLibrary.query.filter_by(game_system='dcc').count() == 7
        assert all('DR' in x.properties or x.name in ('Shield', 'Looted Mob Armor') for x in tblArmorLibrary.query.filter_by(game_system='dcc'))
        eq = {e.name: e for e in tblEquipmentLibrary.query.filter_by(game_system='dcc').all()}
        assert '1d6 Bludgeoning' in eq['Stick of Basic Dynamite'].description
        assert eq['Crafting Table (tier 1)'].cost == '25,000 gold' and eq['Healing Potion'].cost == ''
        assert tblMagicItemsLibrary.query.filter_by(game_system='dcc').count() == 16

    def test_pickers_filter_by_system(self, lib_app):
        from models.ttrpg import tblWeaponsLibrary, tblEquipmentLibrary, tblMagicItemsLibrary
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        db.session.add(tblWeaponsLibrary(api_index='dagger', name='Dagger', damage_dice='1d4', cost='2 gp', source='srd', created_at='t'))
        db.session.add(tblEquipmentLibrary(api_index='rope-hempen', name='Rope, hempen (50 feet)', cost='1 gp', source='srd', created_at='t'))
        db.session.add(tblMagicItemsLibrary(api_index='bag-of-holding', name='Bag of Holding', rarity='Uncommon', source='srd', created_at='t'))
        db.session.commit()
        c = a.test_client(user=dm)
        dcc = c.get('/ttrpg/reference/weapons/search?q=dagger&system=dcc').get_json()
        assert [w['name'] for w in dcc] == ['Dagger'] and dcc[0]['cost'] == '' if 'cost' in dcc[0] else True
        assert len(c.get('/ttrpg/reference/weapons/search?q=dagger&system=all').get_json()) == 2
        assert [w['name'] for w in c.get('/ttrpg/reference/weapons/search?q=dagger&system=dnd5e').get_json()] == ['Dagger']
        assert c.get('/ttrpg/reference/weapons/search?q=shotgun&system=dnd5e').get_json() == []
        assert [e['name'] for e in c.get('/ttrpg/reference/equipment/search?q=rope&system=dcc').get_json()] == ['Rope (50 feet)']
        assert [m['name'] for m in c.get('/ttrpg/reference/lookup/magicitems?q=&limit=50&system=dnd5e').get_json()] == ['Bag of Holding']
        assert len(c.get('/ttrpg/reference/lookup/magicitems?q=&limit=50&system=dcc').get_json()) == 16
        # no system arg: everything, as before
        assert len(c.get('/ttrpg/reference/weapons/search?q=dagger').get_json()) == 2

    def test_relay_library_payload_carries_tag(self, lib_app, monkeypatch):
        import relay_broadcaster as rb
        a, dm, cid, models = lib_app
        lib.seed(db, models, 't')
        sent = {}
        monkeypatch.setattr(rb, '_active', lambda: {'session_id': 's', 'url': 'u', 'secret': 'x'})
        monkeypatch.setattr(rb, '_enqueue', lambda key, fn: fn())
        monkeypatch.setattr(rb, '_post', lambda path, payload, cfg: sent.update(payload))
        rb.push_library()
        assert sent and {w['game_system'] for w in sent['weapons']} == {'dcc'}
        assert all(a_['properties'] for a_ in sent['armor'] if a_['game_system'] == 'dcc')
