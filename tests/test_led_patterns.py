"""RPiLED: registry, driver and payload contract.

- led_patterns.PATTERNS is the one description of every routine and the
  params it honors; led_Run.FUNCS must match it exactly.
- Every routine runs hardware-free on a fake strip and stops at its deadline.
- Brightness is two layers: the box's hardware cap × the pattern's creative
  level; nothing a routine does can exceed the cap.
- Legacy payload keys (cdiff / wait_ms / iterations) and legacy scene rows
  still map onto the vocabulary, and the 0010 migration converts old rows.
"""
import json
import os
import sqlite3

import pytest

import led_patterns as reg
import led_Run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------
class FakePixels:
    def __init__(self, n):
        self.buf = [(0, 0, 0)] * n
        self.brightness = 1.0
        self.shows = 0
        self.max_brightness_seen = 0.0

    def __setitem__(self, i, c):
        self.buf[i] = tuple(int(x) for x in c)

    def __getitem__(self, i):
        return self.buf[i]

    def fill(self, c):
        self.buf = [tuple(int(x) for x in c)] * len(self.buf)

    def show(self):
        self.shows += 1
        self.max_brightness_seen = max(self.max_brightness_seen, self.brightness)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


def make_strip(n=30, cap=0.08):
    clock = FakeClock()
    px = FakePixels(n)
    return led_Run.Strip(px, n, cap, clock=clock, sleep=clock.sleep), px, clock


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_driver_and_registry_agree(self):
        assert set(led_Run.FUNCS) == set(reg.PATTERNS)

    def test_every_param_is_defined_and_universal_last(self):
        for t in reg.TYPES:
            keys = reg.param_keys(t)
            assert set(keys) <= set(reg.PARAM_DEFS)
            assert keys[-len(reg.UNIVERSAL_PARAMS):] == list(reg.UNIVERSAL_PARAMS)
            assert len(keys) == len(set(keys))

    def test_defaults_are_in_range(self):
        for t in reg.TYPES:
            d = reg.defaults(t)
            assert reg.coerce(t, d) == d, t

    def test_registry_json_serializable_and_complete(self):
        j = json.loads(json.dumps(reg.registry_json()))
        assert [p['type'] for p in j['patterns']] == list(reg.TYPES)
        for p in j['patterns']:
            assert p['name'] and p['desc']
            for f in p['params']:
                assert {'key', 'label', 'kind', 'default'} <= set(f)

    def test_overrides_apply(self):
        spec = {f['key']: f for f in reg.param_spec('lightning_strike')}
        assert spec['speed']['label'] == 'Quiet between strikes'
        assert spec['speed']['default'] == 2000
        assert spec['color2']['label'] == 'Bolt'
        # generic definition untouched
        assert reg.PARAM_DEFS['speed']['label'] == 'Speed'

    def test_routines_read_only_declared_params(self):
        """Each routine may only index p[...] with keys it declares."""
        import inspect
        import re
        for t, fn in led_Run.FUNCS.items():
            src = inspect.getsource(fn)
            used = set(re.findall(r"(?<![\w\]])p\['(\w+)'\]", src)) | \
                set(re.findall(r"(?<![\w\]])p\.get\('(\w+)'", src))
            assert used <= set(reg.param_keys(t)), (t, used - set(reg.param_keys(t)))


# ---------------------------------------------------------------------------
# coercion / legacy
# ---------------------------------------------------------------------------
class TestCoerce:
    def test_rgb_from_string_and_clamped(self):
        p = reg.coerce('solid', {'color': '[300, -5, 12.7]'})
        assert p['color'] == [255, 0, 12]

    def test_numbers_clamped_and_typed(self):
        p = reg.coerce('beam', {'speed': '99999', 'brightness': 4, 'duration': -3})
        assert p['speed'] == 10000 and p['brightness'] == 1.0 and p['duration'] == 0

    def test_unknown_keys_dropped_and_missing_defaulted(self):
        p = reg.coerce('solid', {'color': [1, 2, 3], 'sparks': 9, 'outPinID': 2})
        assert set(p) == set(reg.param_keys('solid'))
        assert p['brightness'] == 1.0 and p['duration'] == 0

    def test_bad_choice_falls_back(self):
        assert reg.coerce('beam', {'direction': 5})['direction'] == 1
        assert reg.coerce('beam', {'direction': '-1'})['direction'] == -1


