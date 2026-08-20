"""Floorplan validator (3D mode geometry): schema checks, grid rescaling,
coordinate clamping, door id assignment, and the size caps. Pure tests —
persistence and endpoints live in routes/battlemap.py."""

import pytest

from floorplan import (validate_floorplan, floorplan_summary,
                       floorplan_layout_text, SCHEMA_VERSION,
                       MAX_WALLS, MAX_LIGHTS, DEFAULT_WALL_HEIGHT_FT)


def _plan(**over):
    base = {
        'format': 'sceneplay-floorplan', 'schema_version': 1,
        'grid': {'cols': 20, 'rows': 20},
        'walls': [{'x1': 3, 'y1': 0, 'x2': 3, 'y2': 6.5}],
        'doors': [{'id': 'd1', 'x1': 3, 'y1': 6.5, 'x2': 3, 'y2': 7.5}],
        'elevations': [{'x1': 5, 'y1': 5, 'x2': 9, 'y2': 9, 'floor_ft': -10}],
    }
    base.update(over)
    return base


class TestHappyPath:
    def test_valid_plan_round_trips(self):
        clean, warnings, errors = validate_floorplan(_plan(), 20, 20)
        assert errors == [] and warnings == []
        assert len(clean['walls']) == 1
        assert clean['doors'][0]['id'] == 'd1'
        assert clean['doors'][0]['open'] is False
        assert clean['grid'] == {'cols': 20, 'rows': 20}

    def test_summary(self):
        clean, _, _ = validate_floorplan(_plan(), 20, 20)
        assert floorplan_summary(clean) == '1 walls · 1 doors · 1 elevation region'

    def test_defaults_omitted_from_clean_json(self):
        # A door at the wall default height is stripped (doors inherit wall
        # height); an explicitly shorter door keeps its height_ft so the 3D
        # renderer knows to draw a lintel above it.
        clean, _, _ = validate_floorplan(_plan(
            doors=[{'x1': 1, 'y1': 1, 'x2': 2, 'y2': 1,
                    'height_ft': DEFAULT_WALL_HEIGHT_FT},
                   {'x1': 3, 'y1': 1, 'x2': 4, 'y2': 1, 'height_ft': 6}]), 20, 20)
        assert 'height_ft' not in clean['doors'][0]
        assert clean['doors'][1]['height_ft'] == 6


class TestGridRescale:
    def test_mismatched_grid_rescales_and_warns(self):
        clean, warnings, errors = validate_floorplan(
            _plan(grid={'cols': 10, 'rows': 10}), 20, 20)
        assert errors == [] and any('rescaled' in w for w in warnings)
        assert clean['walls'][0]['x1'] == 6.0        # 3 * (20/10)
        assert clean['walls'][0]['y2'] == 13.0       # 6.5 * 2

    def test_absent_grid_is_accepted_unscaled(self):
        plan = _plan()
        del plan['grid']
        clean, warnings, errors = validate_floorplan(plan, 20, 20)
        assert errors == [] and clean['walls'][0]['x1'] == 3.0

    def test_nonsense_grid_rejected(self):
        _, _, errors = validate_floorplan(_plan(grid={'cols': 0, 'rows': 20}), 20, 20)
        assert errors


class TestRejections:
    @pytest.mark.parametrize('bad, needle', [
        ({'schema_version': 3}, 'schema_version'),
        ('not a dict', 'JSON object'),
        (_plan(walls='nope'), '"walls" must be a list'),
        (_plan(walls=[{'x1': 1, 'y1': 1, 'x2': 'x', 'y2': 2}]), 'invalid "x2"'),
        (_plan(elevations=[{'x1': 1, 'y1': 1, 'x2': 3, 'y2': 3}]), 'floor_ft'),
        (_plan(walls=[{}] * (MAX_WALLS + 1)), 'too many walls'),
    ])
    def test_rejected(self, bad, needle):
        clean, _, errors = validate_floorplan(bad, 20, 20)
        assert clean is None
        assert any(needle in e for e in errors), errors


