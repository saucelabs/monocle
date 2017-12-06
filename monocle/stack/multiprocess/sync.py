from __future__ import print_function
# eventually this will be part of monocle

import select
import logging
import time
import socket
import cPickle as pickle
from multiprocessing import Process, Pipe
from functools import partial

try:
    import errno
except ImportError:
    errno = None
EINTR = getattr(errno, 'EINTR', 4)

import monocle
from monocle import _o, Return, launch
from monocle.core import Callback
from monocle.stack.network import add_service, Client
from monocle.stack.multiprocess import PipeChannel, SocketChannel, get_conn, make_subchannels, Service

log = logging.getLogger("monocle.stack.multiprocess.sync")
subproc_formatter = logging.Formatter("%(asctime)s - %(name)s - %(message)s")


@_o
def log_receive(chan):
    root = logging.getLogger('')
    while True:
        levelno, msg = yield chan.recv()
        # python's logging module is ridiculous
        for h in root.handlers:
            h.old_formatter = h.formatter
            h.setFormatter(subproc_formatter)
        log.log(levelno, msg)
        for h in root.handlers:
            h.setFormatter(h.old_formatter)


# using sockets
class SyncSockChannel(object):
    def __init__(self, sock):
        self.sock = sock

    def _sendall(self, data):
        while data:
            try:
                r = self.sock.send(data)
            except socket.error as e:
                if e.args[0] == EINTR:
                    continue
                raise
            data = data[r:]

    def _recv(self, count):
        result = ""
        while count:
            try:
                data = self.sock.recv(min(count, 4096))
            except socket.error as e:
                if e.args[0] == EINTR:
                    continue
                raise
            else:
                count -= len(data)
                result += data
        return result

    def send(self, value):
        p = pickle.dumps(value)
        self._sendall(str(len(p)))
        self._sendall("\n")
        self._sendall(p)

    def recv(self):
        l = ""
        while True:
            x = self._recv(1)
            if x == "\n":
                break
            l += x
        l = int(l)
        p = self._recv(l)
        try:
            value = pickle.loads(p)
        except Exception:
            log.exception("Error loading pickle: %s", p)
            raise
        return value

    def poll(self):
        r, w, x = select.select([self.sock], [], [self.sock], 0)
        if r + x:
            log.info("poll triggered")
            return True
        else:
            return False


class SockChannelHandler(logging.Handler):
    def __init__(self, sock):
        logging.Handler.__init__(self)

        self.sock = sock

    def setFormatter(self, formatter):
        self.formatter = formatter

    def send(self, record):
        # ow, python logging is painful to work with
        if record.args and isinstance(record.args, tuple):
            args = record.args
            new_args = []
            for arg in args:
                if isinstance(arg, str):
                    new_args.append(arg.decode('utf-8', 'replace'))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        self.sock.send((record.levelno, self.formatter.format(record)))

    def emit(self, record):
        try:
            self.send(record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self):
        logging.Handler.close(self)


class SyncSockSubchan(object):
    def __init__(self, chan, subchan):
        self.chan = chan
        self.subchan = subchan

    def send(self, value):
        return self.chan.send({'subchan': self.subchan,
                               'content': value})

    def recv(self):
        value = self.chan.recv()
        assert value['subchan'] == self.subchan
        return value['content']

    def poll(self):
        return self.chan.poll()


def _wrapper_with_sockets(target, port, *args, **kwargs):
    sock = socket.socket()
    while True:
        try:
            sock.connect(('127.0.0.1', port))
        except Exception as e:
            print("failed to connect to monocle multiprocess parent on port", port, type(e), str(e))
            time.sleep(0.2)
            sock.close()
            sock = socket.socket()
        else:
            break
    try:
        formatter = logging.Formatter("%(asctime)s - %(name)s[%(funcName)s:"
                                      "%(lineno)s] - %(levelname)s - %(message)s")
        chan = SyncSockChannel(sock)
        handler = SockChannelHandler(SyncSockSubchan(chan, 'log'))
        handler.setFormatter(formatter)
        root = logging.getLogger('')
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)

        target(SyncSockSubchan(chan, 'main'), *args, **kwargs)
    finally:
        log.info("subprocess finished, closing monocle socket")
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()


@_o
def launch_proc_with_sockets(target, port, *args, **kwargs):
    args = [target, port] + list(args)
    p = Process(target=_wrapper_with_sockets, args=args, kwargs=kwargs)
    p.start()
    cb = Callback()
    get_chan_service = partial(get_conn, cb)
    service = Service(get_chan_service, port, bindaddr="127.0.0.1", backlog=1)
    service._add()
    conn = yield cb
    yield service.stop()
    chan = SocketChannel(conn)
    main_chan, log_chan = make_subchannels(chan, ['main', 'log'])
    launch(log_receive, log_chan)
    yield Return(p, main_chan)


# using pipes
class PipeHandler(logging.Handler):
    def __init__(self, pipe):
        logging.Handler.__init__(self)

        self.pipe = pipe

    def setFormatter(self, formatter):
        self.formatter = formatter

    def send(self, record):
        # ow, python logging is painful to work with
        if record.args and isinstance(record.args, tuple):
            args = record.args
            new_args = []
            for arg in args:
                if isinstance(arg, str):
                    new_args.append(arg.decode('utf-8', 'replace'))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        self.pipe.send(self.formatter.format(record))

    def emit(self, record):
        try:
            self.send(record)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self):
        logging.Handler.close(self)


def _wrapper_with_pipes(target, log_pipe, pipe, *args, **kwargs):
    formatter = logging.Formatter("%(asctime)s - %(name)s[%(funcName)s:"
                                  "%(lineno)s] - %(levelname)s - %(message)s")
    pipehandler = PipeHandler(log_pipe)
    pipehandler.setFormatter(formatter)
    target(pipe, *args, **kwargs)


def launch_proc_with_pipes(target, *args, **kwargs):
    log_child, log_parent = Pipe()
    child, parent = Pipe()
    args = [target, log_child, child] + list(args)
    p = Process(target=_wrapper_with_pipes, args=args, kwargs=kwargs)
    p.start()
    launch(log_receive, PipeChannel(log_parent))
    return p, parent
