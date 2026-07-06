"""Push-queue failure semantics (relay_broadcaster).

The queue must never let one doomed entry starve the others: a 4xx is dropped
immediately, and retry backoff is per-entry (stamped next-retry + move to
tail) rather than a worker-blocking sleep.
"""

import threading
import time

import relay_broadcaster as rb


class _FakeHTTPError(Exception):
    def __init__(self, status):
        super().__init__(f'{status} error')
        self.response = type('R', (), {'status_code': status})()


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_is_permanent_classification():
    assert rb._is_permanent(_FakeHTTPError(404)) is True
    assert rb._is_permanent(_FakeHTTPError(422)) is True
    assert rb._is_permanent(_FakeHTTPError(500)) is False
    assert rb._is_permanent(RuntimeError('conn refused')) is False


def test_4xx_dropped_immediately_not_retried():
    calls = []

    def doomed():
        calls.append(time.monotonic())
        raise _FakeHTTPError(404)

    rb._enqueue('test-4xx', doomed)
    assert _wait_for(lambda: 'test-4xx' not in rb._queue)
    time.sleep(0.3)                    # would retry here under the old logic
    assert len(calls) == 1             # rejected once, never retried


def test_doomed_entry_does_not_block_healthy_pushes():
    done = threading.Event()

    def doomed():
        raise RuntimeError('relay unreachable')   # transient -> backoff

    def healthy():
        done.set()

    rb._enqueue('test-doomed', doomed)
    rb._enqueue('test-healthy', healthy)
    # Under the old worker, doomed slept 1s+2s+... IN the loop before healthy
    # ever ran. Now healthy must complete while doomed is still backing off.
    assert done.wait(2.0), 'healthy push starved behind a backing-off entry'
    # cleanup: silence the doomed entry so it stops retrying during the run
    with rb._queue_lock:
        rb._queue.pop('test-doomed', None)
