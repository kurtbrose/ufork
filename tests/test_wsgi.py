import socket
import threading
import time
import urllib2

from ufork import Arbiter

import wsgiref.simple_server

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 7777


def test_wsgiref_hello():
    def wsgi_hello(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        yield 'Hello World\n'

    httpd = wsgiref.simple_server.make_server(SERVER_HOST, SERVER_PORT, wsgi_hello)
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def start_server():
        w = threading.Thread(target=httpd.serve_forever)
        w.daemon = True
        w.start()

    def close_socket():
        httpd.socket.close()

    arbiter = Arbiter(
        post_fork=start_server,
        child_pre_exit=httpd.shutdown,
        parent_pre_stop=close_socket,
        size=1
    )
    arbiter_thread = threading.Thread(target=arbiter.run, kwargs={"repl": False})
    arbiter.spawn_thread()
    arbiter_thread.daemon = True
    arbiter_thread.start()
    time.sleep(2)  # Todo: Find another way to wait until server is ready to accept requests.
    assert len(arbiter.workers) == 1
    response = urllib2.urlopen('http://{}:{}'.format(SERVER_HOST, SERVER_PORT)).read()
    assert response == 'Hello World\n'
    worker = arbiter.workers[0]
    arbiter.stop()
    time.sleep(5)
    assert arbiter.dead_workers[0].pid == worker.pid
    assert arbiter.workers == {}
