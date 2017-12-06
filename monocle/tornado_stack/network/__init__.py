# -*- coding: utf-8 -*-
#
# by Steven Hazel

import errno
import socket

try:
    import ssl  # Python 2.6+
except ImportError:
    ssl = None

from tornado.iostream import IOStream, SSLIOStream

from monocle import _o, launch
from monocle.callback import Callback
from monocle.stack.network import Connection
from monocle.tornado_stack.eventloop import evlp
from monocle.util import monkeypatch


# monkeypatch IOStream to provide a reactive read
@monkeypatch(IOStream)
def __init__(orig_method, self, *a, **k):
    orig_method(self, *a, **k)
    self._read_some = None


@monkeypatch(IOStream)
def _read_from_buffer(orig_method, self, *a, **k):
    if self._read_some is not None:
        if self._read_buffer_size > 0:
            callback = self._read_callback
            self._read_callback = None
            self._read_some = None
            self._run_callback(callback, self._consume(self._read_buffer_size))
            return True
    else:
        return orig_method(self, *a, **k)


@monkeypatch(IOStream)
def read_some(orig_method, self, callback):
    """Call callback when we read some bytes."""
    from tornado import stack_context
    assert not self._read_callback, "Already reading"
    self._read_some = True
    self._read_callback = stack_context.wrap(callback)
    while True:
        if self._read_from_buffer():
            return
        self._check_closed()
        if self._read_to_buffer() == 0:
            break
    self._add_io_state(self.io_loop.READ)


class _Connection(object):

    def __init__(self, iostream):
        self.iostream = iostream
        self.iostream.set_close_callback(self._close_called)
        self.read_cb = None
        self.connect_cb = None

    def attach(self, connection):
        self._write_flushed = connection._write_flushed
        self._closed = connection._closed

    def connect(self, address):
        cb = Callback()
        self.connect_cb = cb
        self.iostream.connect(address, self._connect_complete)
        return cb

    def read_some(self):
        cb = Callback()
        self.read_cb = cb
        self.iostream.read_some(self._read_complete)
        return cb

    def read(self, size):
        cb = Callback()
        self.read_cb = cb
        self.iostream.read_bytes(size, self._read_complete)
        return cb

    def read_until(self, s):
        cb = Callback()
        self.read_cb = cb
        self.iostream.read_until(s, self._read_complete)
        return cb

    def _connect_complete(self, result=None):
        cb = self.connect_cb
        self.connect_cb = None
        if cb:
            cb(result)

    def _read_complete(self, result):
        cb = self.read_cb
        self.read_cb = None
        cb(result)

    def _close_called(self, reason=None):
        # XXX: get a real reason from Tornado
        if reason is None:
            reason = IOError("Connection closed")
        self._closed(reason)

    # functions to support the StackConnection interface

    def write(self, data):
        self.iostream.write(data, self._write_flushed)

    def resume(self):
        self.iostream.resume()

    def reading(self):
        return self.iostream.reading()

    def closed(self):
        return self.iostream.closed()

    def disconnect(self):
        self.iostream.close()


# A Tornado-specific connection which passes through to Tornado's read functions
class TornadoConnection(Connection):

    def read_some(self):
        self._check_reading()
        cb = self._stack_conn.read_some()
        self._queue_timeout(cb)
        return cb

    def read(self, size):
        self._check_reading()
        cb = self._stack_conn.read(size)
        self._queue_timeout(cb)
        return cb

    def read_until(self, s):
        self._check_reading()
        cb = self._stack_conn.read_until(s)
        self._queue_timeout(cb)
        return cb


class Service(object):
    def __init__(self, handler, port, bindaddr="", backlog=128):
        @_o
        def _handler(s):
            try:
                yield launch(handler, s)
            finally:
                s.close()
        self.handler = _handler
        self.port = port
        self.bindaddr = bindaddr
        self.backlog = backlog
        self.ssl_options = None
        self._evlp = None
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setblocking(0)
        self._sock.bind((self.bindaddr, self.port))
        self._sock.listen(self.backlog)

    def _connection_ready(self, fd, events):
        while True:
            try:
                s, address = self._sock.accept()
            except socket.error as e:
                if e[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                return
            iostream = self._make_iostream(s)
            if not iostream:
                continue
            connection = TornadoConnection(_Connection(iostream))
            connection._stack_conn.attach(connection)
            self.handler(connection)

    def _add(self, evlp):
        self._evlp = evlp
        self._evlp._add_handler(self._sock.fileno(),
                                self._connection_ready,
                                self._evlp.READ)

    def _make_iostream(self, s):
        return IOStream(s)

    @_o
    def stop(self):
        if self._evlp:
            self._evlp._remove_handler(self._sock.fileno())


class SSLService(Service):

    def __init__(self, handler, port, bindaddr="", backlog=128,
                 ssl_options=None):
        if ssl_options is None:
            ssl_options = {}
        Service.__init__(self, handler, port, bindaddr, backlog)
        self.ssl_options = ssl_options

    def _make_iostream(self, s):
        assert ssl, "Python 2.6+ and OpenSSL required for SSL"
        try:
            s = ssl.wrap_socket(s,
                                server_side=True,
                                do_handshake_on_connect=False,
                                **self.ssl_options)
        except ssl.SSLError as err:
            if err.args[0] == ssl.SSL_ERROR_EOF:
                s.close()
                return
            else:
                raise
        except socket.error as err:
            if err.args[0] == errno.ECONNABORTED:
                s.close()
                return
            else:
                raise
        return SSLIOStream(s)


class Client(TornadoConnection):
    def __init__(self, *args, **kwargs):
        Connection.__init__(self, *args, **kwargs)
        self.ssl_options = None

    @_o
    def connect(self, host, port):
        s = socket.socket()
        iostream = self._make_iostream(s)
        self._stack_conn = _Connection(iostream)
        self._stack_conn.attach(self)
        self._stack_conn.connect((host, port))

        if self.timeout is not None:
            self._queue_timeout(self._stack_conn.connect_cb)

        yield self._stack_conn.connect_cb

    def _make_iostream(self, s):
        return IOStream(s)


class SSLClient(Client):

    def __init__(self, ssl_options=None):
        if ssl_options is None:
            ssl_options = {}
        Connection.__init__(self)
        self.ssl_options = ssl_options

    def _make_iostream(self, s):
        return SSLIOStream(s, ssl_options=self.ssl_options)


def add_service(service, evlp=evlp):
    return service._add(evlp)
