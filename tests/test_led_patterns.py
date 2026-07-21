"""RPiLED pattern pipeline.

Three guarantees:
1. The seed file (defaultData/tblLEDTypeModel.json) covers EVERY pattern type
   led_Run.py can dispatch, and every entry carries the FULL uniform field
   set — one shape of data for all patterns.
2. prepJsonRemote emits that same full field set for every pattern (the one
   payload passed to local led_Run, other ScenePlay boxes, and the relay),
   with scene values winning and template values as NULL-fallbacks.
3. The pairing/JSON bugs of the old string-builder stay dead: multi-pattern
   scenes are valid JSON, and misordered/duplicate model ids pair correctly.

led_Run.py is parsed as TEXT (importing it would drive LED hardware).
"""

import json
import os
import re

import pytest

from remotes import prepJsonRemote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL_KEYS = {'type', 'color', 'cdiff', 'wait_ms', 'iterations', 'direction'}


def _seed():
    with open(os.path.join(ROOT, 'defaultData', 'tblLEDTypeModel.json')) as f:
        return json.load(f)


class TestSeedData:
    def test_every_dispatch_type_has_a_default_model(self):
        src = open(os.path.join(ROOT, 'led_Run.py')).read()
        dispatch = set(re.findall(r'pattern_type\)\s*==\s*"(\w+)"', src))
        assert dispatch, 'failed to parse led_Run.py dispatch table'
        seeded = {json.loads(item['ledJSON'])['type'] for item in _seed()}
        missing = dispatch - seeded
        assert not missing, f'led_Run patterns with no default model: {missing}'

    def test_every_model_carries_the_full_field_set(self):
        for item in _seed():
            t = json.loads(item['ledJSON'])
            assert set(t.keys()) == FULL_KEYS, \
                f"{item['modelName']}: {set(t.keys())} != {FULL_KEYS}"

    def test_model_names_unique(self):
        names = [(i['modelName'] or '').strip().lower() for i in _seed()]
        assert len(names) == len(set(names))

    def test_dispatch_required_keys_covered_by_templates(self):
        """Per pattern type: every key led_Run's branch HARD-indexes
        (pattern["x"] — a KeyError if absent) must exist in that type's
        default template, and no branch may read a key outside the uniform
        field set. Guards future led_Run edits against payload drift."""
        src = open(os.path.join(ROOT, 'led_Run.py')).read()
        run_body = src[src.index('def run():'):]
        branches = re.split(r'(?:el)?if str\(pattern_type\) == "(\w+)":',
                            run_body)
        templates = {json.loads(i['ledJSON'])['type']:
                     set(json.loads(i['ledJSON']).keys()) - {'type'}
                     for i in _seed()}
        checked = 0
        for i in range(1, len(branches) - 1, 2):
            ptype = branches[i]
            body = branches[i + 1].split('elif')[0].split('else:')[0]
            hard = set(re.findall(r'pattern\["(\w+)"\]', body))
            soft = set(re.findall(r'pattern\.get\("(\w+)"', body))
            assert ptype in templates, f'no template for {ptype}'
            assert hard <= templates[ptype], \
                f'{ptype}: hard-required {hard - templates[ptype]} missing from template'
            assert (hard | soft) <= FULL_KEYS - {'type'}, \
                f'{ptype}: reads keys outside the uniform set: {(hard | soft) - FULL_KEYS}'
            checked += 1
        assert checked >= 20   # sanity: the parse actually found the branches


def _model(mid, mtype, **kw):
    t = {'type': mtype, 'color': [0, 0, 0], 'cdiff': [0, 0, 0],
         'wait_ms': 30, 'iterations': 9999999, 'direction': 1}
    t.update(kw)
    return (mid, mtype, json.dumps(t))


def _scene_row(model_id, color='[255, 0, 0]', wait_ms=25, iterations=100,
               direction=0, cdiff='[1, 2, 3]', out_pin=18, brightness=0.5):
    # (scenePattern_ID, scene_ID, ledTypeModel_ID, color, wait_ms, iterations,
    #  direction, cdiff, orderBy, outPin, brightness)
    return (1, 1, model_id, color, wait_ms, iterations, direction, cdiff,
            0, out_pin, brightness)


class TestPrepJsonRemote:
    def test_full_field_set_always(self):
        out = json.loads(prepJsonRemote([_model(3, 'rainbow_wave')],
                                        [_scene_row(3)]))
        p = out['patterns'][0]
        assert set(p.keys()) == FULL_KEYS
        assert p['type'] == 'rainbow_wave'
        assert p['color'] == [255, 0, 0] and p['cdiff'] == [1, 2, 3]
        assert (p['wait_ms'], p['iterations'], p['direction']) == (25, 100, 0)

    def test_null_scene_values_fall_back_to_template(self):
        mdl = _model(5, 'lightning_strike', color=[0, 0, 20],
                     cdiff=[220, 230, 255], wait_ms=2000)
        row = _scene_row(5, color=None, wait_ms=None, iterations=None,
                         direction=None, cdiff=None)
        p = json.loads(prepJsonRemote([mdl], [row]))['patterns'][0]
        assert p['color'] == [0, 0, 20] and p['cdiff'] == [220, 230, 255]
        assert p['wait_ms'] == 2000 and p['iterations'] == 9999999
        assert p['direction'] == 1

    def test_misordered_and_duplicate_models_pair_by_id(self):
        # scene order: model 7, model 3, model 7 again — the IN-query returns
        # models in TABLE order [3, 7] with the duplicate collapsed
        mdls = [_model(3, 'solid'), _model(7, 'beam')]
        rows = [_scene_row(7, color='[9, 9, 9]'),
                _scene_row(3, color='[4, 4, 4]'),
                _scene_row(7, color='[8, 8, 8]')]
        pats = json.loads(prepJsonRemote(mdls, rows))['patterns']
        assert [p['type'] for p in pats[:3]] == ['beam', 'solid', 'beam']
        assert pats[0]['color'] == [9, 9, 9]
        assert pats[1]['color'] == [4, 4, 4]
        assert pats[2]['color'] == [8, 8, 8]

    def test_multi_pattern_output_is_valid_json_with_trailing_solid(self):
        mdls = [_model(1, 'beam'), _model(2, 'sparkle')]
        rows = [_scene_row(1), _scene_row(2)]
        out = json.loads(prepJsonRemote(mdls, rows))   # raises if invalid
        # 2 real patterns + lights-off tail (last real pattern isn't solid)
        assert len(out['patterns']) == 3
        assert out['patterns'][-1]['type'] == 'solid'
        assert out['patterns'][-1]['color'] == [0, 0, 0]

    def test_no_trailing_solid_when_last_is_solid(self):
        out = json.loads(prepJsonRemote([_model(1, 'solid')], [_scene_row(1)]))
        assert [p['type'] for p in out['patterns']] == ['solid']

    def test_local_adds_pin_and_brightness(self):
        p = json.loads(prepJsonRemote([_model(1, 'beam')], [_scene_row(1)],
                                      isLocal=True))['patterns'][0]
        assert p['outPinID'] == 18 and p['brightness'] == 0.5
        # remote payload must NOT carry box-specific fields
        r = json.loads(prepJsonRemote([_model(1, 'beam')],
                                      [_scene_row(1)]))['patterns'][0]
        assert 'outPinID' not in r and 'brightness' not in r

    def test_deleted_model_row_skipped_not_crashed(self):
        out = json.loads(prepJsonRemote([_model(2, 'beam')],
                                        [_scene_row(99), _scene_row(2)]))
        types = [p['type'] for p in out['patterns']]
        assert 'beam' in types           # surviving row still played
