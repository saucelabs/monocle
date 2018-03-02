import sys
import thread
import signal

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
        self._sig_handlers = {}

        # queue this up as early as possible, so that signal handlers get
        # reinstalled just after the reactor starts up
        self.queue_task(0, self._reinstall_signal_handlers)

    def _preserve_sig_handlers(self):
        """ Obnoxiously, twisted overwrites any event handlers with its own when
        its reactor starts up. Nobody wants that. To make twisted work more like
        other stacks, we preserve any non-default signal handlers so that they
        can be reinstalled after the reactor has started. """
        default_handlers = {None, signal.SIG_DFL, signal.SIG_IGN,
                            signal.default_int_handler}
        i = 1
        while True:
            try:
                handler = signal.getsignal(i)
                if handler not in default_handlers:
                    self._sig_handlers[i] = handler
            except ValueError:
                break
            i += 1

    def _reinstall_signal_handlers(self):
        """ Reinstall preserved signal handlers """
        for sig, handler in self._sig_handlers.iteritems():
            signal.signal(sig, handler)

    def queue_task(self, delay, callable, *args, **kw):
        if thread.get_ident() != self._thread_ident:
            reactor.callFromThread(reactor.callLater,
                                   delay, launch, callable, *args, **kw)
        else:
            df = reactor.callLater(delay, launch, callable, *args, **kw)
            return Task(df)

    def run(self):
        if not self._halted:
            self._thread_ident = thread.get_ident()

            # preserve signal handlers just before reactor startup; a task has
            # already been queued up to reinstall them as quickly as possible
            self._preserve_sig_handlers()

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
