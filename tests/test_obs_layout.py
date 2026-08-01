"""Party-scene grid geometry. Pure maths.

Two modes: an even grid with nobody featured, and the SPOTLIGHT — the featured
tile doubles in each direction and everyone else shrinks and repacks around it.
The invariants that matter are that tiles never overlap in either mode (nobody
gets covered), and that the spotlit tile really is 2x linear."""
import pytest

from obs_layout import (SPOTLIGHT_SPAN, choose_grid, choose_spotlight_grid,
                        frame_areas, grid_layout)


class TestChooseGrid:
    @pytest.mark.parametrize('n,expected', [
        (1, (1, 1)),
        (2, (2, 1)),
        (4, (2, 2)),
        (6, (3, 2)),
        # 8 players go 3x3 (one spare cell), NOT 4x2: 3x3 cells are exactly
        # 640x360 — true 16:9 for a webcam — while 4x2 gives near-square
        # 480x540 tiles that letterbox every camera.
        (8, (3, 3)),
        (9, (3, 3)),
    ])
    def test_common_party_sizes(self, n, expected):
        assert choose_grid(n, 1920, 1080) == expected

    def test_prefers_webcam_shaped_cells(self):
        """Cells should land near 16:9 for every realistic party size."""
        for n in range(1, 13):
            cols, rows = choose_grid(n, 1920, 1080)
            aspect = (1920 / cols) / (1080 / rows)
            assert 0.8 <= aspect <= 3.6, f'n={n} gave {cols}x{rows} (aspect {aspect:.2f})'

    def test_every_tile_gets_a_cell(self):
        for n in range(1, 17):
            cols, rows = choose_grid(n, 1920, 1080)
            assert cols * rows >= n

    def test_zero(self):
        assert choose_grid(0) == (0, 0)
        assert grid_layout(0) == []


class TestGridLayout:
    def test_tiles_stay_inside_the_canvas(self):
        for n in range(1, 13):
            for featured in [None] + list(range(n)):
                for t in grid_layout(n, 1920, 1080, featured=featured):
                    assert t['x'] >= -0.01 and t['y'] >= -0.01
                    assert t['x'] + t['w'] <= 1920.01
                    assert t['y'] + t['h'] <= 1080.01

    def test_no_overlap_when_nobody_is_featured(self):
        tiles = grid_layout(6, 1920, 1080)
        for i, a in enumerate(tiles):
            for b in tiles[i + 1:]:
                apart = (a['x'] + a['w'] <= b['x'] + .01 or b['x'] + b['w'] <= a['x'] + .01 or
                         a['y'] + a['h'] <= b['y'] + .01 or b['y'] + b['h'] <= a['y'] + .01)
                assert apart, f'tiles overlap: {a} {b}'

    def test_every_tile_is_the_same_size_when_nobody_is_featured(self):
        for n in range(1, 13):
            tiles = grid_layout(n, 1920, 1080)
            sizes = {(t['w'], t['h']) for t in tiles}
            assert len(sizes) == 1, f'n={n} -> {sizes}'

    def test_only_the_flag_marks_the_featured_tile(self):
        feat = grid_layout(6, 1920, 1080, featured=3)
        assert [t['featured'] for t in feat] == [False] * 3 + [True] + [False] * 2

    def test_short_last_row_is_centred(self):
        # 5 tiles in a 3x2 grid: the last row holds 2 and should be centred.
        tiles = grid_layout(5, 1920, 1080)
        cols, rows = choose_grid(5, 1920, 1080)
        assert (cols, rows) == (3, 2)
        last = tiles[3:]
        left_gap = last[0]['x']
        right_gap = 1920 - (last[-1]['x'] + last[-1]['w'])
        assert left_gap == pytest.approx(right_gap, abs=1.0)

    def test_gutter_separates_tiles(self):
        tiles = grid_layout(2, 1920, 1080, gutter=20)
        gap = tiles[1]['x'] - (tiles[0]['x'] + tiles[0]['w'])
        assert gap == pytest.approx(20, abs=0.5)

    def test_single_player_fills_the_canvas(self):
        t = grid_layout(1, 1920, 1080, gutter=0)[0]
        assert (t['x'], t['y'], t['w'], t['h']) == (0, 0, 1920, 1080)

    def test_respects_a_non_1080p_canvas(self):
        for t in grid_layout(4, 1280, 720):
            assert t['x'] + t['w'] <= 1280.01 and t['y'] + t['h'] <= 720.01


