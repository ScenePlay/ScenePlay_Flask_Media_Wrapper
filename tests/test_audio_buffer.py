"""_StreamBuffer: the capture-side backlog that bridges relay outages."""
import threading
import time

from relay_audio_stream import _StreamBuffer


def test_fifo_order():
    buf = _StreamBuffer(max_bytes=1000)
    for b in (b'aa', b'bb', b'cc'):
        buf.push(b)
    assert [buf.pop(0.01) for _ in range(3)] == [b'aa', b'bb', b'cc']


def test_pop_timeout_returns_none():
    buf = _StreamBuffer(max_bytes=1000)
    t0 = time.monotonic()
    assert buf.pop(0.05) is None
    assert time.monotonic() - t0 >= 0.04


def test_overflow_drops_oldest():
    buf = _StreamBuffer(max_bytes=10)
    buf.push(b'11111')       # 5 bytes
    buf.push(b'22222')       # 10 bytes total
    buf.push(b'33333')       # over cap -> drop oldest
    assert buf.pop(0.01) == b'22222'
    assert buf.pop(0.01) == b'33333'
    assert buf.pop(0.01) is None


def test_overflow_always_keeps_newest():
    buf = _StreamBuffer(max_bytes=4)
    buf.push(b'oldpayload')
    buf.push(b'newpayload')  # both exceed cap alone; newest must survive
    assert buf.pop(0.01) == b'newpayload'


def test_close_and_done():
    buf = _StreamBuffer(max_bytes=100)
    buf.push(b'tail')
    buf.close()
    assert not buf.done()            # closed but not drained
    assert buf.pop(0.01) == b'tail'  # drains remaining data after close
    assert buf.done()
    assert buf.pop(0.01) is None


def test_close_wakes_blocked_pop():
    buf = _StreamBuffer(max_bytes=100)
    result = {}
    def popper():
        result['v'] = buf.pop(timeout=5)
    t = threading.Thread(target=popper)
    t.start()
    time.sleep(0.05)
    buf.close()
    t.join(timeout=1)
    assert not t.is_alive()          # close() must not leave pop() waiting
    assert result['v'] is None


def test_producer_consumer_threads():
    buf = _StreamBuffer(max_bytes=1_000_000)
    chunks = [bytes([i % 256]) * 100 for i in range(200)]
    def producer():
        for c in chunks:
            buf.push(c)
        buf.close()
    threading.Thread(target=producer).start()
    got = []
    while True:
        c = buf.pop(0.5)
        if c is None and buf.done():
            break
        if c is not None:
            got.append(c)
    assert got == chunks
