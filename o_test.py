import os
import sys
import time
import traceback
import random
import argparse
import logging
import inspect
from cStringIO import StringIO
from functools import partial, wraps

import monocle
from monocle import _o, Return

root = logging.getLogger('')
root.setLevel(logging.DEBUG)

_tests = []
_fail_count = 1


@_o
def run_test(test, verbose=False):
    if verbose:
        sys.stdout.write(test.__module__ + "." + test.__name__ + " ... ")
        sys.stdout.flush()
    result = {'test': test}
    captured_stdout = ""
    captured_stderr = ""
    try:
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        log = StringIO()
        handlers = []
        while root.handlers:
            handlers.append(root.handlers[0])
            root.removeHandler(root.handlers[0])
        handler = logging.StreamHandler(log)
        root.addHandler(handler)
        try:
            yield test()
        finally:
            captured_stdout = sys.stdout.getvalue()
            captured_stderr = sys.stderr.getvalue()
            captured_log = log.getvalue()
            sys.stdout = real_stdout
            sys.stderr = real_stderr
            root.removeHandler(handler)
            for h in handlers:
                root.addHandler(h)
    except Exception, e:
        if isinstance(e, AssertionError):
            if verbose:
                print "FAIL"
            else:
                sys.stdout.write("F")
            result['type'] = "FAIL"
        else:
            if verbose:
                print "ERROR"
            else:
                sys.stdout.write("E")
            result['type'] = "ERROR"
        result['tb'] = traceback.format_exc()
    else:
        if verbose:
            print "ok"
        else:
            sys.stdout.write(".")
        result['type'] = "SUCCESS"
    sys.stdout.flush()

    result['stdout'] = captured_stdout
    result['stderr'] = captured_stderr
    result['log'] = captured_log
    yield Return(result)


def test(f):
    _tests.append(partial(wraps(f)(run_test), f))
    return f


def tests(cls):
    for name, method in inspect.getmembers(cls, predicate=inspect.ismethod):
        if not name.startswith('test_'):
            continue

        @wraps(method)
        def f(name=name):
            o = cls()
            return getattr(o, name)()
        _tests.append(partial(wraps(f)(run_test), f))
    return cls


@_o
def run(tests, verbose=False):
    global _fail_count

    try:
        #print tests
        results = []
        start_time = time.time()
        for test in tests:
            result = yield test(verbose)
            results.append(result)
        duration = time.time() - start_time
        print
        print "----------------------------------------------------------------------"
        print "Ran %s tests in %.3fs" % (len(tests), duration)
        print
        _fail_count = 0
        for result in results:
            if result['type'] != "SUCCESS":
                _fail_count += 1
                test = result['test']
                print "======================================================================"
                print "%s %s (%s)" % (result['type'],
                                      test.__doc__ or test.__name__,
                                      __file__)
                print "----------------------------------------------------------------------"
                print result['tb']
                if result['stdout']:
                    print "-------------------- >> begin captured stdout << ---------------------"
                    print result['stdout']
                    print "--------------------- >> end captured stdout << ----------------------"
                if result['stderr']:
                    print "-------------------- >> begin captured stderr << ---------------------"
                    print result['stderr']
                    print "--------------------- >> end captured stderr << ----------------------"
                if result['log']:
                    print "-------------------- >> begin captured log << ---------------------"
                    print result['log']
                    print "--------------------- >> end captured log << ----------------------"
        if not _fail_count:
            print "OK"
    finally:
        from monocle.stack import eventloop
        eventloop.halt()


def main(args):
    parser = argparse.ArgumentParser(
        description="runs monocle tests")
    parser.add_argument('--verbose', '-v', action='store_true', default=False,
                        help="verbose mode")
    parser.add_argument('stack', help="monocle stack to use")
    parser.add_argument('paths', nargs=argparse.REMAINDER, help="args for nosetests")
    args = parser.parse_args()

    monocle.init(args.stack)
    from monocle.stack import eventloop

    import rewrite
    hook = rewrite.AssertionRewritingHook()
    sys.meta_path.insert(0, hook)

    class State(object):
        debug = False

        def trace(self, msg):
            if self.debug:
                print msg

    class Config(object):
        _assertstate = State()

    class Session(object):
        config = Config()

        def isinitpath(self, fn):
            return False

    hook.session = Session()

    paths = set()
    all_tests = []
    test_files = []

    for path in args.paths:
        if os.path.isfile(path):
            paths.add(os.path.dirname(path))
            file = os.path.basename(path)
            all_tests.append(file[:-3])
            test_files.append(path)
        elif os.path.isdir(path):
            for top, dirs, files in os.walk(path):
                for file in files:
                    if file.endswith(".py"):
                        paths.add(top)
                        all_tests.append(file[:-3])
                        test_files.append(os.path.join(top, file))
        else:
            print "Unknown file or directory", path
            return

        sys.path.extend(paths)
        imported_tests = []
        hook.fnpats = test_files

        for test in all_tests:
            try:
                m = __import__(test, globals(), locals())
                if hasattr(m, "test"):
                    imported_tests.extend(m.test.func_globals['_tests'])
            except Exception, e:
                print test, str(e)
        _tests.extend(set(imported_tests))

    random.shuffle(_tests)

    monocle.launch(run, _tests, args.verbose)
    eventloop.run()


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except:
        traceback.print_exc(file=sys.stdout)
        raise
    finally:
        sys.exit(_fail_count)
