"""Local-access password recovery lifecycle (routes/auth.py helpers).

sql.database is pointed at a scratch db and RECOVERY_DIR at tmp_path, so the
code-file lifecycle (write, verify, expire, rate-limit, clear) runs for real
without touching the app database or filesystem.
"""

import os
import re
import sqlite3

import pytest

import sql
import routes.auth as auth


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / 'scratch.db')
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE tblAppSettings (name TEXT, value TEXT, typevalue TEXT)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(sql, 'database', db_path)
    monkeypatch.setattr(auth, 'RECOVERY_DIR', str(tmp_path / 'password_recovery'))
    return tmp_path


def _read_code(path):
    text = open(path).read()
    return re.search(r'Code:\s+([A-Z2-9-]+)', text).group(1)


def test_begin_writes_file_and_correct_code_passes(env):
    path = auth._recovery_begin('bendm')
    assert os.path.exists(path)
    code = _read_code(path)
    ok, err = auth._recovery_check('bendm', code)
    assert ok and err is None


def test_code_is_single_use_after_clear(env):
    path = auth._recovery_begin('bendm')
    code = _read_code(path)
    assert auth._recovery_check('bendm', code)[0]
    auth._recovery_clear()
    assert not os.path.exists(path)
    ok, err = auth._recovery_check('bendm', code)
    assert not ok and 'generate one first' in err


def test_wrong_code_and_username_mismatch(env):
    path = auth._recovery_begin('bendm')
    code = _read_code(path)
    ok, err = auth._recovery_check('bendm', 'AAAA-AAAA')
    assert not ok and 'Incorrect code' in err
    ok, err = auth._recovery_check('someone_else', code)
    assert not ok and 'different username' in err
    # normalization: lowercase / spaces / missing dash all accepted
    assert auth._recovery_check('bendm', code.replace('-', ' ').lower())[0]


def test_rate_limit_invalidates(env):
    path = auth._recovery_begin('bendm')
    code = _read_code(path)
    for _ in range(auth._RECOVERY_MAX_TRIES):
        auth._recovery_check('bendm', 'BBBB-BBBB')
    ok, err = auth._recovery_check('bendm', code)   # even the right code now fails
    assert not ok and 'Too many attempts' in err
    assert not os.path.exists(path)                 # file removed on invalidation


def test_expired_code_rejected(env):
    path = auth._recovery_begin('bendm')
    code = _read_code(path)
    sql.appsettingSet('pw_recovery_expires', '2000-01-01 00:00:00')
    ok, err = auth._recovery_check('bendm', code)
    assert not ok and 'expired' in err
    assert not os.path.exists(path)


def test_regenerate_replaces_previous_code(env):
    path = auth._recovery_begin('bendm')
    old_code = _read_code(path)
    auth._recovery_begin('bendm')
    new_code = _read_code(path)
    assert old_code != new_code
    assert not auth._recovery_check('bendm', old_code)[0]
    assert auth._recovery_check('bendm', new_code)[0]
