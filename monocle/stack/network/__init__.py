import monocle
from monocle import _o, Return
from monocle.callback import Callback, defer
from monocle.stack import eventloop as evlp


class ConnectionLost(Exception):
    pass


class Connection(object):
    """
    Connection takes a stack_conn, which should have this interface:

    def write(data):
        writes the data

    read_cb: callback which is called when a read completes
    connect_cb: callback which is called when the connection completes

    def resume():
        resumes reading

    def reading():
        returns a boolean indicating the current reading state

    def closed():
        returns a boolean indicating the current closed state

    def disconnect():
        closes the connection

    if the read/read_until implementations here are used:

    buffer: string buffer which grows before read_cb is called
    """
    def __init__(self, stack_conn=None):
        self._stack_conn = stack_conn
        self.writing = False
        self.flush_cb = Callback()
        self.write_encoding = 'utf-8'
        self.timeout = None
        self._current_timeout = None

    def _time_out(self, instigating_cb, timeout):
        self._current_timeout = None
        if hasattr(instigating_cb, 'result'):
            return

        current_cbs = [self._stack_conn.read_cb,
                       self.flush_cb,
                       self._stack_conn.connect_cb]
        self._stack_conn.read_cb = None
        self.flush_cb = None
        self._stack_conn.connect_cb = None
        self._stack_conn.disconnect()
        for cb in current_cbs:
            if cb and not hasattr(cb, 'result'):
                cb(ConnectionLost("connection timed out after %s seconds" %
                                  timeout))

    def _queue_timeout(self, cb):
        if self.timeout is not None:
            if self._current_timeout:
                self._current_timeout.cancel()
            self._current_timeout = evlp.queue_task(self.timeout,
                                                    self._time_out,
                                                    cb,
                                                    self.timeout)

    @_o
    def read_some(self):
        self._check_reading()

        if not self._stack_conn.buffer:
            self._check_closed()
            self._stack_conn.resume()
            self._queue_timeout(self._stack_conn.read_cb)
            yield self._stack_conn.read_cb
        tmp = self._stack_conn.buffer
        self._stack_conn.buffer = ""
        yield Return(tmp)

    @_o
    def read(self, size):
        self._check_reading()

        while len(self._stack_conn.buffer) < size:
            self._check_closed()
            self._stack_conn.resume()
            self._queue_timeout(self._stack_conn.read_cb)
            yield self._stack_conn.read_cb
        tmp = self._stack_conn.buffer[:size]
        self._stack_conn.buffer = self._stack_conn.buffer[size:]
        yield Return(tmp)

    @_o
    def read_until(self, s):
        self._check_reading()

        while True:
            size = self._stack_conn.buffer.find(s)
            if size != -1:
                size += len(s)
                break
            self._check_closed()
            self._stack_conn.resume()
            self._queue_timeout(self._stack_conn.read_cb)
            yield self._stack_conn.read_cb
        tmp = self._stack_conn.buffer[:size]
        self._stack_conn.buffer = self._stack_conn.buffer[size:]
        yield Return(tmp)

    def readline(self):
        return self.read_until("\n")

    def write(self, data):
        if isinstance(data, unicode):
            data = data.encode(self.write_encoding)
        self._check_closed()
        if data == "":
            # twisted won't ever tell us we flushed writing ""
            return defer(None)
        self.writing = True
        self._stack_conn.write(data)
        cb = self.flush()
        self._queue_timeout(cb)
        return cb

    def _write_flushed(self, result=None):
        self.writing = False
        cb = self.flush_cb
        self.flush_cb = Callback()
        if cb:
            cb(result)

    def flush(self):
        self._check_closed()
        cb = self.flush_cb
        if not self.writing:
            self._write_flushed()
        return cb

    def _closed(self, reason):
        if self._current_timeout:
            self._current_timeout.cancel()
            self._current_timeout = None
        cl = ConnectionLost(str(reason))
        cl.original = reason
        if self._stack_conn.connect_cb:
            cb = self._stack_conn.connect_cb
            self._stack_conn.connect_cb = None
            cb(cl)
        self._write_flushed(cl)
        if self._stack_conn.read_cb:
            cb = self._stack_conn.read_cb
            self._stack_conn.read_cb = None
            cb(cl)

    def close(self):
        self._stack_conn.disconnect()

    def _check_reading(self):
        if self._stack_conn.reading():
            raise IOError("Already reading")

    def _check_closed(self):
        if self._stack_conn.closed():
            raise IOError("Stream is closed")

    def is_closed(self):
        return self._stack_conn.closed()


if monocle._stack_name == 'twisted':
    from monocle.twisted_stack.network import *
elif monocle._stack_name == 'tornado':
    from monocle.tornado_stack.network import *
elif monocle._stack_name == 'asyncore':
    from monocle.asyncore_stack.network import *
elif not monocle._stack_name:
    raise ImportError(
        "Could not import stack.\n"
        "Ensure you have called monocle.init()\n"
        "or defined MONOCLE_STACK=<stack> in the environment")
