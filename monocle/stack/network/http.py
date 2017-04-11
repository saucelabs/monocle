import urlparse
import collections
import re
import urllib2
import time
import logging
import base64
import Cookie

from monocle import _o, Return, log_exception, VERSION
from monocle.stack.network import ConnectionLost, Client

try:
    from monocle.stack.network import SSLClient
except:
    pass

log = logging.getLogger(__name__)


class HttpException(Exception):
    pass


# a unique value to let us check when a default was not set to anything else
class _NotSetFlag(object):
    pass


class HttpHeaders(collections.MutableMapping):

    def __init__(self, headers=None):
        self.headers = []
        self.keyset = set()
        if hasattr(headers, 'iteritems'):
            for k, v in headers.iteritems():
                self.add(k, v)
        else:
            for k, v in headers or []:
                self.add(k, v)

    def __len__(self):
        return len(self.headers)

    def keys(self):
        return [k for k, v in self.headers]

    def add(self, key, value):
        key = key.lower()
        self.keyset.add(key)
        self.headers.append((key, value))

    def items(self):
        return self.headers

    def __iter__(self):
        return (k for k, v in self.headers)

    def iteritems(self):
        return (x for x in self.headers)

    def __repr__(self):
        return "<%s %s>" % (self.__class__.__name__, repr(self.headers))

    def get_list(self, key, default=_NotSetFlag):
        key = key.lower()
        if key not in self.keyset:
            if default == _NotSetFlag:
                raise KeyError(key)
            else:
                return default
        vals = [v for k, v in self.headers if k == key]
        return vals

    def __getitem__(self, key):
        vals = self.get_list(key)
        if len(vals) == 1:
            return vals[0]
        else:
            return vals

    def __setitem__(self, key, value):
        try:
            del self[key]
        except KeyError:
            pass
        return self.add(key, value)

    def __delitem__(self, key):
        key = key.lower()
        if key not in self.keyset:
            raise KeyError(key)
        self.keyset.remove(key)
        self.headers = [(k, v) for k, v in self.headers if k != key]


class HttpRequest(object):
    def __init__(self, proto='HTTP/1.0', host=None, method=None,
                 uri=None, args=None, remote_ip=None, headers=None,
                 body=None, body_file=None):
        self.proto = proto
        self.host = host
        self.method = method
        self.uri = uri
        self.remote_ip = remote_ip
        self.headers = headers
        self.body = body
        self.body_file = body_file

        self.path, _, self.query = uri.partition('?')
        self.query_args = urlparse.parse_qs(self.query, keep_blank_values=True)
        self.args = args

        self.cookies = {}
        for cookie in self.headers.get_list("cookie", []):
            try:
                for name, morsel in Cookie.BaseCookie(cookie).iteritems():
                    self.cookies[name] = morsel.value
            except Cookie.CookieError:
                pass

    def __repr__(self):
        return "<%s (%s %s %s, headers=%s)>" % (
            self.__class__.__name__, self.method, self.path, self.proto, self.headers)

    def get_basic_auth(self):
        if 'authorization' not in self.headers:
            return None, None
        auth = self.headers["authorization"]
        try:
            method, b64 = auth.split(" ")
            if method.lower() != "basic":
                return None, None
            username, password = base64.decodestring(b64).split(':', 1)
        except Exception:
            # parsing error; no valid auth
            return None, None
        return username, password


class HttpResponse(object):
    def __init__(self, code, msg=None, headers=None, body=None, proto=None):
        self.code = code
        self.msg = msg
        self.headers = headers or HttpHeaders()
        self.body = body
        self.proto = proto or 'HTTP/1.1'


def parse_headers(lines):
    headers = HttpHeaders()
    for line in lines:
        k, v = line.split(":", 1)
        headers.add(k, v.lstrip())
    return headers


def parse_request(data):
    data = data[:-4]
    lines = data.split("\r\n")
    method, path, proto = lines[0].split(" ", 2)
    headers = parse_headers(lines[1:])
    return method, path, proto, headers


def parse_response(data):
    data = data[:-4]
    lines = data.split("\r\n")
    parts = lines[0].split(" ")
    proto = parts[0]
    code = parts[1]
    if len(parts) > 2:
        msg = parts[2]
    else:
        msg = ""
    headers = parse_headers(lines[1:])
    return proto, code, msg, headers