class TestNormalization:
    def test_coords_clamped_to_grid(self):
        clean, _, errors = validate_floorplan(
            _plan(walls=[{'x1': -5, 'y1': 0, 'x2': -5, 'y2': 99}]), 20, 20)
        assert errors == []
        assert clean['walls'] == [{'x1': 0.0, 'y1': 0.0, 'x2': 0.0, 'y2': 20.0}]

    def test_zero_length_segments_dropped_with_empty_warning(self):
        clean, warnings, errors = validate_floorplan(
            _plan(walls=[{'x1': 4, 'y1': 4, 'x2': 4, 'y2': 4}],
                  doors=[], elevations=[]), 20, 20)
        assert errors == [] and clean['walls'] == []
        assert any('no walls' in w for w in warnings)

    def test_door_ids_autoassigned_and_deduped(self):
        clean, _, errors = validate_floorplan(_plan(doors=[
            {'x1': 1, 'y1': 1, 'x2': 2, 'y2': 1},
            {'id': 'd1', 'x1': 3, 'y1': 1, 'x2': 4, 'y2': 1},
            {'id': 'd1', 'x1': 5, 'y1': 1, 'x2': 6, 'y2': 1},
        ]), 20, 20)
        assert errors == []
        ids = [d['id'] for d in clean['doors']]
        assert len(set(ids)) == 3 and 'd1' in ids

    def test_wall_show_passthrough(self):
        clean, _, errors = validate_floorplan(_plan(walls=[
            {'x1': 1, 'y1': 1, 'x2': 5, 'y2': 1, 'show': True},
            {'x1': 1, 'y1': 2, 'x2': 5, 'y2': 2},
        ]), 20, 20)
        assert errors == []
        assert clean['walls'][0]['show'] is True
        assert 'show' not in clean['walls'][1]

    def test_wall_style_passthrough(self):
        clean, warnings, errors = validate_floorplan(_plan(wall_style='brick'), 20, 20)
        assert errors == [] and clean['wall_style'] == 'brick'
        # 'none' and absent are both omitted from the clean JSON
        clean2, _, _ = validate_floorplan(_plan(wall_style='none'), 20, 20)
        assert 'wall_style' not in clean2
        clean3, w3, e3 = validate_floorplan(_plan(wall_style='marble'), 20, 20)
        assert e3 == [] and 'wall_style' not in clean3
        assert any('wall_style' in w for w in w3)

    def test_circle_elevation(self):
        clean, _, errors = validate_floorplan(_plan(elevations=[
            {'shape': 'circle', 'cx': 10, 'cy': 8, 'r': 2.5, 'floor_ft': -10, 'label': 'well'},
        ]), 20, 20)
        assert errors == []
        e = clean['elevations'][0]
        assert e == {'shape': 'circle', 'cx': 10.0, 'cy': 8.0, 'r': 2.5,
                     'floor_ft': -10.0, 'label': 'well'}
        _, _, errs = validate_floorplan(_plan(elevations=[
            {'shape': 'circle', 'cx': 10, 'cy': 8}]), 20, 20)
        assert any('circle needs' in x for x in errs)

    def test_elevation_corners_normalized(self):
        clean, _, _ = validate_floorplan(
            _plan(elevations=[{'x1': 9, 'y1': 9, 'x2': 5, 'y2': 5, 'floor_ft': 10}]),
            20, 20)
        e = clean['elevations'][0]
        assert (e['x1'], e['y1'], e['x2'], e['y2']) == (5.0, 5.0, 9.0, 9.0)


