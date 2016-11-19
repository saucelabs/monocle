import time
from monocle import _o, util
from o_test import test


@test
@_o
def test_next_tick():
    yield util.next_tick()


@test
@_o
def test_immediate():
    res = yield util.immediate(123)
    assert res == 123


@test
@_o
def test_delayed():
    t = time.time()
    res = yield util.delayed(0.01, 456)
    dt = time.time() - t
    assert 0.005 < dt < 0.015
    assert res == 456


@test
@_o
def test_sleep():
    t = time.time()
    yield util.sleep(0.01)
    dt = time.time() - t
    assert 0.005 < dt < 0.015
