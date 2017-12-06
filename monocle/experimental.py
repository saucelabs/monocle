# -*- coding: utf-8 -*-
#
# by Steven Hazel

from __future__ import absolute_import
from collections import deque
from .callback import Callback

from monocle.stack.eventloop import queue_task
from monocle import _o, Return


# Go-style channels
class Channel(object):
    def __init__(self, bufsize=0):
        self.bufsize = bufsize
        self._msgs = deque()
        self._recv_cbs = deque()
        self._send_cbs = deque()

    @_o
    def send(self, value):
        if self._recv_cbs:
            # if there are receivers waiting, send to the first one
            rcb = self._recv_cbs.popleft()
            queue_task(0, rcb, value)
        elif len(self._msgs) < self.bufsize:
            # if there's available buffer, use that
            self._msgs.append(value)
        else:
            # otherwise, wait for a receiver
            cb = Callback()
            self._send_cbs.append(cb)
            rcb = yield cb
            queue_task(0, rcb, value)

    @_o
    def recv(self):
        # if there's buffer, read it
        if self._msgs:
            value = self._msgs.popleft()
            yield Return(value)

        # otherwise we need a sender
        rcb = Callback()
        if self._send_cbs:
            # if there are senders waiting, wake up the first one
            cb = self._send_cbs.popleft()
            cb(rcb)
        else:
            # otherwise, wait for a sender
            self._recv_cbs.append(rcb)
        value = yield rcb
        yield Return(value)


# Some ideas from diesel:

# This is really not a very good idea without limiting it to a set of
# cancelable operations...
@_o
def first_of(*a):
    cb = Callback()
    cb.called = False
    for i, c in enumerate(a):
        def cb(result, i=i):
            if isinstance(result, Exception):
                raise result
            if not cb.called:
                cb.called = True
                cb((i, result))
        c.add(cb)
    x, r = yield cb
    yield Return([(True, r) if x == i else None for i in xrange(len(a))])


@_o
def fire(name, value):
    if name in waits:
        cb = waits[name]
        waits.pop(name)
        cb(value)


@_o
def wait(name):
    waits.setdefault(name, Callback())
    r = yield waits[name]
    yield Return(r)

waits = {}
