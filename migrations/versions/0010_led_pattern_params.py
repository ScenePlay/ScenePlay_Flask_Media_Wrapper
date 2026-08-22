"""Scene RPiLED patterns: registry-shaped rows.

tblScenePattern becomes (scenePattern_ID, scene_ID, patternType, params JSON,
orderBy). The pattern type and its parameters are described by the code
registry (led_patterns.py); the old tblLEDTypeModel "template" table — which
only ever supplied per-type defaults — is dropped.

Existing rows are CONVERTED, not lost: the type comes from the row's old
model, and the old fixed columns (color, cdiff, wait_ms, iterations,
direction, brightness) map onto the generic vocabulary via
led_patterns.legacy_to_params (iterations → duration in seconds, with the
old 9999999 "forever" sentinel → 0; the hardware brightness value the old
rows copied in becomes creative 1.0 so nothing double-dims once the LED
Config cap applies). outPin is dropped — the pin always came from LED Config.

Guarded: a database that already has patternType passes straight through,
and a fresh install (create_table made the new shape) only drops the model
table if it exists.

Revision ID: 0010_led_pattern_params
Revises: 0009_floorplan_history
Create Date: 2026-08-22
"""
import json
import os
import sys

from alembic import op

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import led_patterns as reg  # noqa: E402

# revision identifiers, used by Alembic.
revision = '0010_led_pattern_params'
down_revision = '0009_floorplan_history'
branch_labels = None
depends_on = None

NEW_DDL = ('CREATE TABLE tblScenePattern ('
           'scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT, scene_ID INT, '
           'patternType TEXT, params TEXT, orderBy INT)')
OLD_DDL = ('CREATE TABLE tblScenePattern ('
           'scenePattern_ID INTEGER PRIMARY KEY AUTOINCREMENT, scene_ID INT, '
           'ledTypeModel_ID INT, color TEXT, wait_ms INT, iterations INT, '
           'direction INT, cdiff TEXT, orderBy INT, outPin INT, brightness REAL)')


def _tables(bind):
    """Real table names keyed by lowercase (SQLite names are case-insensitive
    but old backups spell tblLedTypeModel differently from create_table)."""
    return {r[0].lower(): r[0] for r in bind.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(bind, table):
    return [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]


def _rows(bind, sql):
    res = bind.exec_driver_sql(sql)
    keys = list(res.keys())
    return [dict(zip(keys, r)) for r in res.fetchall()]


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)
    sp = tables.get('tblscenepattern')
    model_tbl = tables.get('tblledtypemodel')

    if sp is None:
        bind.exec_driver_sql(NEW_DDL)
    elif 'patternType' not in _cols(bind, sp):
        types = {}
        if model_tbl:
            for r in _rows(bind, f'SELECT ledTypeModel_ID, ledJSON FROM "{model_tbl}"'):
                try:
                    types[r['ledTypeModel_ID']] = (json.loads(r['ledJSON'] or '{}') or {}).get('type')
                except (TypeError, ValueError):
                    pass
        old = _rows(bind, f'SELECT * FROM "{sp}"')
        bind.exec_driver_sql(f'ALTER TABLE "{sp}" RENAME TO _tblScenePattern_old')
        bind.exec_driver_sql(NEW_DDL)
        for r in old:
            ptype = types.get(r.get('ledTypeModel_ID'))
            params = reg.legacy_to_params(
                ptype, r.get('color'), r.get('cdiff'), r.get('wait_ms'),
                r.get('iterations'), r.get('direction'), r.get('brightness'))
            if params is None:
                continue            # model row was deleted → pattern was unplayable
            bind.exec_driver_sql(
                'INSERT INTO tblScenePattern(scenePattern_ID, scene_ID, patternType, '
                'params, orderBy) VALUES (?, ?, ?, ?, ?)',
                (r.get('scenePattern_ID'), r.get('scene_ID'), ptype,
                 json.dumps(params), r.get('orderBy')))
        bind.exec_driver_sql('DROP TABLE _tblScenePattern_old')

    if model_tbl:
        bind.exec_driver_sql(f'DROP TABLE "{model_tbl}"')


def downgrade():
    """Best effort: restore the old column shape (values NULL except scene,
    order and brightness) and an empty model table. The registry-era data
    cannot be expressed in the old columns, so this is a schema-only revert."""
    bind = op.get_bind()
    tables = _tables(bind)
    sp = tables.get('tblscenepattern')
    if sp and 'patternType' in _cols(bind, sp):
        old = _rows(bind, f'SELECT * FROM "{sp}"')
        bind.exec_driver_sql(f'ALTER TABLE "{sp}" RENAME TO _tblScenePattern_new')
        bind.exec_driver_sql(OLD_DDL)
        for r in old:
            try:
                b = (json.loads(r.get('params') or '{}') or {}).get('brightness')
            except (TypeError, ValueError):
                b = None
            bind.exec_driver_sql(
                'INSERT INTO tblScenePattern(scenePattern_ID, scene_ID, orderBy, brightness) '
                'VALUES (?, ?, ?, ?)',
                (r.get('scenePattern_ID'), r.get('scene_ID'), r.get('orderBy'), b))
        bind.exec_driver_sql('DROP TABLE _tblScenePattern_new')
    if 'tblledtypemodel' not in tables:
        bind.exec_driver_sql(
            'CREATE TABLE tblLEDTypeModel (ledTypeModel_ID INTEGER PRIMARY KEY '
            'AUTOINCREMENT, modelName TEXT, ledJSON TEXT)')
