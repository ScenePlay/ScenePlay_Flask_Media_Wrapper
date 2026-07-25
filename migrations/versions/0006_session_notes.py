"""Session notes go multi-row: carry tblSessions.dm_notes into tblSessionNotes.

The session page's single dm_notes textarea became a many-notes list
(tblSessionNotes, mirroring tblBattleMapNotes). Existing dm_notes text must
survive as the first note. The dm_notes column itself stays (SQLite column
drops are a table rebuild; nothing writes it anymore).

Guards make this safe everywhere it can run:
- fresh database: db.create_all() has already built tblSessionNotes; there
  are no sessions yet, so nothing copies.
- pre-ttrpg database (no tblSessions): nothing to do.
- re-run / already-copied: a session with ANY notes rows is skipped.

Revision ID: 0006_session_notes
Revises: 0005_music_scene_loops
Create Date: 2026-07-24
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '0006_session_notes'
down_revision = '0005_music_scene_loops'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    def cols(table):
        return [r[1] for r in bind.exec_driver_sql(f'PRAGMA table_info("{table}")')]

    if not cols('tblSessions') or 'dm_notes' not in cols('tblSessions'):
        return
    if not cols('tblSessionNotes'):
        # Standalone-upgrade path (e.g. the migration test suite) where
        # create_all didn't run first.
        bind.exec_driver_sql(
            "CREATE TABLE tblSessionNotes ("
            " note_id INTEGER PRIMARY KEY,"
            " session_id INTEGER NOT NULL REFERENCES tblSessions(session_id),"
            " title TEXT DEFAULT '',"
            " body TEXT DEFAULT '',"
            " sort_order INT DEFAULT 0,"
            " created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL)")

    rows = bind.exec_driver_sql(
        "SELECT session_id, dm_notes, created_at FROM tblSessions "
        "WHERE dm_notes IS NOT NULL AND TRIM(dm_notes) <> ''").fetchall()
    for sid, body, created in rows:
        already = bind.exec_driver_sql(
            "SELECT COUNT(*) FROM tblSessionNotes WHERE session_id = ?",
            (sid,)).fetchone()[0]
        if already:
            continue
        bind.exec_driver_sql(
            "INSERT INTO tblSessionNotes"
            " (session_id, title, body, sort_order, created_at, updated_at)"
            " VALUES (?, 'Session notes', ?, 0, ?, ?)",
            (sid, body, created or '', created or ''))


def downgrade():
    # The copied rows are additive; dm_notes was never cleared. Nothing to undo.
    pass
