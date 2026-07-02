"""Shared fixtures: a minimal Flask app bound to an in-memory SQLite DB.

Deliberately does NOT import app.py (which has module-level side effects:
seeding, multiprocessing arrays, upload-dir creation). Only the extensions
and models are loaded. Audio libs (alsaaudio/pulsectl) are stubbed if absent
so the suite runs on machines without sound hardware.
"""
import sys
import types

import pytest

# Stub hardware audio libs BEFORE extensions is imported (it imports them
# at module level). Harmless if the real ones are installed.
for _mod in ('alsaaudio', 'pulsectl'):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = types.ModuleType(_mod)

from flask import Flask            # noqa: E402
from extensions import db          # noqa: E402
# Register every table the TTRPG models reference via ForeignKey (create_all
# fails on dangling FKs, e.g. tblSessions.campaign_id -> tblcampaigns).
import models.ttrpg                # noqa: E402,F401
import models.user                 # noqa: E402,F401
import models.campaigns            # noqa: E402,F401
import models.scenes               # noqa: E402,F401
import models.tblRollLog           # noqa: E402,F401
import models.tblTokenPositions    # noqa: E402,F401


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'   # in-memory
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.rollback()
        db.drop_all()


@pytest.fixture()
def character(app):
    """A minimal active character with known HP bounds."""
    from models.user import tblUsers
    from models.ttrpg import tblCharacters
    user = tblUsers(username='tester', display_name='Tester',
                    password_hash='x', role='player', active=1,
                    created_at='2026-01-01 00:00:00')
    db.session.add(user)
    db.session.flush()
    char = tblCharacters(
        user_id=user.user_id, name='Hero', char_class='Fighter', race='Human',
        level=3, hp_current=20, hp_max=30, ac=15, speed=30,
        active=1, created_at='2026-01-01 00:00:00',
    )
    db.session.add(char)
    db.session.commit()
    return char