@_o
def read_request(conn):
    data = yield conn.read_until("\r\n\r\n")
    method, path, proto, headers = parse_request(data)
    body = None
    if method in ["POST", "PUT"] and "Content-Length" in headers:
        cl = int(headers["Content-Length"])
        body = yield conn.read(cl)
    yield Return(method, path, proto, headers, body)


@_o
def write_request(conn, method, path, headers, body=None):
    yield conn.write("%s %s HTTP/1.1\r\n" % (method, path))
    for k, v in headers.iteritems():
        yield conn.write("%s: %s\r\n" % (k, v))
    yield conn.write("\r\n")
    if body:
        yield conn.write(body)


@_o
def read_response(conn):
    data = yield conn.read_until("\r\n\r\n")
    proto, code, msg, headers = parse_response(data)

    proto = proto.lower()
    content_length = int(headers.get('Content-Length', 0))
    body = ""

    # From rfc2616 section 4.4:
    # Messages MUST NOT include both a Content-Length header field and
    # a non-identity transfer-coding. If the message does include a
    # non- identity transfer-coding, the Content-Length MUST be
    # ignored.
    if headers.get('Transfer-Encoding', '').lower() == 'chunked':
        while True:
            line = yield conn.read_until("\r\n")
            line = line[:-2]
            parts = line.split(';')
            chunk_len = int(parts[0], 16)
            body += yield conn.read(chunk_len)
            yield conn.read_until("\r\n")
            if not chunk_len:
                break
    elif content_length:
        body = yield conn.read(content_length)
    elif ((proto == 'http/1.0' and
           not headers.get('Connection', '').lower() == 'keep-alive') or
          (proto == 'http/1.1' and
           headers.get('Connection', '').lower() == 'close')):
        while True:
            try:
                body += yield conn.read_some()
            except ConnectionLost:
                break

    yield Return(HttpResponse(code, msg, headers, body, proto))


@_o
def write_response(conn, resp):
    yield conn.write("%s %s %s\r\n" % (resp.proto.upper(), resp.code, resp.msg))
    for k, v in resp.headers.iteritems():
        yield conn.write("%s: %s\r\n" % (k, v))
    yield conn.write('\r\n')
    if resp.body:
        yield conn.write(resp.body)


class HttpClient(object):
    DEFAULT_PORTS = {'http': 80,
                     'https': 443}

    def __init__(self):
        self.client = None
        self.scheme = None
        self.host = None
        self.port = None
        self._timeout = None

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = value
        if self.client:
            self.client.timeout = value

    @_o
    def connect(self, host, port,
                scheme='http', timeout=None, is_proxy=False):
        if timeout is not None:
            # this parameter is deprecated
            self.timeout = None

        if self.client and not self.client.is_closed():
            self.client.close()

        if scheme == 'http':
            self.client = Client()
        elif SSLClient and scheme == 'https':
            self.client = SSLClient()
        else:
            raise HttpException('unsupported url scheme %s' % scheme)
        self.scheme = scheme
        self.host = host
        self.port = port
        self.is_proxy = is_proxy
        self.client.timeout = self._timeout
        yield self.client.connect(self.host, self.port)

    @_o
    def request(self, url, headers=None, method='GET', body=None):
        parts = urlparse.urlsplit(url)

        if self.is_proxy:
            host = parts.netloc
            path = url
        else:
            if parts.scheme and parts.scheme != self.scheme:
                raise HttpException("URL is %s but connection is %s" %
                                    (parts.scheme, self.scheme))

            host = parts.netloc
            if not host:
                host = self.host
                if self.port != self.DEFAULT_PORTS[self.scheme]:
                    host += ":%s" % self.port

            path = parts.path
            if parts.query:
                path += '?' + parts.query

        if not headers:
            headers = HttpHeaders()
        headers.setdefault('User-Agent', 'monocle/%s' % VERSION)
        headers.setdefault('Host', host)
        if body is not None:
            headers['Content-Length'] = str(len(body))

        yield write_request(self.client, method, path, headers, body)
        response = yield read_response(self.client)
        yield Return(response)

    def close(self):
        self.client.close()

    def is_closed(self):
        return self.client is None or self.client.is_closed()

    @classmethod
    @_o
    def query(cls, url, headers=None, method='GET', body=None):
        self = cls()
        parts = urlparse.urlsplit(url)
        host = parts.hostname
        port = parts.port or self.DEFAULT_PORTS[parts.scheme]

        if not self.client or self.client.is_closed():
            yield self.connect(host, port, scheme=parts.scheme)
        elif not (self.host, self.port) == (host, port):
            self.client.close()
            yield self.connect(host, port, scheme=parts.scheme)

        try:
            result = yield self.request(url, headers, method, body)
        finally:
            self.close()
        yield Return(result)


