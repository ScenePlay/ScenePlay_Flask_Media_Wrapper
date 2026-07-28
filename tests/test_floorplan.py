"""Floorplan validator (3D mode geometry): schema checks, grid rescaling,
coordinate clamping, door id assignment, and the size caps. Pure tests —
persistence and endpoints live in routes/battlemap.py."""

import pytest

from floorplan import (validate_floorplan, floorplan_summary,
                       MAX_WALLS, DEFAULT_WALL_HEIGHT_FT)


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
        ({'schema_version': 2}, 'schema_version'),
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
