import sys
import thread

from monocle import launch

# prefer fast reactors
# FIXME: this should optionally refuse to use slow ones
if 'twisted.internet.reactor' not in sys.modules:
    try:
        from twisted.internet import epollreactor
        epollreactor.install()
    except Exception:
        try:
            from twisted.internet import kqreactor
            kqreactor.install()
        except Exception:
            try:
                from twisted.internet import pollreactor
                pollreactor.install()
            except Exception:
                pass

from twisted.internet import reactor
try:
    from twisted.internet.error import ReactorNotRunning
except ImportError:
    ReactorNotRunning = RuntimeError


# thanks to Peter Norvig
def singleton(object, message="singleton class already instantiated",
              instantiated=[]):
    """
    Raise an exception if an object of this class has been instantiated before.
    """
    assert object.__class__ not in instantiated, message
    instantiated.append(object.__class__)


class Task(object):
    def __init__(self, df):
        self._df = df

    def cancel(self):
        self._df.cancel()


class EventLoop(object):
    def __init__(self):
        singleton(self, "Twisted can only have one EventLoop (reactor)")
        self._halted = False
        self._thread_ident = thread.get_ident()

    def queue_task(self, delay, callable, *args, **kw):
        if thread.get_ident() != self._thread_ident:
            reactor.callFromThread(reactor.callLater, delay, launch, callable, *args, **kw)
        else:
            df = reactor.callLater(delay, launch, callable, *args, **kw)
            return Task(df)

    def run(self):
        if not self._halted:
            self._thread_ident = thread.get_ident()
            reactor.run()

    def halt(self):
        try:
            reactor.stop()
        except ReactorNotRunning:
            self._halted = True
            pass

evlp = EventLoop()
queue_task = evlp.queue_task
run = evlp.run
halt = evlp.halt
