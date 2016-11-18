import monocle
monocle.init('twisted')
from monocle.script_util import run

from monocle import _o
import twisted.web.client


@_o
def example():
    page = yield twisted.web.client.getPage('https://google.com')
    print len(page)

run(example)