class TestSchemaV2:
    def test_v1_plans_accepted_and_stamped_current(self):
        clean, warnings, errors = validate_floorplan(_plan(), 20, 20)
        assert errors == []
        assert clean['schema_version'] == SCHEMA_VERSION
        # empty v2 layers are omitted so v1-era plans stay byte-compatible
        assert 'lights' not in clean and 'props' not in clean and 'zones' not in clean

    def test_one_foot_precision_round_trips(self):
        # x=6.2: well clear of the base plan's door at column 3, which the
        # doorway carve would otherwise trim against
        clean, _, errors = validate_floorplan(
            _plan(walls=[{'x1': 6.2, 'y1': 0.4, 'x2': 6.2, 'y2': 6.8}]), 20, 20)
        assert errors == []
        w = clean['walls'][0]
        assert (w['x1'], w['y1'], w['y2']) == (6.2, 0.4, 6.8)

    def test_light_defaults_and_overrides(self):
        clean, warnings, errors = validate_floorplan(_plan(lights=[
            {'x': 4, 'y': 6, 'type': 'torch'},
            {'x': 1, 'y': 1, 'type': 'glow', 'color': '#7FB8FF',
             'intensity': 99, 'radius_ft': 1, 'height_ft': -5, 'flicker': True},
        ]), 20, 20)
        assert errors == []
        assert clean['lights'][0] == {'x': 4.0, 'y': 6.0, 'type': 'torch'}
        lt = clean['lights'][1]
        assert lt['color'] == '#7fb8ff'
        assert lt['intensity'] == 3.0 and lt['radius_ft'] == 5.0
        assert lt['height_ft'] == 0.0 and lt['flicker'] is True

    def test_light_bad_type_color_and_coords(self):
        clean, warnings, errors = validate_floorplan(_plan(lights=[
            {'x': 4, 'y': 6, 'type': 'lava_lamp', 'color': 'orange'},
            {'type': 'torch'},
        ]), 20, 20)
        assert errors == []
        assert len(clean['lights']) == 1               # missing x/y dropped
        assert clean['lights'][0]['type'] == 'torch'   # unknown type coerced
        assert 'color' not in clean['lights'][0]
        assert any('lava_lamp' in w for w in warnings)
        assert any('color' in w for w in warnings)
        assert any('x/y' in w for w in warnings)

    def test_light_cap(self):
        _, _, errors = validate_floorplan(
            _plan(lights=[{}] * (MAX_LIGHTS + 1)), 20, 20)
        assert any('too many lights' in e for e in errors)

    def test_props_validated(self):
        clean, warnings, errors = validate_floorplan(_plan(props=[
            {'type': 'barrel', 'x': 5, 'y': 5.4, 'rot': 400, 'scale': 99,
             'texture': 'oak_planks'},
            {'type': 'jacuzzi', 'x': 1, 'y': 1},
            {'type': 'crate'},
        ]), 20, 20)
        assert errors == []
        assert len(clean['props']) == 1                # unknown type + no x/y dropped
        p = clean['props'][0]
        assert p['rot'] == 40.0 and p['scale'] == 4.0 and p['texture'] == 'oak_planks'
        assert any('jacuzzi' in w for w in warnings)

    def test_zones_validated(self):
        clean, warnings, errors = validate_floorplan(_plan(zones=[
            {'name': 'Great Hall', 'rects': [{'x1': 2, 'y1': 2, 'x2': 10, 'y2': 8}],
             'floor_texture': 'flagstone', 'wall_texture': 'BAD SLUG!',
             'wall_style': 'stone'},
            {'rects': []},
        ]), 20, 20)
        assert errors == []
        assert len(clean['zones']) == 1
        z = clean['zones'][0]
        assert z['id'] == 'z1' and z['name'] == 'Great Hall'
        assert z['floor_texture'] == 'flagstone' and 'wall_texture' not in z
        assert z['wall_style'] == 'stone'
        assert any('texture ref' in w for w in warnings)
        assert any('"rects"' in w for w in warnings)

    def test_segment_texture_and_style(self):
        clean, warnings, errors = validate_floorplan(_plan(
            walls=[{'x1': 1, 'y1': 1, 'x2': 5, 'y2': 1,
                    'style': 'wood', 'texture': 'mossy_stone'}],
            doors=[{'x1': 5, 'y1': 1, 'x2': 6, 'y2': 1, 'texture': 'Oak Planks'}],
        ), 20, 20)
        assert errors == []
        assert clean['walls'][0]['style'] == 'wood'
        assert clean['walls'][0]['texture'] == 'mossy_stone'
        # texture ref with spaces/uppercase fails the slug shape -> warned, dropped
        assert 'texture' not in clean['doors'][0]
        assert any('texture ref' in w for w in warnings)

    def test_summary_includes_v2_layers(self):
        clean, _, _ = validate_floorplan(_plan(
            lights=[{'x': 1, 'y': 1, 'type': 'torch'}],
            props=[{'type': 'crate', 'x': 2, 'y': 2}],
            zones=[{'rects': [{'x1': 0, 'y1': 0, 'x2': 5, 'y2': 5}]}],
        ), 20, 20)
        s = floorplan_summary(clean)
        assert '1 light' in s and '1 prop' in s and '1 zone' in s

    def test_layout_text_mentions_lights_props_rooms(self):
        clean, _, _ = validate_floorplan(_plan(
            lights=[{'x': 4, 'y': 6, 'type': 'torch'},
                    {'x': 10, 'y': 10, 'type': 'brazier'}],
            props=[{'type': 'crate', 'x': 2, 'y': 2},
                   {'type': 'crate', 'x': 3, 'y': 2}],
            zones=[{'name': 'Great Hall',
                    'rects': [{'x1': 2, 'y1': 2, 'x2': 10, 'y2': 8}]}],
        ), 20, 20)
        text = floorplan_layout_text(clean)
        assert '1 brazier, 1 torch' in text
        assert '2 crates' in text
        assert 'Room "Great Hall"' in text


