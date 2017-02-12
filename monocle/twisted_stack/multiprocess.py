from multiprocessing import Pipe

from monocle.stack.multiprocess import launch_proc

log = logging.getLogger(__name__)


class PipeForTwisted(object):
    def __init__(self, pipe):
        self.pipe = pipe
        self.callback = Callback()

    def doRead(self):
        self.callback((False, None))

    def fileno(self):
        return self.pipe.fileno()

    def connectionLost(self, reason):
        self.callback((True, reason))

    def logPrefix(self):
        return "Pipe"

    def doWrite(self):
        self.callback((False, None))


class PipeChannel(object):
    def __init__(self, pipe):
        self.pipe = pipe

    @_o
    def send(self, value):
        w = PipeForTwisted(self.pipe)
        eventloop.reactor.addWriter(w)
        lost, reason = yield w.callback
        eventloop.reactor.removeWriter(w)

        if lost:
            raise Exception("connection lost: %s" % reason)
        self.pipe.send(value)

    @_o
    def recv(self):
        r = PipeForTwisted(self.pipe)
        eventloop.reactor.addReader(r)
        lost, reason = yield r.callback
        eventloop.reactor.removeReader(r)

        if lost:
            raise Exception("connection lost: %s" % reason)
        yield Return(self.pipe.recv())


def launch_proc_with_pipes(target, *args, **kwargs):
    child, parent = Pipe()
    pc = PipeChannel(parent)
    p = launch_proc(target, pc, *args, **kwargs)
    cc = PipeChannel(child)
    return p, cc
