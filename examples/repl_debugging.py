import sys

import monocle
from monocle import _o
monocle.init(sys.argv[1])

from monocle.stack import eventloop
from monocle.repl import repl

@_o
def main():
    x = 7
    print "about to drop into repl, x =", x
    yield repl()
    print "returned from repl, x =", x

monocle.launch(main)
eventloop.run()
