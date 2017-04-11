# -*- coding: utf-8 -*-
#
# by Steven Hazel

import os
import logging

from monocle import _o, Return, VERSION, log_exception
from monocle.stack.network.http import HttpHeaders, HttpRequest, HttpRouter, extract_response
from monocle.twisted_stack.network import Service, SSLService

from twisted.web import server, resource

log = logging.getLogger("monocle.twisted_stack.network.http")


class _HttpServerResource(resource.Resource):
    isLeaf = 1

    def __init__(self, handler, max_body_str_len):
        self.handler = handler
        self.max_body_str_len = max_body_str_len

    def render(self, request):
        @_o
        def _handler(twisted_request):
            try:
                headers = HttpHeaders()
                for k, vs in twisted_request.requestHeaders.getAllRawHeaders():
                    for v in vs:
                        headers.add(k, v)

                # decode UTF-8 keys, matching tornado arg parsing behavior
                args = dict(
                    [(k.decode('utf-8'), v)
                     for k, v
                     in twisted_request.args.iteritems()])

                body = None
                if hasattr(twisted_request.content, "getvalue"):
                    body = twisted_request.content.getvalue()
                else:
                    twisted_request.content.seek(0, os.SEEK_END)
                    if twisted_request.content.tell() <= self.max_body_str_len:
                        twisted_request.content.seek(0, os.SEEK_SET)
                        body = twisted_request.content.read()
                    twisted_request.content.seek(0, os.SEEK_SET)

                request = HttpRequest(
                    proto=twisted_request.clientproto,
                    host=twisted_request.getRequestHostname(),
                    method=twisted_request.method,
                    uri=twisted_request.uri,
                    args=args,
                    remote_ip=twisted_request.getClientIP(),
                    headers=headers,
                    body=body,
                    body_file=twisted_request.content)
                request._twisted_request = twisted_request

                value = yield self.handler(request)
                code, headers, content = extract_response(value)
            except Exception:
                log_exception()
                code, headers, content = 500, {}, "500 Internal Server Error"
            try:
                if twisted_request._disconnected:
                    return

                twisted_request.setResponseCode(code)
                headers.setdefault('Server', 'monocle/%s' % VERSION)
                grouped_headers = {}
                for name, value in headers.iteritems():
                    if name in grouped_headers:
                        grouped_headers[name].append(value)
                    else:
                        grouped_headers[name] = [value]
                for name, value in grouped_headers.iteritems():
                    if isinstance(name, unicode):
                        name = name.encode('ascii')
                    if isinstance(value, unicode):
                        value = value.encode('ascii')
                    twisted_request.responseHeaders.setRawHeaders(name, value)
                twisted_request.write(content)

                # close connections with a 'close' header
                if headers.get('Connection', '').lower() == 'close':
                    twisted_request.channel.persistent = False

                twisted_request.finish()
            except Exception:
                log_exception()
                raise
        _handler(request)
        return server.NOT_DONE_YET


class HttpServer(Service, HttpRouter):
    def __init__(self, port, handler=None, bindaddr="", backlog=128,
                 max_body_str_len=1024 * 1024):
        HttpRouter.__init__(self)
        self.port = port
        self.handler = handler
        self.bindaddr = bindaddr
        self.backlog = backlog
        self._twisted_listening_port = None
        self.factory = server.Site(_HttpServerResource(self.handle_request,
                                                       max_body_str_len))


class HttpsServer(SSLService, HttpRouter):
    def __init__(self, port, ssl_options, handler=None, bindaddr="", backlog=128,
                 max_body_str_len=1024 * 1024):
        HttpRouter.__init__(self)
        self.port = port
        self.ssl_options = ssl_options
        self.handler = handler
        self.bindaddr = bindaddr
        self.backlog = backlog
        self._twisted_listening_port = None
        self.factory = server.Site(_HttpServerResource(self.handle_request,
                                                       max_body_str_len))
