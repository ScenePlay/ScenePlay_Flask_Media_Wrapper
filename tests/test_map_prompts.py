"""Stored LLM prompts per battle map (tblBattleMapPrompts): one row per
(map, kind) with latest-wins updates, removed with the map. Endpoint behavior
(DM gate, size cap) lives in routes/battlemap.py and is exercised there."""

from extensions import db
from models.ttrpg import tblBattleMaps, tblBattleMapPrompts, tblSessions


def _map(session_id):
    bm = tblBattleMaps(session_id=session_id, name='Crypt',
                       created_at='2026-01-01 00:00:00')
    db.session.add(bm)
    db.session.commit()
    return bm


def _session():
    s = tblSessions(title='S', created_at='2026-01-01 00:00:00')
    db.session.add(s)
    db.session.commit()
    return s


class TestMapPrompts:
    def test_one_row_per_kind_latest_wins(self, app):
        bm = _map(_session().session_id)
        db.session.add(tblBattleMapPrompts(
            map_id=bm.map_id, kind='art', prompt_text='v1',
            settings_json='{"genre":"fantasy"}', updated_at='t1'))
        db.session.commit()
        row = tblBattleMapPrompts.query.filter_by(map_id=bm.map_id,
                                                  kind='art').one()
        row.prompt_text, row.updated_at = 'v2', 't2'
        db.session.commit()
        rows = tblBattleMapPrompts.query.filter_by(map_id=bm.map_id).all()
        assert len(rows) == 1 and rows[0].prompt_text == 'v2'

    def test_art_and_layout_coexist(self, app):
        bm = _map(_session().session_id)
        for kind in ('art', 'layout'):
            db.session.add(tblBattleMapPrompts(
                map_id=bm.map_id, kind=kind, prompt_text=kind, updated_at='t'))
        db.session.commit()
        assert tblBattleMapPrompts.query.filter_by(map_id=bm.map_id).count() == 2

    def test_deleted_with_map(self, app):
        bm = _map(_session().session_id)
        db.session.add(tblBattleMapPrompts(
            map_id=bm.map_id, kind='layout', prompt_text='p', updated_at='t'))
        db.session.commit()
        db.session.delete(bm)
        db.session.commit()
        assert tblBattleMapPrompts.query.count() == 0
