"""Relay boot-crash guard: sentinel arm/disarm semantics that break the
Pi-Zero boot loop (crash during relay bring-up -> next boot skips the relay)."""

import time

import relay_guard as rg


def test_arm_trip_disarm(tmp_path):
    p = str(tmp_path / 'guard')
    assert rg.tripped(p) is False        # clean box
    rg.arm(p)
    assert rg.tripped(p) is True         # crash now -> next boot sees this
    rg.disarm(p)
    assert rg.tripped(p) is False        # survived -> next boot starts relay


def test_disarm_is_idempotent(tmp_path):
    p = str(tmp_path / 'guard')
    rg.disarm(p)                         # nothing armed — must not raise
    assert rg.tripped(p) is False


def test_disarm_after_grace(tmp_path):
    p = str(tmp_path / 'guard')
    rg.arm(p)
    t = rg.disarm_after_grace(p, seconds=0.05)
    assert rg.tripped(p) is True         # still armed inside the grace window
    t.join(2)
    assert rg.tripped(p) is False        # survived the grace period
