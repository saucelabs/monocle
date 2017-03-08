# This code is based heavily on inlineCallbacks from Twisted 10.0, see LICENSE.

import sys
import types
import logging
import traceback
import time
import inspect
import os.path
import functools

from callback import Callback, defer

try:
    from twisted.python.failure import Failure as TwistedFailure
    from twisted.internet.defer import Deferred as TwistedDeferred
except ImportError:
    class TwistedFailure:
        pass

    class TwistedDeferred:
        pass

logging.basicConfig(stream=sys.stderr,
                    format="%(message)s")
log = logging.getLogger("monocle")

blocking_warn_threshold = 500  # ms
tracebacks_elide_internals = True


class Return(object):
    def __init__(self, *args):
        # mimic the semantics of the return statement
        if len(args) == 0:
            self.value = None
        elif len(args) == 1:
            self.value = args[0]
        else:
            self.value = args

    def __repr__(self):
        return "<%s.%s object at 0x%x; value: %s>" % (self.__class__.__module__,
                                                      self.__class__.__name__,
                                                      id(self),
                                                      repr(self.value))


class InvalidYieldException(Exception):
    pass


def is_eventloop_stack(stack):
    this_dir = os.path.dirname(__file__)
    for file, line, context, code in stack:
        if (file.startswith(this_dir) and
            file.endswith("eventloop.py") and
            context == 'run'):
            return True
    return False


def format_stack_lines(stack, elide_internals=tracebacks_elide_internals):
    eliding = False
    lines = []
    for file, line, context, code in stack:
        this_file = __file__
        if this_file.endswith('.pyc'):
            this_file = this_file[:-1]
        if not file == this_file or not elide_internals:
            eliding = False
            lines.append("  File %s, line %s, in %s\n    %s" %
                         (file, line, context, code))
        else:
            if not eliding:
                eliding = True
                lines.append("  -- eliding monocle internals --")
    return lines


def format_tb(e, elide_internals=tracebacks_elide_internals):
    s = ""
    for i, (tb, caller_stack) in enumerate(reversed(e._monocle['tracebacks'])):
        lines = tb.split('\n')

        first = lines[0]  # "Traceback (most recent call last)"

        end_offset = -1
        while (end_offset >= -len(lines) and
               not lines[end_offset].startswith('  File ')):
            end_offset -= 1
        end_offset += 2
        last = lines[end_offset]  # Line(s) describing the exception

        caller_stack_lines = []
        if caller_stack and not is_eventloop_stack(caller_stack):
            caller_stack_lines = format_stack_lines(caller_stack, elide_internals)

        # 3 because of the "Traceback (most recent call last)" line,
        # plus two lines describing the g.throw that got us the
        # exception
        lines = caller_stack_lines + lines[3:end_offset]

        if caller_stack and is_eventloop_stack(caller_stack):
            if i + 1 < len(e._monocle['tracebacks']):
                lines += ["  -- trampolined off eventloop --"]
            else:
                lines += ["  -- trampolined off eventloop, into caller stack --"]
                # the last one is details on how we got called
                if elide_internals:
                    caller_stack = caller_stack[2:]
                lines += format_stack_lines(caller_stack, elide_internals)

        s += "\n" + '\n'.join(lines)
    return first + s + "\n" + last


def _append_traceback(e, tb, caller_stack):
    if not hasattr(e, "_monocle"):
        e._monocle = {'tracebacks': []}
    e._monocle['tracebacks'].append((tb, caller_stack))
    return e


def _add_monocle_tb(e, bounceback=False):
    tb = traceback.format_exc()
    caller_stack = None
    if bounceback:
        caller_stack = traceback.extract_stack()

    # if it's not an eventloop stack, the first one we get is
    # comprehensive and future ones are higher up the stack.  if it is
    # an eventloop stack, we need to add it to reconstruct how we got
    # to the first one.
    if (not caller_stack or
        is_eventloop_stack(caller_stack) or
        not hasattr(e, "_monocle")):
        _append_traceback(e, tb, caller_stack)
    return e


def _add_twisted_tb(f):
    tb = f.getTraceback(elideFrameworkCode=tracebacks_elide_internals)
    return _append_traceback(f.value, tb, None)