# Takes a response return value like:
# "this is a body"
# 404
# (200, "this is a body")
# (200, {"headers": "here"}, "this is a body")
#
# ...and converts that to a full (code, headers, body) tuple.
def extract_response(value):
    if isinstance(value, basestring):
        return (200, HttpHeaders(), value)
    if isinstance(value, int):
        return (value, HttpHeaders(), "")
    if len(value) == 2:
        return (value[0], HttpHeaders(), value[1])
    return value


class HttpRouter(object):
    named_param_re = re.compile(r':([^\/\?\*\:]+)')

    def __init__(self):
        self.routes = collections.defaultdict(list)

    @classmethod
    def path_matches(cls, path, pattern):
        m = pattern.match(path)
        if not m:
            return False, None
        if not m.end() == len(path):
            # must match the whole string
            return False, None
        return True, m.groupdict()

    def mk_decorator(self, method, pattern, add_head=False):
        if not hasattr(pattern, 'match'):
            pattern = re.escape(pattern)
            pattern = pattern.replace(r'\?', '?')
            pattern = pattern.replace(r'\:', ':')
            pattern = pattern.replace(r'\_', '_')
            pattern = pattern.replace(r'\/', '/')
            pattern = pattern.replace(r'\*', '.*')
            pattern = self.named_param_re.sub(r'(?P<\1>[^/]+)', pattern)
            pattern = re.compile("^" + pattern + "$")

        def decorator(f):
            handler = _o(f)
            self.routes[method].append((pattern, handler))
            if add_head:
                self.routes['HEAD'].append((pattern, handler))
            return handler
        return decorator

    def get(self, pattern, add_head=True):
        return self.mk_decorator('GET', pattern, add_head=add_head)

    def post(self, pattern):
        return self.mk_decorator('POST', pattern)

    def put(self, pattern):
        return self.mk_decorator('PUT', pattern)

    def delete(self, pattern):
        return self.mk_decorator('DELETE', pattern)

    def head(self, pattern):
        return self.mk_decorator('HEAD', pattern)

    def options(self, pattern):
        return self.mk_decorator('OPTIONS', pattern)

    def patch(self, pattern):
        return self.mk_decorator('PATCH', pattern)

    def route_match(self, req):
        for pattern, handler in self.routes[req.method]:
            match, kwargs = self.path_matches(urllib2.unquote(req.path),
                                              pattern)
            if match:
                return handler, kwargs
        return None, None

    @_o
    def request_handler_wrapper(self, req, handler, **kwargs):
        resp = yield handler(req, **kwargs)
        yield Return(resp)

    @_o
    def handle_request(self, req):
        before = time.time()
        resp = None

        handler, kwargs = self.route_match(req)
        try:
            if handler:
                resp = yield self.request_handler_wrapper(req, handler, **kwargs)
            elif self.handler:
                resp = yield self.request_handler_wrapper(req, self.handler)
            else:
                resp = (404, {}, "")
        except Exception:
            log_exception()
            resp = (500, {}, "500 Internal Server Error")
        after = time.time()

        content_length = 0
        if len(resp) > 2:
            content_length = len(resp[2])

        log.info("[%s] %s %s %s -> %s (%s bytes, %.0fms); %s",
                 req.remote_ip,
                 req.method, req.path, req.proto,
                 resp[0], content_length, (after - before) * 1000,
                 req.headers.get('user-agent'))

        yield Return(resp)


import monocle

if monocle._stack_name == 'twisted':
    from monocle.twisted_stack.network.http import *
elif monocle._stack_name == 'tornado':
    from monocle.tornado_stack.network.http import *
