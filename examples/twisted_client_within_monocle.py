import monocle
monocle.init('twisted')
from monocle import _o
import twisted.web.client
from monocle.stack import eventloop

# next line breaks the twisted http client in some cases
import monocle.stack.network.http  # NOQA


@_o
def req():
    try:
        yield twisted.web.client.getPage('https://google.com')
    finally:
        eventloop.halt()
monocle.launch(req)
eventloop.run()
