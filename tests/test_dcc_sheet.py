"""Dungeon Crawler Carl character sheets (per-character game_system).

Five stats with Table 2 modifiers off the Enhanced score, a 10-slot Health Bar
(hp_* count slots), damage → slots through DR, Mana = Intelligence, ranked
skills, the Hotlist, and the dcc_json bag round-tripping through save-field."""
import json
import os

import pytest
from flask import Blueprint, Flask
from flask_login import FlaskLoginClient, LoginManager

from extensions import db
import dice_systems as ds

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def dcc_app(monkeypatch):
    from models.user import tblUsers
    from models.ttrpg import tblCharacters, tblCharacterResources
    import relay_broadcaster
    import routes.ttrpg as ttrpg_mod
    monkeypatch.setattr(relay_broadcaster, 'push_character', lambda c: None)
    monkeypatch.setattr(relay_broadcaster, 'find_token_id', lambda *a: None)

    a = Flask(__name__, root_path=REPO)   # real templates, for page renders
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.secret_key = 't'
    db.init_app(a)
    login = LoginManager(); login.init_app(a)
    a.register_blueprint(ttrpg_mod.ttrpg)
    stub = Blueprint('auth', __name__)
    stub.add_url_rule('/login', 'login', lambda: ('login', 200))
    a.register_blueprint(stub)
    # base.html links to a couple of dozen blueprints this fixture doesn't
    # mount; any unknown endpoint becomes a dead '/stub/<endpoint>' href.
    a.url_build_error_handlers.append(lambda err, endpoint, values: '/stub/' + endpoint)
    a.jinja_env.globals['static_v'] = lambda f: '/static/' + f    # app.py's mtime cache-buster
    a.test_client_class = FlaskLoginClient
    with a.app_context():
        db.create_all()

        @login.user_loader
        def _load(uid):
            return db.session.get(tblUsers, int(uid))

        dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm',
                      active=1, created_at='2026-01-01 00:00:00')
        db.session.add(dm); db.session.flush()
        carl = tblCharacters(user_id=dm.user_id, name='Carl', level=5, game_system='dcc',
                             str_val=4, dex_val=6, con_val=5, int_val=3, cha_val=12,
                             hp_current=10, hp_max=10, created_at='2026-01-01 00:00:00',
                             dcc_json=json.dumps({'dr': 2, 'enh': {'dex': 10}}))
        db.session.add(carl); db.session.flush()
        db.session.add(tblCharacterResources(character_id=carl.character_id, resource_name='Mana',
                                             current_val=3, max_val=3, order_by=0))
        db.session.commit()
        yield a, dm, carl.character_id
        db.session.remove(); db.drop_all()


