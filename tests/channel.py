from __future__ import print_function
from collections import deque

import monocle
from monocle import _o
from monocle.experimental import Channel
from o_test import test


@test
@_o
def test_send_recv():
    ch = Channel(bufsize=2)
    for x in range(2):
        yield ch.send('ok%s' % x)
    for x in range(2):
        r = yield ch.recv()
        assert r == 'ok%s' % x


@_o
def sendxs(ch, xs):
    print("in sendxs")
    for x in xs:
        yield ch.send(x)
    print("leaving sendxs")


@_o
def recvxs(ch, xs):
    print("in recvxs")
    for x in xs:
        y = yield ch.recv()
        assert y == x, "%s != %s" % (y, x)
    print("leaving recvxs")


@test
@_o
def test_buffers_oneway():
    for i in xrange(10):
        ch = Channel(i)
        xs = range(10000)
        sendxs(ch, xs)
        yield recvxs(ch, xs)


@_o
def chat1(ch1, ch2, xs):
    print("in chat1")
    for x in xs:
        yield ch1.send(x)
        yield ch2.recv()
    print("leaving chat1")


@_o
def chat2(ch1, ch2, xs):
    print("in chat2")
    for x in xs:
        y = yield ch1.recv()
        assert y == x, "%s != %s" % (y, x)
        yield ch2.send(x)
    print("leaving chat2")


@test
@_o
def test_buffers_twoway():
    for i in xrange(10):
        ch1 = Channel(i)
        ch2 = Channel(i)
        xs = range(10000)
        chat1(ch1, ch2, xs)
        yield chat2(ch1, ch2, xs)


@_o
def try_pattern(pattern):
    # s = start send, r = start recv, R = wait for a recv, S = wait for a send
    print("in try_pattern")
    assert (pattern.count("s") == pattern.count("S") ==
            pattern.count("r") == pattern.count("R"))
    print("assert passed")
    cs = 0
    cr = 0
    scbs = deque()
    rcbs = deque()
    ch = Channel()

    for c in pattern:
        if c == "s":
            print("starting send")
            scbs.append(ch.send(cs))
            cs += 1
            print("started send")
        elif c == "S":
            print("waiting for send")
            yield scbs.popleft()
            print("done waiting for send")
        elif c == "r":
            print("starting recv")
            rcbs.append(ch.recv())
            print("started recv")
        elif c == "R":
            print("waiting for recv")
            x = yield rcbs.popleft()
            print("done waiting for recv")
            assert x == cr, "%s != %s" % (x, cr)
            print("post-recv assert passed")
            cr += 1
    print("leaving try_pattern")


@test
@_o
def test_sr():
    yield try_pattern("srSR")


@test
@_o
def test_rs():
    yield try_pattern("rsRS")


@test
@_o
def test_snrn():
    for n in xrange(100):
        yield try_pattern("s" * n +
                          "r" * n +
                          "S" * n +
                          "R" * n)


@test
@_o
def test_rnsn():
    for n in xrange(100):
        yield try_pattern("r" * n +
                          "s" * n +
                          "R" * n +
                          "S" * n)


@test
@_o
def test_ssrsrr():
    yield try_pattern("ssrsrrSSRSRR")


@test
@_o
def test_ssrsrr_weirdwait():
    yield try_pattern("ssrsrrRSRSRS")


@test
@_o
def test_rrsrss():
    yield try_pattern("rrsrssRRSRSS")
