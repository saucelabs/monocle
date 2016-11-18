import sys

import monocle

from monocle import _o
monocle.init('twisted')

import traceback
from monocle.stack import eventloop
from monocle.stack.network.http import HttpClient


@_o
def req():
    client = HttpClient()
    try:
        yield client.connect("www.google.com", 443, "https")
        print "connected"
        resp = yield client.request('/')
        print resp.code, repr(resp.body)
        client.close()
    except:
        traceback.print_exc(file=sys.stdout)
        raise
    finally:
        eventloop.halt()
        print "finished"


monocle.launch(req)
eventloop.run()
