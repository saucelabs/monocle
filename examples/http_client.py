from __future__ import print_function
import sys

import monocle

from monocle import _o
monocle.init(sys.argv[1])

from monocle.stack import eventloop
from monocle.stack.network.http import HttpClient


@_o
def req():
    client = HttpClient()
    try:
        yield client.connect("www.google.com", 80)
        resp = yield client.request('/')
        print(resp.code, repr(resp.body))
        resp = yield client.request('http://www.google.com/')
        print(resp.code, repr(resp.body))
        client.close()
        yield client.connect("localhost", 80)
        resp = yield client.request('/')
        print(resp.code, repr(resp.body))
        resp = yield client.request('http://localhost/')
        print(resp.code, repr(resp.body))
    finally:
        eventloop.halt()


monocle.launch(req)
eventloop.run()
