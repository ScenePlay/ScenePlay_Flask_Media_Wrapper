"""Floorplan validator (3D mode geometry): schema checks, grid rescaling,
coordinate clamping, door id assignment, and the size caps. Pure tests —
persistence and endpoints live in routes/battlemap.py."""

import pytest

from floorplan import (validate_floorplan, floorplan_summary,
                       floorplan_layout_text,
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
