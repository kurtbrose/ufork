from __future__ import absolute_import

import time
import threading
from wsgiref.simple_server import make_server

try:
    from urllib2 import urlopen
except ImportError:
    from urllib.request import urlopen  # py3

from ufork import Arbiter
from .utils import check_leaked_workers

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 7777


def wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]

    start_response(status, headers)
    yield b"Hello World\n"


httpd = make_server(SERVER_HOST, SERVER_PORT, wsgi_app)


def start_server():
    w = threading.Thread(target=httpd.serve_forever)
    w.daemon = True
    w.start()


def test_wsgiref_hello():
    arbiter = Arbiter(
        post_fork=start_server,
        child_pre_exit=httpd.shutdown,
        size=1
    )
    arbiter.spawn_thread()
    time.sleep(3)  # Todo: Find another way to wait until server is ready to accept requests.
    try:
        response = urlopen('http://{}:{}'.format(SERVER_HOST, SERVER_PORT)).read()
        assert response == b'Hello World\n'
    finally:
        arbiter.stop()
        arbiter.thread.join()
        check_leaked_workers(arbiter)
