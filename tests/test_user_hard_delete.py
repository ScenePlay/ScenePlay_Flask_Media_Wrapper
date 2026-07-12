"""Deleting a user keeps their characters by reassigning them first.

Mirrors the logic in auth.delete_user: reassign, then hard-delete the
account. A straight delete of a user who still owns characters would
raise IntegrityError (tblCharacters.user_id is NOT NULL).
"""
from extensions import db


def test_delete_user_keeps_characters(character):
    from models.user import tblUsers
    from models.ttrpg import tblCharacters, tblCharacterResources

    dm = tblUsers(username='dm', display_name='The DM',
                  password_hash='x', role='dm', active=1,
                  created_at='2026-01-01 00:00:00')
    res = tblCharacterResources(character_id=character.character_id,
                                resource_name='Rage', current_val=2, max_val=3)
    db.session.add_all([dm, res])
    db.session.commit()

    player = db.session.get(tblUsers, character.user_id)
    for char in list(player.characters):
        char.user = dm
    db.session.delete(player)
    db.session.commit()

    assert db.session.get(tblUsers, player.user_id) is None
    survivor = db.session.get(tblCharacters, character.character_id)
    assert survivor is not None
    assert survivor.user_id == dm.user_id
    assert tblCharacterResources.query.count() == 1
