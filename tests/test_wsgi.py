from __future__ import absolute_import
import threading
import time
import six.moves.urllib.request, six.moves.urllib.error, six.moves.urllib.parse

from ufork import Arbiter

from wsgiref.simple_server import make_server

from tests.utils import check_leaked_workers

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
        response = six.moves.urllib.request.urlopen('http://{}:{}'.format(SERVER_HOST, SERVER_PORT)).read()
        if six.PY3:
            assert response == b'Hello World\n'
        else:
            assert response == 'Hello World\n'
    finally:
        arbiter.stop()
        arbiter.thread.join()
        check_leaked_workers(arbiter)
