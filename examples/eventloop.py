from __future__ import print_function
import sys

import monocle

from monocle import _o
monocle.init(sys.argv[1])

from monocle.stack import eventloop
from monocle.util import sleep


@_o
def yielding_oroutine(x, z=1):
    yield sleep(1)
    print(x)


def nonyielding_oroutine(x, z=1):
    print(x)


@_o
def fail():
    raise Exception("whoo")
    yield sleep(1)


eventloop.queue_task(0, yielding_oroutine, x="oroutine worked")
eventloop.queue_task(0, nonyielding_oroutine, x="function worked")
eventloop.queue_task(0, fail)
eventloop.run()
