"""Safety net around the riskiest sync logic in relay_receiver:
mutation application (HP clamping, conditions, attr whitelist), the
applied-ID idempotency ledger, and relay timestamp conversion.
"""
import json

import pytest

from extensions import db
import relay_receiver as rr


def _apply(char, mtype, data):
    rr._apply_mutation(char, mtype, data, 'http://relay.invalid', db)
    db.session.commit()


# ── hp_delta ──────────────────────────────────────────────────────────────────

def test_hp_delta_damage(character):
    _apply(character, 'hp_delta', {'delta': -5})
    assert character.hp_current == 15


def test_hp_delta_heal(character):
    _apply(character, 'hp_delta', {'delta': 4})
    assert character.hp_current == 24


def test_hp_delta_clamps_at_zero(character):
    _apply(character, 'hp_delta', {'delta': -999})
    assert character.hp_current == 0


def test_hp_delta_clamps_at_max(character):
    _apply(character, 'hp_delta', {'delta': 999})
    assert character.hp_current == character.hp_max


# ── conditions ────────────────────────────────────────────────────────────────

def test_condition_add_and_duplicate(character):
    _apply(character, 'condition_add', {'condition': 'Poisoned'})
    assert [c.condition_name for c in character.conditions] == ['Poisoned']
    # adding the same condition again must not duplicate it
    _apply(character, 'condition_add', {'condition': 'Poisoned'})
    assert len(character.conditions) == 1


def test_condition_remove(character):
    _apply(character, 'condition_add', {'condition': 'Stunned'})
    _apply(character, 'condition_remove', {'condition': 'Stunned'})
    assert character.conditions == []


def test_condition_remove_missing_is_noop(character):
    _apply(character, 'condition_remove', {'condition': 'NotThere'})
    assert character.conditions == []


# ── attr_save whitelist ───────────────────────────────────────────────────────

def test_attr_save_whitelisted_fields(character):
    _apply(character, 'attr_save', {'ac': 18, 'speed': 25, 'char_class': 'Paladin'})
    assert character.ac == 18
    assert character.speed == 25
    assert character.char_class == 'Paladin'


def test_attr_save_rejects_non_whitelisted(character):
    before_hp, before_name = character.hp_max, character.name
    # hp_max and name are NOT in the whitelist — a malicious/buggy portal
    # mutation must not be able to touch them
    _apply(character, 'attr_save', {'hp_max': 9999, 'name': 'Hacked'})
    assert character.hp_max == before_hp
    assert character.name == before_name


def test_unknown_mutation_type_is_noop(character):
    _apply(character, 'definitely_not_a_type', {'x': 1})
    assert character.hp_current == 20


# ── applied-ID ledger (idempotency; pairs with the double-apply fix) ─────────

@pytest.fixture()
def ledger_store(monkeypatch):
    store = {}
    monkeypatch.setattr('sql.appsettingGet', lambda k, d=None: store.get(k, d))
    monkeypatch.setattr('sql.appsettingSet',
                        lambda k, v, t='text': store.__setitem__(k, str(v)))
    return store


def test_ledger_round_trip(ledger_store):
    led = rr._applied_ledger_load()
    assert led == set()
    rr._applied_ledger_save(led, [1, 2, 3])
    assert rr._applied_ledger_load() == {1, 2, 3}


def test_ledger_ring_trims_oldest(ledger_store):
    led = rr._applied_ledger_load()
    rr._applied_ledger_save(led, range(rr._LEDGER_SIZE + 100))
    loaded = rr._applied_ledger_load()
    assert len(loaded) == rr._LEDGER_SIZE
    assert max(loaded) == rr._LEDGER_SIZE + 99   # newest kept
    assert 0 not in loaded                        # oldest trimmed


def test_ledger_survives_corrupt_setting(ledger_store):
    ledger_store[rr._LEDGER_KEY] = '{corrupt'
    assert rr._applied_ledger_load() == set()


def test_ledger_skip_semantics(character, ledger_store):
    """A mutation whose ID is in the ledger must not re-apply (the
    double-damage scenario when an ack POST fails)."""
    led = rr._applied_ledger_load()
    rr._applied_ledger_save(led, [42])
    ledger = rr._applied_ledger_load()
    mut = {'id': 42, 'applied': 0, 'player_name': 'Hero',
           'mutation_type': 'hp_delta', 'mutation_data': json.dumps({'delta': -5})}
    # replicate the loop's guard
    if mut['id'] in ledger:
        pass                                # skipped: re-ack only
    else:
        _apply(character, mut['mutation_type'], json.loads(mut['mutation_data']))
    assert character.hp_current == 20       # unchanged — not re-applied


# ── token reconciliation decision (seq preferred, timestamp fallback) ────────

def test_seq_newer_applies():
    assert rr._should_apply_relay_pos(5, 4, '', '') is True


def test_seq_equal_skips():
    """Local wins ties — an echo of our own push must not count as a new move."""
    assert rr._should_apply_relay_pos(5, 5, '', '') is False


def test_seq_lower_means_relay_reset_and_applies():
    """The relay's per-token seq only increments; its rows are dropped on map
    change / New Session. A LOWER seq therefore means the counter restarted —
    the write is genuinely new (skipping it froze player moves after resets)."""
    assert rr._should_apply_relay_pos(3, 5, '', '') is True
    assert rr._should_apply_relay_pos(1, 999, '', '') is True


def test_seq_ignores_clock_skew():
    """With seqs present, timestamps are irrelevant — even a relay timestamp
    far in the past (skewed clock) must not suppress a genuinely newer write."""
    assert rr._should_apply_relay_pos(2, 1, '2000-01-01T00:00:00', '2026-01-01T00:00:00') is True


def test_no_seq_falls_back_to_timestamps():
    # relay newer -> apply
    assert rr._should_apply_relay_pos(None, 0, '2026-01-02T00:00:00', '2026-01-01T00:00:00') is True
    # relay older/equal -> skip
    assert rr._should_apply_relay_pos(None, 0, '2026-01-01T00:00:00', '2026-01-01T00:00:00') is False
    # missing either timestamp -> apply (legacy permissive behavior)
    assert rr._should_apply_relay_pos(None, 0, '', '2026-01-01T00:00:00') is True


# ── relay timestamp conversion ────────────────────────────────────────────────

def test_ts_conversion_handles_zulu():
    out = rr._relay_ts_to_local('2026-06-30T15:04:05Z')
    assert len(out) == 19 and out[10] == ' '


def test_ts_conversion_garbage_falls_back():
    assert rr._relay_ts_to_local('') == ''
    assert rr._relay_ts_to_local('not-a-date') == 'not-a-date'[:19]
