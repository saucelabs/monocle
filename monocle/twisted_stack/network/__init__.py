# -*- coding: utf-8 -*-
#
# by Steven Hazel

from monocle.twisted_stack.eventloop import reactor
from twisted.internet.protocol import Factory, Protocol, ClientFactory
from twisted.internet import ssl
from twisted.internet.error import TimeoutError

from monocle import _o, launch
from monocle.callback import Callback
from monocle.stack.network import Connection
from monocle.util import monkeypatch
import twisted
from twisted.protocols.tls import TLSMemoryBIOProtocol

twisted_major_version = int(twisted.__version__.split('.')[0])


# monkeypatch TLSMemoryBIOProtocol to resume reading when necessary for writes
@monkeypatch(TLSMemoryBIOProtocol)
def __init__(orig_method, self, *a, **k):
    orig_method(self, *a, **k)
    self._was_paused = False


def _is_blocked(o):
    if twisted_major_version > 16 or not hasattr(o, '_writeBlockedOnRead'):
        return len(o._appSendBuffer) > 0
    else:
        return o._writeBlockedOnRead


@monkeypatch(TLSMemoryBIOProtocol)
def _write(orig_method, self, bytes):
    was_blocked = _is_blocked(self)
    orig_method(self, bytes)
    if not was_blocked and _is_blocked(self):
        if (self.transport.producer is not None and
            self.transport.producer._producerPaused):
            self._was_paused = True
            self.transport.resumeProducing()


@monkeypatch(TLSMemoryBIOProtocol)
def dataReceived(orig_method, self, bytes):
    was_blocked = _is_blocked(self)
    orig_method(self, bytes)
    if was_blocked and not _is_blocked(self):
        if self._was_paused:
            self.transport.pauseProducing()
            self._was_paused = False


class _Connection(Protocol):
    def __init__(self):
        self.read_cb = None
        self.connect_cb = None

    def attach(self, connection):
        self._write_flushed = connection._write_flushed
        self._closed = connection._closed

    # functions to support Protocol

    def connectionMade(self):
        self.max_buffer_size = 104857600
        self.buffer = ""
        self.transport.pauseProducing()
        if hasattr(self.factory, "handler"):
            connection = Connection(self)
            self.attach(connection)
        self.transport.registerProducer(self, False)
        if hasattr(self.factory, "handler"):
            self.factory.handler(connection)
        if self.connect_cb:
            cb = self.connect_cb
            self.connect_cb = None
            cb(None)

    def dataReceived(self, data):
        self.transport.pauseProducing()
        self.buffer += data
        if len(self.buffer) >= self.max_buffer_size:
            # Reached maximum read buffer size
            self.disconnect()
            return
        read_cb = self.read_cb
        self.read_cb = None
        read_cb(None)

    def connectionLost(self, reason):
        self._closed(reason.value)

    # functions to support IPullProducer

    def resumeProducing(self):
        if self._write_flushed:
            self._write_flushed()

    def stopProducing(self):
        # we just wait for the connection lost event
        pass

    # functions to support the StackConnection interface

    def write(self, data):
        self.transport.write(data)

    def resume(self):
        self.read_cb = Callback()
        self.transport.resumeProducing()

    def reading(self):
        return self.read_cb is not None

    def closed(self):
        return not (self.transport and
                    self.transport.connected and
                    not self.transport.disconnecting)

    def disconnect(self):
        if self.transport:
            self.transport.unregisterProducer()
            self.transport.loseConnection()


class Service(object):
    def __init__(self, handler, port, bindaddr="", backlog=128):
        self.factory = Factory()
        self.factory.protocol = _Connection

        @_o
        def _handler(s):
            try:
                yield launch(handler, s)
            finally:
                s.close()
        self.factory.handler = _handler
        self.port = port
        self.bindaddr = bindaddr
        self.backlog = backlog
        self._twisted_listening_port = None

    def _add(self):
        self._twisted_listening_port = reactor.listenTCP(
            self.port, self.factory,
            backlog=self.backlog,
            interface=self.bindaddr)

    @_o
    def stop(self):
        df = self._twisted_listening_port.stopListening()
        if df:
            yield df


class SSLService(Service):

    def __init__(self, handler, ssl_options, port, bindaddr="", backlog=128):
        Service.__init__(self, handler, port, bindaddr, backlog)
        self.ssl_options = ssl_options

    def _add(self):
        cf = ssl.DefaultOpenSSLContextFactory(self.ssl_options['keyfile'],
                                              self.ssl_options['certfile'])
        self._twisted_listening_port = reactor.listenSSL(
            self.port, self.factory, cf,
            backlog=self.backlog,
            interface=self.bindaddr)


class SSLContextFactory(ssl.ClientContextFactory):

    def __init__(self, ssl_options):
        self.ssl_options = ssl_options

    def getContext(self):
        ctx = ssl.ClientContextFactory.getContext(self)
        if 'certfile' in self.ssl_options:
            ctx.use_certificate_file(self.ssl_options['certfile'])
        if 'keyfile' in self.ssl_options:
            ctx.use_privatekey_file(self.ssl_options['keyfile'])
        return ctx


class Client(Connection):
    def __init__(self, *args, **kwargs):
        Connection.__init__(self, *args, **kwargs)
        self._connection_timeout = "unknown"

    def clientConnectionFailed(self, connector, reason):
        if reason.type == TimeoutError:
            msg = ("connection timed out after %s seconds" %
                   self._connection_timeout)
        else:
            msg = reason.value
        self._closed(msg)

    @_o
    def connect(self, host, port):
        self._connection_timeout = self.timeout
        self._stack_conn = _Connection()
        self._stack_conn.attach(self)
        self._stack_conn.connect_cb = Callback()
        factory = ClientFactory()
        factory.protocol = lambda: self._stack_conn
        factory.clientConnectionFailed = self.clientConnectionFailed
        self._connect_to_reactor(host, port, factory, self._connection_timeout)
        yield self._stack_conn.connect_cb

    def _connect_to_reactor(self, host, port, factory, timeout):
        reactor.connectTCP(host, port, factory, timeout=timeout)


class SSLClient(Client):

    def __init__(self, ssl_options=None):
        if ssl_options is None:
            ssl_options = {}
        Connection.__init__(self)
        self.ssl_options = ssl_options

    def _connect_to_reactor(self, host, port, factory, timeout):
        reactor.connectSSL(host, port, factory,
                           SSLContextFactory(self.ssl_options),
                           timeout=timeout)


def add_service(service):
    return service._add()