class TestDoorwayCarve:
    """Walls running along a doorway are trimmed to the door's edges — the
    validator enforces the gap the prompts ask for, since LLMs keep ending
    walls mid-door or drawing the wall straight through the doorway."""

    DOOR = [{'id': 'd1', 'x1': 8, 'y1': 5, 'x2': 10, 'y2': 5}]

    def _carve(self, walls, doors=None):
        clean, warnings, errors = validate_floorplan(_plan(
            walls=walls, doors=self.DOOR if doors is None else doors,
            elevations=[]), 20, 20)
        assert errors == []
        return clean, warnings

    def test_wall_through_doorway_is_split_at_jambs(self):
        clean, warnings = self._carve(
            [{'x1': 2, 'y1': 5, 'x2': 16, 'y2': 5, 'height_ft': 15,
              'texture': 'medieval_stone'}])
        segs = sorted((w['x1'], w['x2']) for w in clean['walls'])
        assert segs == [(2.0, 8.0), (10.0, 16.0)]
        # trimmed pieces keep the wall's fields
        for w in clean['walls']:
            assert w['height_ft'] == 15 and w['texture'] == 'medieval_stone'
        assert any('trimmed' in w for w in warnings)

    def test_wall_ending_mid_door_is_clipped_to_jamb(self):
        clean, _ = self._carve([{'x1': 2, 'y1': 5, 'x2': 9, 'y2': 5}])
        assert clean['walls'] == [{'x1': 2.0, 'y1': 5.0, 'x2': 8.0, 'y2': 5.0}]

    def test_wall_wholly_inside_door_is_dropped(self):
        clean, warnings = self._carve([{'x1': 8.4, 'y1': 5, 'x2': 9.6, 'y2': 5}])
        assert clean['walls'] == []
        assert any('trimmed' in w for w in warnings)

    def test_perpendicular_wall_is_left_alone(self):
        clean, warnings = self._carve([{'x1': 9, 'y1': 1, 'x2': 9, 'y2': 9}])
        assert clean['walls'] == [{'x1': 9.0, 'y1': 1.0, 'x2': 9.0, 'y2': 9.0}]
        assert not any('trimmed' in w for w in warnings)

    def test_wall_meeting_the_jamb_exactly_is_untouched(self):
        clean, warnings = self._carve([{'x1': 2, 'y1': 5, 'x2': 8, 'y2': 5},
                                       {'x1': 10, 'y1': 5, 'x2': 16, 'y2': 5}])
        assert len(clean['walls']) == 2
        assert not any('trimmed' in w for w in warnings)

    def test_slightly_offset_parallel_wall_is_carved(self):
        # 0.2 cells (1 ft) off the door line — still "the same wall" to a human
        clean, _ = self._carve([{'x1': 2, 'y1': 5.2, 'x2': 16, 'y2': 5.2}])
        assert len(clean['walls']) == 2
        xs = sorted(round(w['x2'], 1) for w in clean['walls'])
        assert 8.0 in xs   # cut lands on the jamb

    def test_wall_spanning_two_doorways(self):
        doors = [{'id': 'd1', 'x1': 5, 'y1': 5, 'x2': 6, 'y2': 5},
                 {'id': 'd2', 'x1': 12, 'y1': 5, 'x2': 13, 'y2': 5}]
        clean, _ = self._carve([{'x1': 2, 'y1': 5, 'x2': 18, 'y2': 5}], doors)
        segs = sorted((w['x1'], w['x2']) for w in clean['walls'])
        assert segs == [(2.0, 5.0), (6.0, 12.0), (13.0, 18.0)]