class TestLegacy:
    def test_normalize_legacy_keys(self):
        p = reg.normalize({'type': 'beam', 'color': '[1,2,3]', 'cdiff': [9, 9, 9],
                           'wait_ms': 5, 'iterations': 9999999, 'direction': -1,
                           'outPinID': 2})
        assert p['type'] == 'beam' and p['color'] == [1, 2, 3]
        assert p['speed'] == 5 and p['duration'] == 0 and p['direction'] == -1
        assert 'outPinID' not in p and 'cdiff' not in p

    def test_cdiff_is_color2_or_variance(self):
        assert reg.normalize({'type': 'ember_rise', 'cdiff': [7, 8, 9]})['color2'] == [7, 8, 9]
        assert reg.normalize({'type': 'sparkle', 'cdiff': [7, 8, 9]})['variance'] == [7, 8, 9]

    def test_iterations_to_duration(self):
        assert reg.legacy_duration('beam', 9999999, 30) == 0
        assert reg.legacy_duration('beam', 100, 30) == 3       # 100 frames × 30 ms
        assert reg.legacy_duration('aurora_drift', 15, 500) == 15   # was seconds
        assert reg.legacy_duration('beam', 'junk', 30) == 0

    def test_unknown_type_is_none(self):
        assert reg.normalize({'type': 'disco'}) is None
        assert reg.normalize('nope') is None

    def test_hardware_brightness_becomes_creative_full(self):
        p = reg.legacy_to_params('solid', '[1,2,3]', brightness=0.08)
        assert p['brightness'] == 1.0
        p = reg.legacy_to_params('solid', '[1,2,3]', brightness=0.6)
        assert p['brightness'] == 0.6
        assert reg.legacy_to_params('disco', '[1,2,3]') is None


class TestBuildPayload:
    def test_rows_to_wire(self):
        out = json.loads(reg.build_payload([('beam', '{"color": [1,2,3], "speed": 4}'),
                                            ('solid', {'color': [9, 9, 9]})]))
        assert [p['type'] for p in out['patterns']] == ['beam', 'solid']
        assert set(out['patterns'][0]) == {'type'} | set(reg.param_keys('beam'))
        assert out['patterns'][0]['speed'] == 4
        assert out['patterns'][1]['color'] == [9, 9, 9]

    def test_unknown_skipped_and_empty_is_off(self):
        out = json.loads(reg.build_payload([('disco', {})]))
        assert out['patterns'] == json.loads(reg.OFF_PAYLOAD)['patterns']
        assert json.loads(reg.build_payload([]))['patterns'][0]['color'] == [0, 0, 0]

    def test_wire_round_trips_through_normalize(self):
        for t in reg.TYPES:
            wire = json.loads(reg.build_payload([(t, None)]))['patterns'][0]
            assert reg.normalize(wire) == wire


# ---------------------------------------------------------------------------
# brightness cap
# ---------------------------------------------------------------------------
class TestBrightnessCap:
    def test_output_is_cap_times_level(self):
        strip, px, _ = make_strip(cap=0.08)
        strip.begin({'brightness': 1.0, 'duration': 0})
        assert px.brightness == pytest.approx(0.08)
        strip.begin({'brightness': 0.5, 'duration': 0})
        assert px.brightness == pytest.approx(0.04)

    def test_pulse_cannot_exceed_cap(self):
        strip, px, _ = make_strip(cap=0.08)
        strip.begin({'brightness': 1.0, 'duration': 0})
        strip.set_level(5.0)
        assert px.brightness == pytest.approx(0.08)
        strip.set_level(0.5)
        assert px.brightness == pytest.approx(0.04)
        strip.begin({'brightness': 3.0, 'duration': 0})     # over-range level
        assert px.brightness == pytest.approx(0.08)

    def test_sparkle_pulse_stays_under_cap(self):
        strip, px, _ = make_strip(cap=0.2)
        p = reg.normalize({'type': 'sparkle', 'brightness': 1.0, 'duration': 3})
        strip.begin(p)
        led_Run.sparkle(strip, p)
        assert px.max_brightness_seen <= 0.2 + 1e-9


