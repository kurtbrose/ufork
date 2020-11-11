# install ufork and run with "python example.py"

import os
from wsgiref.simple_server import make_server

from ufork import Arbiter

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 7777


def wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]

    start_response(status, headers)
    yield ("Hello, World! (from PID %s)\n" % os.getpid()).encode('utf-8')


httpd = make_server(SERVER_HOST, SERVER_PORT, wsgi_app)


def start_server():
    print('starting server on http://%s:%s' % (SERVER_HOST, SERVER_PORT))
    arbiter = Arbiter(
        post_fork=httpd.serve_forever,
        child_pre_exit=httpd.shutdown,
        size=2
    )
    arbiter.run()

start_server()
