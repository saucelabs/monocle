""" sloppy monkeypatch for pytest assertion rewriting to make it
    usable to o_test """

import os
import sys
import py
import imp
import errno
from _pytest import config
from _pytest.assertion import install_importhook
from _pytest.assertion.rewrite import (
    PYC_TAIL,
    _read_pyc,
    _rewrite_test,
    _make_rewritten_pyc,
    AssertionRewritingHook,
)

class AssertionRewritingHook(AssertionRewritingHook):

    def find_module(self, name, path=None):
        if self.session is None:
            return None
        sess = self.session
        state = sess.config._assertstate
        state.trace("find_module called for: %s" % name)
        names = name.rsplit(".", 1)
        lastname = names[-1]
        pth = None
        if path is not None:
            # Starting with Python 3.3, path is a _NamespacePath(), which
            # causes problems if not converted to list.
            path = list(path)
            if len(path) == 1:
                pth = path[0]
        if pth is None:
            try:
                fd, fn, desc = imp.find_module(lastname, path)
            except ImportError:
                return None
            if fd is not None:
                fd.close()
            tp = desc[2]
            if tp == imp.PY_COMPILED:
                if hasattr(imp, "source_from_cache"):
                    fn = imp.source_from_cache(fn)
                else:
                    fn = fn[:-1]
            elif tp != imp.PY_SOURCE:
                # Don't know what this is.
                return None
        else:
            fn = os.path.join(pth, name.rpartition(".")[2] + ".py")
        self.session = None
        fn_pypath = py.path.local(fn)
        self.session = sess
        # Is this a test file?
        if not sess.isinitpath(fn):
            # We have to be very careful here because imports in this code can
            # trigger a cycle.
            self.session = None
            try:
                for pat in self.fnpats:
                    if str(fn_pypath).endswith(pat):
                        state.trace("matched test file %r" % (fn,))
                        break
                else:
                    return None
            finally:
                self.session = sess
        else:
            state.trace("matched test file (was specified on cmdline): %r" %
                        (fn,))
        # The requested module looks like a test file, so rewrite it. This is
        # the most magical part of the process: load the source, rewrite the
        # asserts, and load the rewritten source. We also cache the rewritten
        # module code in a special pyc. We must be aware of the possibility of
        # concurrent pytest processes rewriting and loading pycs. To avoid
        # tricky race conditions, we maintain the following invariant: The
        # cached pyc is always a complete, valid pyc. Operations on it must be
        # atomic. POSIX's atomic rename comes in handy.
        write = not sys.dont_write_bytecode
        cache_dir = os.path.join(fn_pypath.dirname, "__pycache__")
        if write:
            try:
                os.mkdir(cache_dir)
            except OSError:
                e = sys.exc_info()[1].errno
                if e == errno.EEXIST:
                    # Either the __pycache__ directory already exists (the
                    # common case) or it's blocked by a non-dir node. In the
                    # latter case, we'll ignore it in _write_pyc.
                    pass
                elif e in [errno.ENOENT, errno.ENOTDIR]:
                    # One of the path components was not a directory, likely
                    # because we're in a zip file.
                    write = False
                elif e in [errno.EACCES, errno.EROFS]:
                    state.trace("read only directory: %r" % fn_pypath.dirname)
                    write = False
                else:
                    raise
        cache_name = fn_pypath.basename[:-3] + PYC_TAIL
        pyc = os.path.join(cache_dir, cache_name)
        # Notice that even if we're in a read-only directory, I'm going
        # to check for a cached pyc. This may not be optimal...
        co = _read_pyc(fn_pypath, pyc, state.trace)
        if co is None:
            state.trace("rewriting %r" % (fn,))
            self.session = None
            try:
                source_stat, co = _rewrite_test(state, fn_pypath)
            finally:
                self.session = sess
            if co is None:
                # Probably a SyntaxError in the test.
                return None
            if write:
                self.session = None
                try:
                    _make_rewritten_pyc(state, source_stat, pyc, co)
                finally:
                    self.session = sess
        else:
            state.trace("found cached rewritten pyc for %r" % (fn,))
        self.session = None
        try:
            self.modules[name] = co, pyc
        finally:
            self.session = sess
        return self

def make_assertion_hook():
    c = config.get_config()
    c.parse([])
    return install_importhook(c)
