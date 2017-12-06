from __future__ import print_function
import time

import monocle
from monocle import _o
from monocle.stack.network import add_service, Service, Client, ConnectionLost
from o_test import test


@_o
def handle_echo(conn):
    while True:
        try:
            message = yield conn.read_until('\r\n')
        except ConnectionLost:
            break
        yield conn.write("you said: %s\r\n" % message.strip())


@test
@_o
def test_lots_of_messages():
    add_service(Service(handle_echo, port=8000))
    try:
        client = Client()
        yield client.connect('localhost', 8000)
        t = time.time()
        for x in xrange(10000):
            msg = "hello, world #%s!" % x
            yield client.write(msg + '\r\n')
            echo_result = yield client.read_until("\r\n")
            assert echo_result.strip() == "you said: %s" % msg
        print('10000 loops in %.2fs' % (time.time() - t))
    finally:
        client.close()
