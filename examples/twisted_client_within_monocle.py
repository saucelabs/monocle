'''
This shows how to make HTTP requests using the Twisted HTTP client within
monocle.
'''
import monocle
monocle.init('twisted')
from monocle.script_util import run

from monocle import _o

from twisted.internet import reactor
try:
    from twisted.web.client import (
        Agent,
        ProxyAgent,
        RedirectAgent,
    )
    from twisted.internet.endpoints import TCP4ClientEndpoint
except ImportError:
    print 'This test needs Twisted 11.1+'
    raise SystemExit()

url = 'http://google.com'


@_o
def example():
    # Follow HTTP redirects
    agent = RedirectAgent(Agent(reactor))
    response = yield agent.request('GET', url)
    print '{} responded with code {}'.format(url, response.code)


@_o
def proxy_example():
    '''
    make an HTTP request though a proxy running on localhost:31337
    '''
    endpoint = TCP4ClientEndpoint(reactor, "localhost", 31337)
    agent = ProxyAgent(endpoint)
    response = yield agent.request('GET', url)
    print response.code, response.headers, response.length

run(example)
