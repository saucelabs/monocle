import sys
import monocle
monocle.init(sys.argv[1])

from monocle.script_util import run

from monocle import _o
from monocle.stack.network.http import HttpClient


@_o
def example():
    client = HttpClient()
    yield client.connect("www.google.com", 443, "https")
    print "connected"
    resp = yield client.request('/')
    print "response code -> %s" % resp.code
    print "page length -> %s" % len(repr(resp.body))
    client.close()

run(example)
