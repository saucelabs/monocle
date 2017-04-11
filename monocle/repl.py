import sys
import code
import readline
import atexit
import os
import traceback
import inspect
from threading import Thread

import monocle
from monocle import Return, _o
if __name__ != '__main__':
    from monocle.stack import eventloop

from monocle.callback import Callback


# it's annoying to ever see these warnings at the repl, so tolerate a lot
monocle.core.blocking_warn_threshold = 10000


class HistoryConsole(code.InteractiveConsole):
    def __init__(self, locals=None, filename="<console>",
                 histfile=os.path.expanduser("~/.console-history")):
        code.InteractiveConsole.__init__(self, locals, filename)
        self.init_history(histfile)

    def init_history(self, histfile):
        readline.parse_and_bind("tab: complete")
        if hasattr(readline, "read_history_file"):
            try:
                readline.read_history_file(histfile)
            except IOError:
                pass
            atexit.register(self.save_history, histfile)

    def save_history(self, histfile):
        readline.write_history_file(histfile)


@_o
def repl(debug=True):
    print "Monocle", monocle.VERSION, "/", "Python", sys.version
    print 'Type "help", "copyright", "credits" or "license" for more information.'
    print "You can yield to Monocle oroutines at the prompt."
    if debug:
        print "Use cont() to continue."
    ic = HistoryConsole()
    gs = dict(globals())

    done = {'val': False}

    def cont():
        done['val'] = True

    ls = {}
    if debug:
        frame = inspect.currentframe()
        ls = frame.f_back.f_back.f_back.f_back.f_locals
        ls['cont'] = cont

    source = ""
    while not done['val']:
        try:
            if source:
                source += "\n"

            cb = Callback()

            def wait_for_input():
                try:
                    prompt = ">>> "
                    if source:
                        prompt = "... "
                    s = ic.raw_input(prompt)
                except EOFError:
                    eventloop.queue_task(0, eventloop.halt)
                    return
                eventloop.queue_task(0, cb, s)

            Thread(target=wait_for_input).start()
            source += yield cb

            if "\n" in source and not source.endswith("\n"):
                continue

            try:
                _c = code.compile_command(source)
                if not _c:
                    continue
                eval(_c, gs, ls)
            except SyntaxError, e:
                if "'yield' outside function" not in str(e):
                    raise

                # it's a yield!

                try:
                    core_hack_source = "    __r = (" + source.replace("\n", "\n    ") + ")"
                    hack_source = "def __g():\n" + core_hack_source + "\n    yield Return(locals())\n\n"
                    _c = code.compile_command(hack_source)
                except SyntaxError:
                    # maybe the return value assignment wasn't okay
                    core_hack_source = "    " + source.replace("\n", "\n    ")
                    hack_source = "def __g():\n" + core_hack_source + "\n    yield Return(locals())\n\n"
                    _c = code.compile_command(hack_source)

                if not _c:
                    continue

                # make the locals global so __g can reach them
                g_gs = dict(gs)
                g_gs.update(ls)
                eval(_c, g_gs, ls)

                # now monoclize it and get the callback
                _c = code.compile_command("monocle.o(__g)()", symbol="eval")
                cb = eval(_c, gs, ls)
                ls.pop('__g')
                #print "=== waiting for %s ===" % cb
                g_ls = yield cb
                if '__r' in g_ls:
                    r = g_ls.pop('__r')
                    ls['_'] = r
                    if r:
                        print r
                ls.update(g_ls)
        except Exception:
            traceback.print_exc()

        source = ""


if __name__ == '__main__':
    monocle.init(sys.argv[1])
    from monocle.stack import eventloop
    monocle.launch(repl, debug=False)
    eventloop.run()
