# -*- coding: utf-8 -*-
#
# by Steven Hazel

import io
import tornado.httpclient
import tornado.httpserver

from httplib import responses
from monocle import _o, Return, VERSION, launch
from monocle.callback import Callback
from monocle.stack.network.http import HttpHeaders, HttpRequest, HttpClient, HttpRouter, extract_response
from monocle.tornado_stack.network import Service


class HttpClient(HttpClient):
    @classmethod
    @_o
    def query(self, url, headers=None, method='GET', body=None):
        _http_client = tornado.httpclient.AsyncHTTPClient()
        req = tornado.httpclient.HTTPRequest(url,
                                             method=method,
                                             headers=headers or {},
                                             body=body,
                                             # XXX: TODO
                                             #request_timeout=self.timeout
                                             )
        cb = Callback()
        _http_client.fetch(req, cb)
        response = yield cb
        yield Return(response)


class HttpServer(Service, HttpRouter):
    def __init__(self, port, handler=None):
        HttpRouter.__init__(self)
        self.handler = handler
        self.port = port

    def _add(self, el):
        @_o
        def _handler(tornado_request):
            try:
                headers = HttpHeaders()
                for k, v in tornado_request.headers.get_all():
                    headers.add(k, v)

                body_file = io.BytesIO(tornado_request.body)
                request = HttpRequest(proto=tornado_request.version,
                                      host=tornado_request.host,
                                      method=tornado_request.method,
                                      uri=tornado_request.uri,
                                      args=tornado_request.arguments,
                                      remote_ip=tornado_request.remote_ip,
                                      headers=headers,
                                      body=tornado_request.body,
                                      body_file=body_file)
                request._tornado_request = tornado_request

                value = yield launch(self.handle_request, request)
                code, headers, content = extract_response(value)
            except:
                code, headers, content = 500, {}, "500 Internal Server Error"
            tornado_request.write("HTTP/1.1 %s %s\r\n" %
                                  (code, responses.get(code, 'Unknown')))
            headers.setdefault('Server', 'monocle/%s' % VERSION)
            headers.setdefault('Content-Length', str(len(content)))
            for name, value in headers.iteritems():
                if isinstance(name, unicode):
                    name = name.encode('ascii')
                if isinstance(value, unicode):
                    value = value.encode('ascii')
                tornado_request.write("%s: %s\r\n" % (name, value))
            tornado_request.write("\r\n")
            tornado_request.write(content)
            tornado_request.finish()
        self._http_server = tornado.httpserver.HTTPServer(
            _handler,
            io_loop=el._tornado_ioloop)
        self._http_server.listen(self.port)