class TestPropDefaultTextures:
    def test_every_prop_type_has_a_default_bitmap(self):
        from floorplan import PROP_TYPES, PROP_DEFAULT_TEXTURES
        missing = PROP_TYPES - set(PROP_DEFAULT_TEXTURES)
        assert not missing, f'prop types without a default texture: {sorted(missing)}'
        orphans = set(PROP_DEFAULT_TEXTURES) - PROP_TYPES
        assert not orphans, f'defaults for unknown prop types: {sorted(orphans)}'

    def test_defaults_reference_builtin_textures(self):
        import json
        import os
        from floorplan import PROP_DEFAULT_TEXTURES
        manifest = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'static', 'textures', 'builtin',
            'manifest.json')
        names = {e['name'] for e in json.load(open(manifest))}
        bad = {t for t in PROP_DEFAULT_TEXTURES.values() if t not in names}
        assert not bad, f'default textures missing from the builtin library: {sorted(bad)}'


class TestLayoutText:
    def _text(self, **over):
        clean, _, errors = validate_floorplan(_plan(**over), 20, 20)
        assert errors == []
        return floorplan_layout_text(clean)

    def test_header_and_feet_conversion(self):
        text = self._text()
        assert 'Grid: 20 x 20 squares (100 ft x 100 ft)' in text
        assert '1 square = 5 ft' in text

    def test_wall_aggregate_and_trailer(self):
        text = self._text()
        assert '1 wall segment;' in text
        assert 'columns 3-3, rows 0-6.5' in text
        assert text.endswith('Everything not listed is flat open floor at ground level.')

    def test_door_line(self):
        # d1 runs down column 3 from row 6.5 to 7.5 -> vertical, 5 ft, left/middle.
        # No door ids in the prose: models paint them into the art as labels.
        text = self._text()
        assert 'A vertical doorway 5 ft wide at column 3, rows 6.5-7.5' in text
        assert 'left of the map' in text
        assert 'd1' not in text

    def test_horizontal_door(self):
        text = self._text(doors=[{'id': 'gate', 'x1': 8, 'y1': 10, 'x2': 9.5, 'y2': 10}])
        assert 'A horizontal doorway 7.5 ft wide at row 10, columns 8-9.5' in text
        assert 'center of the map' in text
        assert 'gate' not in text

    def test_pit_platform_and_circle_phrasing(self):
        text = self._text(elevations=[
            {'x1': 5, 'y1': 5, 'x2': 9, 'y2': 9, 'floor_ft': -10, 'label': 'spike pit'},
            {'x1': 12, 'y1': 2, 'x2': 16, 'y2': 4, 'floor_ft': 15},
            {'shape': 'circle', 'cx': 10, 'cy': 18, 'r': 2, 'floor_ft': -20},
        ])
        assert 'Pit 10 ft deep: 20 ft x 20 ft, from (5,5) to (9,9) ("spike pit").' in text
        assert 'Raised platform 15 ft high: 20 ft x 10 ft, from (12,2) to (16,4).' in text
        assert 'Circular pit 20 ft deep: radius 10 ft, centered at (10,18).' in text

    def test_door_truncation_past_cap(self):
        doors = [{'id': f'd{i}', 'x1': 0.5 * i, 'y1': 1, 'x2': 0.5 * i + 0.5, 'y2': 1}
                 for i in range(25)]
        text = self._text(doors=doors)
        assert '...and 5 more doorways' in text
        assert text.count('doorway ') == 20

    def test_empty_plan_no_crash(self):
        text = self._text(walls=[], doors=[], elevations=[])
        assert 'open ground' in text
        assert 'doorway' not in text and 'Pit' not in text