class TestSpotlight:
    """Featuring a player doubles their tile and shrinks everyone else."""

    def test_the_spotlit_tile_is_twice_the_size_of_the_others(self):
        for n in range(2, 13):
            for featured in range(n):
                tiles = grid_layout(n, 1920, 1080, featured=featured, gutter=0)
                hero = tiles[featured]
                others = [t for i, t in enumerate(tiles) if i != featured]
                assert hero['w'] == pytest.approx(others[0]['w'] * SPOTLIGHT_SPAN, rel=.01)
                assert hero['h'] == pytest.approx(others[0]['h'] * SPOTLIGHT_SPAN, rel=.01)

    def test_everyone_who_is_not_spotlit_stays_one_size(self):
        for n in range(2, 13):
            tiles = grid_layout(n, 1920, 1080, featured=0)
            sizes = {(t['w'], t['h']) for t in tiles[1:]}
            assert len(sizes) == 1, f'n={n} -> {sizes}'

    def test_nobody_is_ever_covered(self):
        """The reason this replaced the old grow-in-place spotlight."""
        for n in range(2, 13):
            for featured in range(n):
                tiles = grid_layout(n, 1920, 1080, featured=featured)
                for i, a in enumerate(tiles):
                    for b in tiles[i + 1:]:
                        apart = (a['x'] + a['w'] <= b['x'] + .01
                                 or b['x'] + b['w'] <= a['x'] + .01
                                 or a['y'] + a['h'] <= b['y'] + .01
                                 or b['y'] + b['h'] <= a['y'] + .01)
                        assert apart, f'n={n} featured={featured}: {a} over {b}'

    def test_the_others_shrink_relative_to_the_even_grid(self):
        """Where the extra room for the spotlight comes from."""
        for n in range(3, 13):
            even = grid_layout(n, 1920, 1080)[0]
            spot = [t for i, t in enumerate(grid_layout(n, 1920, 1080, featured=0))
                    if i != 0][0]
            assert spot['w'] * spot['h'] < even['w'] * even['h'], f'n={n}'

    def test_every_tile_is_placed(self):
        for n in range(2, 13):
            for featured in range(n):
                tiles = grid_layout(n, 1920, 1080, featured=featured)
                assert len(tiles) == n
                assert all(t is not None for t in tiles)
                assert sum(1 for t in tiles if t['featured']) == 1

    def test_a_lone_player_has_nothing_to_shrink(self):
        assert grid_layout(1, 1920, 1080, featured=0, gutter=0)[0]['w'] == 1920

    def test_out_of_range_featured_falls_back_to_the_even_grid(self):
        assert grid_layout(4, 1920, 1080, featured=9) == grid_layout(4, 1920, 1080)

    def test_grid_always_has_room_for_the_block_plus_everyone(self):
        for n in range(2, 17):
            cols, rows = choose_spotlight_grid(n, 1920, 1080)
            assert cols >= SPOTLIGHT_SPAN and rows >= SPOTLIGHT_SPAN
            assert cols * rows >= (n - 1) + SPOTLIGHT_SPAN ** 2

    def test_spotlight_stays_inside_the_tiles_area(self):
        a = frame_areas(1920, 1080, 'right', 0.3, 96)
        px, py, pw, ph = a['panel']
        for n in range(2, 10):
            for t in grid_layout(n, 1920, 1080, featured=0, area=a['tiles']):
                overlap_x = min(t['x'] + t['w'], px + pw) - max(t['x'], px)
                overlap_y = min(t['y'] + t['h'], py + ph) - max(t['y'], py)
                assert overlap_x <= 0.01 or overlap_y <= 0.01, \
                    f'n={n}: spotlight overlaps the panel'


class TestFrame:
    """Title strip along the top, information panel down one side, tiles in
    what's left. The tiles area is the contract that keeps a camera from
    landing underneath the panel."""

    def test_title_spans_the_full_width(self):
        a = frame_areas(1920, 1080, title_h=96)
        assert a['title'] == (0, 0, 1920, 96)

    def test_title_can_be_switched_off(self):
        a = frame_areas(1920, 1080, title_h=0)
        assert a['title'] is None
        assert a['tiles'][1] == 0, 'tiles should reclaim the strip'

    def test_panel_and_tiles_fill_the_body_exactly(self):
        for side in ('left', 'right', 'top', 'bottom'):
            a = frame_areas(1920, 1080, side, 0.25, 96)
            body = 1920 * (1080 - 96)
            area = a['panel'][2] * a['panel'][3] + a['tiles'][2] * a['tiles'][3]
            assert area == pytest.approx(body), side

    def test_nothing_overlaps_the_title(self):
        for side in ('left', 'right', 'top', 'bottom'):
            a = frame_areas(1920, 1080, side, 0.25, 96)
            assert a['panel'][1] >= 96 - 0.01, side
            assert a['tiles'][1] >= 96 - 0.01, side

    def test_panel_off_gives_tiles_the_whole_body(self):
        a = frame_areas(1920, 1080, panel_on=False, title_h=96)
        assert a['panel'] is None
        assert a['tiles'] == (0, 96, 1920, 1080 - 96)

    @pytest.mark.parametrize('frac,lo,hi', [(5.0, 0.12, 0.6), (0.0, 0.12, 0.6)])
    def test_fraction_is_clamped_to_something_usable(self, frac, lo, hi):
        a = frame_areas(1920, 1080, 'right', frac, 96)
        share = a['panel'][2] / 1920
        assert lo - 1e-9 <= share <= hi + 1e-9

    def test_a_giant_title_cannot_eat_the_canvas(self):
        a = frame_areas(1920, 1080, title_h=99999)
        assert a['title'][3] <= 1080 * 0.4
        assert a['tiles'][3] > 0

    def test_tiles_never_land_under_the_panel(self):
        for side in ('left', 'right', 'top', 'bottom'):
            a = frame_areas(1920, 1080, side, 0.3, 96)
            px, py, pw, ph = a['panel']
            for n in range(1, 10):
                for t in grid_layout(n, 1920, 1080, area=a['tiles']):
                    overlap_x = min(t['x'] + t['w'], px + pw) - max(t['x'], px)
                    overlap_y = min(t['y'] + t['h'], py + ph) - max(t['y'], py)
                    assert overlap_x <= 0.01 or overlap_y <= 0.01, \
                        f'{side} n={n}: tile overlaps the panel'