# ---------------------------------------------------------------------------
# routines
# ---------------------------------------------------------------------------
class TestRoutines:
    @pytest.mark.parametrize('ptype', list(reg.TYPES))
    def test_runs_and_stops_at_deadline(self, ptype):
        strip, px, clock = make_strip(n=30)
        p = reg.normalize({'type': ptype, 'duration': 2})
        strip.begin(p)
        led_Run.FUNCS[ptype](strip, p)
        assert px.shows > 0
        assert clock.t >= 2.0

    @pytest.mark.parametrize('ptype', [t for t in reg.TYPES if 'direction' in reg.param_keys(t)])
    def test_reverse_direction_runs(self, ptype):
        strip, px, _ = make_strip(n=12)
        p = reg.normalize({'type': ptype, 'duration': 1, 'direction': -1})
        strip.begin(p)
        led_Run.FUNCS[ptype](strip, p)
        assert px.shows > 0

    def test_solid_holds_color(self):
        strip, px, clock = make_strip(n=5)
        p = reg.normalize({'type': 'solid', 'color': [10, 20, 30], 'duration': 1})
        strip.begin(p)
        led_Run.solid(strip, p)
        assert px.buf == [(10, 20, 30)] * 5 and clock.t >= 1.0

    def test_run_sequences_then_goes_dark(self):
        strip, px, clock = make_strip(n=5)
        payload = json.dumps({'patterns': [
            {'type': 'solid', 'color': [1, 1, 1], 'duration': 1},
            {'type': 'disco'},
            {'type': 'color_wipe', 'color': [2, 2, 2], 'wait_ms': 10, 'iterations': 9},
        ]})
        led_Run.run(strip, payload)
        assert px.buf == [(0, 0, 0)] * 5          # off after the last finite pattern
        assert clock.t >= 1.0

    def test_run_tolerates_garbage(self):
        strip, px, _ = make_strip(n=3)
        led_Run.run(strip, 'not json')
        led_Run.run(strip, {'patterns': 'nope'})
        led_Run.run(strip, {'patterns': [None, 3, {'type': None}]})
        assert px.buf == [(0, 0, 0)] * 3


# ---------------------------------------------------------------------------
# mailbox / config
# ---------------------------------------------------------------------------
class TestMailbox:
    def _db(self, tmp_path):
        path = str(tmp_path / 'led.db')
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE tblLED (led_ID INTEGER PRIMARY KEY AUTOINCREMENT, ledJSON TEXT, active INT)")
        c.execute("CREATE TABLE tblLEDConfig (ledConfig_ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "pin INT, ledCount INT, brightness REAL, active INT)")
        c.commit()
        c.close()
        return path

    def test_latest_row_wins_and_is_cleared(self, tmp_path):
        path = self._db(tmp_path)
        c = sqlite3.connect(path)
        c.execute("INSERT INTO tblLED(ledJSON) VALUES ('{\"patterns\": [{\"type\": \"beam\"}]}')")
        c.execute("INSERT INTO tblLED(ledJSON) VALUES ('{\"patterns\": [{\"type\": \"solid\"}]}')")
        c.commit()
        c.close()
        assert json.loads(led_Run.take_payload(path))['patterns'][0]['type'] == 'solid'
        assert led_Run.take_payload(path) == reg.OFF_PAYLOAD      # empty → off

    def test_active_config(self, tmp_path):
        path = self._db(tmp_path)
        assert led_Run.active_config(path) is None
        c = sqlite3.connect(path)
        c.execute("INSERT INTO tblLEDConfig(pin, ledCount, brightness, active) VALUES (18, 100, 0.5, 0)")
        c.execute("INSERT INTO tblLEDConfig(pin, ledCount, brightness, active) VALUES (21, 60, 0.08, 1)")
        c.commit()
        c.close()
        assert led_Run.active_config(path) == (21, 60, 0.08)


