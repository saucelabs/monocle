# -*- coding: utf-8 -*-
#
# by Steven Hazel

from __future__ import print_function
import sys
import os
import logging
import cPickle as pickle
from multiprocessing import Process
from functools import partial
from collections import deque

import monocle
from monocle import _o, Return, launch
from monocle.util import sleep
from monocle.core import Callback
from monocle.experimental import Channel
from monocle.stack import eventloop
import monocle.stack.network as n
from monocle.stack.network import add_service, Client, ConnectionLost

log = logging.getLogger("monocle.stack.multiprocess")


class SocketChannel(object):
    def __init__(self, conn):
        self.conn = conn

    @_o
    def send(self, value):
        p = pickle.dumps(value)
        yield self.conn.write(str(len(p)))
        yield self.conn.write("\n")
        yield self.conn.write(p)

    @_o
    def recv(self):
        l = yield self.conn.readline()
        l = int(l)
        p = yield self.conn.read(l)
        value = pickle.loads(p)
        yield Return(value)


class SplitChannel(object):
    def __init__(self, chan, subchans):
        self.chan = chan
        self.channels = dict([(subchan, Channel(bufsize=float("inf")))
                              for subchan in subchans])
        launch(self._receiver)

    @_o
    def _receiver(self):
        while True:
            try:
                value = yield self.chan.recv()
                yield self.channels[value['subchan']].send(value)
            except ConnectionLost:
                break

    @_o
    def send(self, subchan, value):
        yield self.chan.send({'subchan': subchan,
                              'content': value})

    @_o
    def recv(self, subchan):
        value = yield self.channels[subchan].recv()
        yield Return(value['content'])


class SubChannel(object):
    def __init__(self, split_chan, name):
        self.split_chan = split_chan
        self.name = name

    @_o
    def send(self, value):
        yield self.split_chan.send(self.name, value)

    @_o
    def recv(self):
        value = yield self.split_chan.recv(self.name)
        yield Return(value)


def make_subchannels(chan, subchans):
    splitchan = SplitChannel(chan, subchans)
    return [SubChannel(splitchan, name) for name in subchans]


def launch_proc(target, *args, **kwargs):
    def proc_wrapper():
        eventloop.queue_task(0, target, *args, **kwargs)
        eventloop.run()
    p = Process(target=proc_wrapper)
    p.start()
    return p


@_o
def get_conn(cb, conn):
    cb(conn)
    while not conn.is_closed():
        yield sleep(1)


@_o
def _subproc_wrapper(port, target, *args, **kwargs):
    try:
        client = Client()
        while True:
            try:
                yield client.connect('127.0.0.1', port)
                break
            except Exception as e:
                print("failed to connect to monocle multiprocess parent on port", port, type(e), str(e))
                yield sleep(1)
        chan = SocketChannel(client)
        yield target(chan, *args, **kwargs)
    finally:
        client.close()


@_o
def launch_proc_with_sockets(target, *args, **kwargs):
    port = 7051  # FIXME -- shouldn't be hardcoded
    p = launch_proc(_subproc_wrapper, port, target, *args, **kwargs)
    cb = Callback()
    get_chan_service = partial(get_conn, cb)
    service = Service(get_chan_service, port, bindaddr="127.0.0.1", backlog=1)
    service._add()
    conn = yield cb
    yield service.stop()
    chan = SocketChannel(conn)
    yield Return(p, chan)


@_o
def run_in_proc(target, *args, **kwargs):
    @_o
    def wrapper(chan):
        r = yield target(*args, **kwargs)
        yield chan.send(r)
        eventloop.halt()
    p, chan = yield launch_proc_with_sockets(wrapper)
    r = yield chan.recv()
    p.join()
    yield Return(r)


if monocle._stack_name == 'twisted':
    from monocle.twisted_stack.network import *
