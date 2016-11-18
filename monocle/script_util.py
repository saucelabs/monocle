import sys
import traceback

from monocle import _o, launch
from monocle.stack import eventloop


def run(fn):
    ctx = {'exit_code': 0}

    @_o
    def _run_async(ctx):
        try:
            yield fn()
        except:
            traceback.print_exc(file=sys.stdout)
            ctx['exit_code'] = 1
        finally:
            eventloop.halt()

    launch(_run_async, ctx)
    eventloop.run()
    sys.exit(ctx['exit_code'])