def _monocle_chain(to_gen, g, callback):
    # This function is complicated by the need to prevent unbounded recursion
    # arising from repeatedly yielding immediately ready callbacks.  This while
    # loop solves that by manually unfolding the recursion.

    while True:
        try:
            # Send the last result back as the result of the yield expression.
            start = time.time()
            try:
                if isinstance(to_gen, Exception):
                    from_gen = g.throw(type(to_gen), to_gen)
                elif isinstance(to_gen, TwistedFailure):
                    from_gen = g.throw(to_gen.type, to_gen.value, to_gen.tb)
                else:
                    from_gen = g.send(to_gen)
            finally:
                duration = (time.time() - start) * 1000
                if duration > blocking_warn_threshold:
                    if inspect.isframe(g.gi_frame):
                        fi = inspect.getframeinfo(g.gi_frame)
                        log.warn(
                            "oroutine '%s' blocked for %dms before %s:%s", g.__name__, duration, fi.filename, fi.lineno)
                    else:
                        log.warn(
                            "oroutine '%s' blocked for %dms", g.__name__, duration)
        except StopIteration:
            # "return" statement (or fell off the end of the generator)
            from_gen = Return()
        except Exception, e:
            callback(_add_monocle_tb(e, bounceback=(e == to_gen)))
            return callback

        if isinstance(from_gen, Return):
            try:
                g.close()
            except Exception, e:
                callback(_add_monocle_tb(e))
            else:
                callback(from_gen.value)
            return callback
        elif not isinstance(from_gen, Callback):
            if isinstance(from_gen, TwistedDeferred):
                cb = Callback()
                from_gen.addCallbacks(cb, lambda f: cb(_add_twisted_tb(f)))
                from_gen = cb
            else:
                e = InvalidYieldException(
                    "Unexpected value '%s' of type '%s' yielded from o-routine '%s'.  "
                    "O-routines can only yield Callback and Return types." % (from_gen, type(from_gen), g))
                return _monocle_chain(e, g, callback)

        if not hasattr(from_gen, 'result'):
            def gotResult(r):
                _monocle_chain(r, g, callback)
            from_gen.add(gotResult)
            return callback

        to_gen = from_gen.result


def maybeCallbackGenerator(f, *args, **kw):
    try:
        result = f(*args, **kw)
    except Exception, e:
        return defer(_add_monocle_tb(e))

    if isinstance(result, types.GeneratorType):
        return _monocle_chain(None, result, Callback())
    elif isinstance(result, Callback):
        return result
    elif isinstance(result, TwistedDeferred):
        cb = Callback()
        result.addCallbacks(cb, lambda f: cb(_add_twisted_tb(f)))
        return cb
    return defer(result)


# @_o
def _o(f):
    """
    monocle helps you write Callback-using code that looks like a regular
    sequential function.  For example::

        @_o
        def foo():
            result = yield makeSomeRequestResultingInCallback()
            print result

    When you call anything that results in a Callback, you can simply yield it;
    your generator will automatically be resumed when the Callback's result is
    available. The generator will be sent the result of the Callback with the
    'send' method on generators, or if the result was a failure, 'throw'.

    Your coroutine-enabled generator will return a Callback object,
    which will result in the return value of the generator (or will
    fail with a failure object if your generator raises an unhandled
    exception). Note that you can't use "return result" to return a
    value; use "yield Return(result)" instead. Falling off the end of
    the generator, or simply using "return" will cause the Callback to
    have a result of None.  Yielding anything other and a Callback or
    a Return is not allowed, and will raise an exception.

    The Callback returned from your generator will call back with an
    exception if your generator raised an exception::

        @_o
        def foo():
            result = yield makeSomeRequestResultingInCallback()
            if result == 'foo':
                # this will become the result of the Callback
                yield Return('success')
            else:
                # this too
                raise Exception('fail')
    """
    @functools.wraps(f)
    def unwindGenerator(*args, **kwargs):
        return maybeCallbackGenerator(f, *args, **kwargs)
    return unwindGenerator
o = _o


def log_exception(msg="", elide_internals=tracebacks_elide_internals):
    e = sys.exc_info()[1]

    if hasattr(e, '_monocle'):
        log.error("%s\n%s", msg, format_tb(e, elide_internals=elide_internals))
    else:
        log.exception(msg)


@_o
def launch(oroutine, *args, **kwargs):
    try:
        cb = oroutine(*args, **kwargs)
        if not isinstance(cb, (Callback, TwistedDeferred)):
            yield Return(cb)

        r = yield cb
        yield Return(r)
    except GeneratorExit:
        raise
    except Exception:
        log_exception(elide_internals=kwargs.get('elide_internals',
                                                 tracebacks_elide_internals))