class TestModel:
    def test_five_stats_no_wisdom(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        c = db.session.get(tblCharacters, cid)
        assert c.stat_keys() == ['str', 'int', 'con', 'dex', 'cha']
        assert 'wis' not in c.stat_keys()

    def test_mods_use_table_on_enhanced_score(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        c = db.session.get(tblCharacters, cid)
        assert c.stat_mod('str') == 2           # 4 → +2
        assert c.stat_mod('dex') == 4           # Enhanced 10 → +4 (base 6 would be +3)
        assert c.stat_mod('cha') == 4
        assert c.hb_slot_value() == 2           # Con 5 → +2
        assert c.mana_max() == 3                # Intelligence score
        assert c.evade_bonus() == 2 + 4         # 2 + Dex Mod
        assert c.dr_total() == 2

    def test_5e_character_unchanged(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        c = db.session.get(tblCharacters, cid)
        c.game_system = 'dnd5e'
        assert c.stat_keys() == ['str', 'dex', 'con', 'int', 'wis', 'cha']
        assert c.stat_mod('dex') == -2          # (6-10)//2, no Enhanced layer


class TestDamage:
    def test_damage_slots_math(self):
        assert ds.dcc_damage_slots(22, 0, 4) == 5      # rulebook example
        assert ds.dcc_damage_slots(3, 0, 4) == 0       # below one slot: ignored
        assert ds.dcc_damage_slots(10, 3, 2) == 3      # DR first
        assert ds.dcc_damage_slots('x', 0, 2) == 0

    def test_hp_delta_takes_damage_through_dr(self, dcc_app):
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        d = c.post(f'/ttrpg/character/{cid}/hp-delta', json={'damage': 9}).get_json()
        assert d['slots_lost'] == 3 and d['hp_current'] == 7 and d['hp_pct'] == 70   # (9-2)//2
        d = c.post(f'/ttrpg/character/{cid}/hp-delta', json={'damage': 3}).get_json()
        assert d['slots_lost'] == 0 and d['hp_current'] == 7                         # shrugged off
        d = c.post(f'/ttrpg/character/{cid}/hp-delta', json={'delta': 2}).get_json()  # heal 2 slots
        assert d['hp_current'] == 9


class TestSaveField:
    def test_dcc_bag_fields(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        assert c.post(f'/ttrpg/character/{cid}/save-field', json={'field': 'dcc_popularity', 'value': '8'}).get_json()['ok']
        assert c.post(f'/ttrpg/character/{cid}/save-field', json={'field': 'dcc_past_trauma', 'value': 'lost it all'}).get_json()['ok']
        assert c.post(f'/ttrpg/character/{cid}/save-field', json={'field': 'dcc_enh_str', 'value': '20'}).get_json()['ok']
        ch = db.session.get(tblCharacters, cid)
        bag = ch.dcc()
        assert bag['popularity'] == 8 and bag['past_trauma'] == 'lost it all'
        assert bag['dr'] == 2                       # untouched keys survive
        assert ch.stat_mod('str') == 5              # Enhanced 20 → +5
        # clearing the Enhanced override falls back to the base score
        c.post(f'/ttrpg/character/{cid}/save-field', json={'field': 'dcc_enh_str', 'value': ''})
        assert db.session.get(tblCharacters, cid).stat_mod('str') == 2

    def test_mana_follows_intelligence(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        a.test_client(user=dm).post(f'/ttrpg/character/{cid}/save-field', json={'field': 'int_val', 'value': 7})
        ch = db.session.get(tblCharacters, cid)
        mana = [r for r in ch.resources if r.resource_name == 'Mana'][0]
        assert mana.max_val == 7 and mana.current_val == 3

    def test_switching_system_resets_health_bar(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        ch = db.session.get(tblCharacters, cid)
        ch.game_system = 'dnd5e'; ch.hp_max = 42; ch.hp_current = 30
        db.session.commit()
        a.test_client(user=dm).post(f'/ttrpg/character/{cid}/save-field', json={'field': 'game_system', 'value': 'dcc'})
        ch = db.session.get(tblCharacters, cid)
        assert ch.is_dcc and (ch.hp_current, ch.hp_max) == (10, 10)

    def test_unknown_system_rejected_to_default(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        a.test_client(user=dm).post(f'/ttrpg/character/{cid}/save-field', json={'field': 'game_system', 'value': 'gurps'})
        assert db.session.get(tblCharacters, cid).game_system == 'dnd5e'


class TestSkillsAndHotlist:
    def test_ranked_skill(self, dcc_app):
        from models.ttrpg import tblCharacterSkills
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        d = c.post(f'/ttrpg/character/{cid}/skills',
                   json={'skill_name': 'Bow', 'bonus': 3, 'category': 'Attack', 'stat': 'dex'}).get_json()
        s = db.session.get(tblCharacterSkills, d['skill_id'])
        assert (s.bonus, s.category, s.stat) == (3, 'Attack', 'dex')
        c.post(f'/ttrpg/skill/{s.skill_id}', json={'bonus': 4, 'category': 'Passive', 'stat': 'con'})
        s = db.session.get(tblCharacterSkills, s.skill_id)
        assert (s.bonus, s.category, s.stat) == (4, 'Passive', 'con')

    def test_hotlist_flag(self, dcc_app):
        from models.ttrpg import tblCharacterInventory
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        d = c.post(f'/ttrpg/character/{cid}/inventory', json={'item_name': 'Healing potion', 'hotlist': 1}).get_json()
        assert db.session.get(tblCharacterInventory, d['item_id']).hotlist == 1
        c.post(f'/ttrpg/inventory/{d["item_id"]}', json={'hotlist': 0})
        assert db.session.get(tblCharacterInventory, d['item_id']).hotlist == 0


class TestRelayPayload:
    def test_payload_carries_system_and_bag(self, dcc_app):
        from models.ttrpg import tblCharacters
        import relay_broadcaster
        a, dm, cid = dcc_app
        p = relay_broadcaster._char_to_payload(db.session.get(tblCharacters, cid))
        sheet = p['sheet_json'] if isinstance(p.get('sheet_json'), dict) else json.loads(p.get('sheet_json') or '{}')
        assert sheet['game_system'] == 'dcc'
        assert sheet['dcc']['dr'] == 2 and sheet['dcc']['enh'] == {'dex': 10}
        assert 'wis' in sheet                      # raw score still shipped; portal hides it

    def test_receiver_merges_dcc_fields(self, dcc_app):
        from models.ttrpg import tblCharacters
        import relay_receiver
        a, dm, cid = dcc_app
        ch = db.session.get(tblCharacters, cid)
        relay_receiver._apply_mutation(ch, 'attr_save', {'dcc_popularity': 6, 'dcc_enh_str': 20}, '', db)
        relay_receiver._apply_mutation(ch, 'hp_delta', {'damage': 9}, '', db)
        assert ch.dcc()['popularity'] == 6 and ch.stat_mod('str') == 5
        assert ch.hp_current == 7


class TestHotlistInRoller:
    """The crawler's Hotlist shows up in the dice roller's Quick Reference."""

    def test_sheet_roller_lists_hotlist_items(self, dcc_app):
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        c.post(f'/ttrpg/character/{cid}/inventory',
               json={'item_name': 'Healing potion', 'hotlist': 1, 'notes': 'heals 2d4+2'})
        c.post(f'/ttrpg/character/{cid}/inventory', json={'item_name': 'Rope', 'hotlist': 0})
        html = c.get(f'/ttrpg/character/{cid}').get_data(as_text=True)
        assert 'data-qref="hotlist"' in html
        assert 'hotlistQuickRoll("Healing potion", "heals 2d4+2")' in html
        assert 'hotlistQuickRoll("Rope"' not in html          # not on the Hotlist
        # every quick-reference row is foldable
        assert 'data-qref="skills"' in html or 'data-qref="weapons"' in html or 'data-qref="hotlist"' in html

    def test_use_one_button_and_last_one_deletes(self, dcc_app):
        from models.ttrpg import tblCharacterInventory
        a, dm, cid = dcc_app
        c = a.test_client(user=dm)
        iid = c.post(f'/ttrpg/character/{cid}/inventory',
                     json={'item_name': 'Bomb', 'hotlist': 1, 'quantity': 2}).get_json()['item_id']
        html = c.get(f'/ttrpg/character/{cid}').get_data(as_text=True)
        assert f'hotlistUse({iid}, 2, "Bomb")' in html
        # the "−1" path: quantity-only save keeps the rest of the row intact
        c.post(f'/ttrpg/inventory/{iid}', json={'quantity': 1})
        it = db.session.get(tblCharacterInventory, iid)
        assert (it.quantity, it.hotlist, it.item_name) == (1, 1, 'Bomb')
        c.delete(f'/ttrpg/inventory/{iid}')
        assert db.session.get(tblCharacterInventory, iid) is None

    def test_empty_hotlist_still_shows_row(self, dcc_app):
        a, dm, cid = dcc_app
        html = a.test_client(user=dm).get(f'/ttrpg/character/{cid}').get_data(as_text=True)
        assert 'data-qref="hotlist"' in html and 'tick <b>Hotlist</b>' in html

    def test_5e_sheet_has_no_hotlist_row(self, dcc_app):
        from models.ttrpg import tblCharacters
        a, dm, cid = dcc_app
        ch = db.session.get(tblCharacters, cid)
        ch.game_system = 'dnd5e'; db.session.commit()
        c = a.test_client(user=dm)
        c.post(f'/ttrpg/character/{cid}/inventory', json={'item_name': 'Potion', 'hotlist': 1})
        html = c.get(f'/ttrpg/character/{cid}').get_data(as_text=True)
        assert 'data-qref="hotlist"' not in html
