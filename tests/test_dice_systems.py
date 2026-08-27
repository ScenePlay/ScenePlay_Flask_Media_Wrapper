"""dice_systems.py — the game-system rules behind the dice rollers (pure).

The Dungeon Crawler Carl numbers are checked against the Core Rulebook:
Stat Mod table (p.57), Difficulty formulas (p.59-60), degrees of success
(p.60-61), Rank-Up checks (p.169), Rank damage dice (Table 37)."""
import dice_systems as ds


class TestStatMod:
    def test_dcc_table(self):
        expect = {1: 1, 2: 1, 3: 2, 5: 2, 6: 3, 9: 3, 10: 4, 19: 4, 20: 5, 49: 5,
                  50: 6, 99: 6, 100: 7, 149: 7, 150: 8, 200: 9, 299: 9, 300: 10, 999: 10}
        for score, mod in expect.items():
            assert ds.stat_mod('dcc', score) == mod, score

    def test_5e_unchanged(self):
        assert ds.stat_mod('dnd5e', 10) == 0
        assert ds.stat_mod('dnd5e', 15) == 2
        assert ds.stat_mod('dnd5e', 8) == -1

    def test_garbage_score(self):
        assert ds.stat_mod('dcc', 'x') == 2      # DCC starting-ish score 3
        assert ds.stat_mod('dnd5e', None) == 0


class TestDifficulty:
    def test_formulas(self):
        assert ds.dcc_difficulty('unopposed', 3) == 16          # 10 + 2F
        assert ds.dcc_difficulty('opposed', 3, opp_mod=4) == 17  # 10 + mod + F
        assert ds.dcc_difficulty('stat', 3) == 13               # 10 + F
        assert ds.dcc_difficulty('mob', 4, base=14) == 18       # "14+F"
        assert ds.dcc_difficulty('number', 9, base=21) == 21

    def test_mob_edge(self):
        assert ds.dcc_difficulty('mob', 4, base=14, mob_mode='advantage') == 23
        assert ds.dcc_difficulty('mob', 4, base=14, mob_mode='disadvantage') == 13


class TestRankDamage:
    def test_table_37(self):
        assert ds.rank_damage_die(0) == (0, 0, 0)
        assert ds.rank_damage_die(1) == (0, 0, 1)
        assert ds.rank_damage_die(3) == (1, 2, 0)
        assert ds.rank_damage_die(5) == (1, 4, 0)
        assert ds.rank_damage_die(13) == (1, 12, 0)
        assert ds.rank_damage_die(20) == (2, 10, 0)


class TestEvaluateDcc:
    def _ev(self, natural, total, difficulty, roll_type='check', **kw):
        return ds.evaluate('dcc', 20, natural, total, roll_type, difficulty, floor=3, **kw)

    def test_degrees_by_margin(self):
        assert self._ev(20, 25, 16)['degree'] == 'crit'
        assert self._ev(1, 6, 16)['degree'] == 'crit_fail'
        assert self._ev(15, 26, 16)['degree'] == 'amazing'     # +10
        assert self._ev(15, 16, 16)['degree'] == 'success'     # tie succeeds
        assert self._ev(15, 25, 16)['degree'] == 'success'     # +9
        assert self._ev(10, 15, 16)['degree'] == 'near_miss'   # -1
        assert self._ev(10, 14, 16)['degree'] == 'near_miss'   # -2
        assert self._ev(10, 13, 16)['degree'] == 'fail'        # -3
        assert self._ev(5, 7, 16)['degree'] == 'fail'          # -9
        assert self._ev(5, 6, 16)['degree'] == 'major_fail'    # -10

    def test_ok_flag(self):
        assert self._ev(15, 16, 16)['ok'] is True
        assert self._ev(10, 15, 16)['ok'] is False
        assert self._ev(20, 3, 30)['ok'] is True     # natural 20 always
        assert self._ev(1, 40, 5)['ok'] is False     # natural 1 always

    def test_attack_text_mentions_floor_bonus(self):
        out = self._ev(15, 27, 17, roll_type='attack')
        assert out['degree'] == 'amazing'
        assert '+3 bonus damage' in out['text']

    def test_evade_texts(self):
        assert self._ev(12, 18, 18, roll_type='evade')['text'] == 'Evaded'
        assert 'DOUBLE damage' in self._ev(1, 5, 18, roll_type='evade')['text']

    def test_rankup(self):
        out = ds.evaluate('dcc', 20, 9, 9, 'rankup', None, 3, rank=8)
        assert out['ok'] is True and 'Rank 9' in out['text']
        out = ds.evaluate('dcc', 20, 7, 7, 'rankup', None, 3, rank=8)
        assert out['ok'] is False and 'needed 8+' in out['text']
        assert ds.evaluate('dcc', 20, 7, 7, 'rankup', None, 3, rank=None)['text'] == ''

    def test_no_target_only_naturals(self):
        assert self._ev(12, 15, None)['text'] == ''
        assert self._ev(20, 23, None)['degree'] == 'crit'
        assert self._ev(1, 4, None)['degree'] == 'crit_fail'

    def test_non_d20_is_silent(self):
        assert ds.evaluate('dcc', 6, None, 9, 'damage')['text'] == ''
        assert ds.evaluate('dcc', 20, None, 30, 'attack', 16, 3)['text'] == ''   # 2d20 sum

    def test_bad_difficulty_ignored(self):
        assert self._ev(12, 15, 'abc')['text'] == ''


class TestEvaluate5e:
    def test_dc_compare(self):
        assert ds.evaluate('dnd5e', 20, 12, 17, 'check', 15)['text'] == 'Success'
        assert ds.evaluate('dnd5e', 20, 12, 14, 'check', 15)['text'] == 'Fail'
        assert ds.evaluate('dnd5e', 20, 20, 21, 'check', 25)['text'] == 'Natural 20! — Success'
        assert ds.evaluate('dnd5e', 20, 1, 30, 'check', 5)['text'] == 'Natural 1! — Fail'

    def test_no_dc_only_naturals(self):
        assert ds.evaluate('dnd5e', 20, 12, 17, 'check')['text'] == ''
        assert ds.evaluate('dnd5e', 20, 20, 25, 'attack')['text'] == 'Natural 20!'

    def test_unknown_system_behaves_like_5e(self):
        assert ds.evaluate('nope', 20, 12, 17, 'check', 15)['text'] == 'Success'


class TestAnnotateLabel:
    def test_shapes(self):
        out = {'text': 'Hit'}
        assert ds.annotate_label('Attack', out, 17) == 'Attack vs 17 → Hit'
        assert ds.annotate_label('', out, 17) == 'vs 17 → Hit'
        assert ds.annotate_label('', out, None) == 'Hit'
        assert ds.annotate_label('Attack', {'text': ''}, 17) == 'Attack'
        assert ds.annotate_label('Attack', None) == 'Attack'


class TestSettings:
    def test_floor_clamped(self):
        assert ds.normalize_settings('dcc', {'floor': 0}) == {'floor': 1}
        assert ds.normalize_settings('dcc', {'floor': '99'}) == {'floor': 18}
        assert ds.normalize_settings('dcc', {'floor': 'x'}) == {'floor': 3}
        assert ds.normalize_settings('dcc', None) == {'floor': 3}
        assert ds.normalize_settings('dnd5e', {'floor': 4}) == {}

    def test_system_fallback(self):
        assert ds.system('nope')['id'] == 'dnd5e'
        assert ds.system('dcc')['name'] == 'Dungeon Crawler Carl'