# ---------------------------------------------------------------------------
# migration 0010
# ---------------------------------------------------------------------------
def _upgrade(db_path):
    from flask import Flask
    from flask_migrate import Migrate, upgrade
    from extensions import db
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    Migrate(app, db, directory=os.path.join(ROOT, 'migrations'))
    with app.app_context():
        upgrade()


def _q(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


class TestMigration0010:
    def _old_db(self, tmp_path):
        path = str(tmp_path / 'old.db')
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE tblScenePattern (scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "scene_ID INT, ledTypeModel_ID INT, color TEXT, wait_ms INT, iterations INT, "
                  "direction INT, cdiff TEXT, orderBy INT, outPin INT, brightness REAL)")
        c.execute("CREATE TABLE tblLEDTypeModel (ledTypeModel_ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "modelName TEXT, ledJSON TEXT)")
        c.execute("INSERT INTO tblLEDTypeModel VALUES (7, 'Sparkle', '{\"type\": \"sparkle\", \"color\": [0,0,0]}')")
        c.execute("INSERT INTO tblLEDTypeModel VALUES (9, 'ember', '{\"type\": \"ember_rise\"}')")
        c.execute("INSERT INTO tblLEDTypeModel VALUES (11, 'broken', 'not json')")
        c.execute("INSERT INTO tblScenePattern VALUES (1, 2, 9, '[224,27,36]', 10, 99999999, 1, "
                  "'[129,61,156]', 1, 2, 0.08)")
        c.execute("INSERT INTO tblScenePattern VALUES (2, 1, 7, '[28,113,216]', 100, 50, -1, "
                  "'[5,6,7]', 3, 2, 0.6)")
        c.execute("INSERT INTO tblScenePattern VALUES (3, 1, 11, '[1,1,1]', 5, 5, 1, NULL, 4, 2, NULL)")
        c.execute("INSERT INTO tblScenePattern VALUES (4, 1, 99, '[1,1,1]', 5, 5, 1, NULL, 5, 2, NULL)")
        c.commit()
        c.close()
        return path

    def test_rows_converted_and_model_table_dropped(self, tmp_path):
        path = self._old_db(tmp_path)
        _upgrade(path)
        cols = [r[1] for r in _q(path, 'PRAGMA table_info(tblScenePattern)')]
        assert cols == ['scenePattern_ID', 'scene_ID', 'patternType', 'params', 'orderBy']
        rows = {r[0]: r for r in _q(path, 'SELECT scenePattern_ID, scene_ID, patternType, params, orderBy '
                                          'FROM tblScenePattern')}
        assert set(rows) == {1, 2}             # unknown / unparsable models dropped
        p1 = json.loads(rows[1][3])
        assert rows[1][1:3] == (2, 'ember_rise') and rows[1][4] == 1
        assert p1['color'] == [224, 27, 36] and p1['color2'] == [129, 61, 156]
        assert p1['speed'] == 10 and p1['duration'] == 0 and p1['brightness'] == 1.0
        p2 = json.loads(rows[2][3])
        assert rows[2][2] == 'sparkle'
        assert p2['variance'] == [5, 6, 7] and p2['duration'] == 5   # 50 × 100 ms
        assert p2['brightness'] == 0.6 and 'direction' not in p2
        names = {r[0].lower() for r in _q(path, "SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'tblledtypemodel' not in names
        _upgrade(path)                          # second run: no-op
        assert len(_q(path, 'SELECT * FROM tblScenePattern')) == 2

    def test_fresh_shape_passes_through(self, tmp_path):
        path = str(tmp_path / 'new.db')
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE tblScenePattern (scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "scene_ID INT, patternType TEXT, params TEXT, orderBy INT)")
        c.execute("INSERT INTO tblScenePattern VALUES (1, 1, 'beam', '{}', 1)")
        c.commit()
        c.close()
        _upgrade(path)
        assert _q(path, 'SELECT patternType FROM tblScenePattern') == [('beam',)]

    def test_missing_table_is_created(self, tmp_path):
        path = str(tmp_path / 'bare.db')
        sqlite3.connect(path).close()
        _upgrade(path)
        cols = [r[1] for r in _q(path, 'PRAGMA table_info(tblScenePattern)')]
        assert 'patternType' in cols
