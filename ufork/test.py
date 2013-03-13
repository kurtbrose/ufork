import ufork
import threading
import urllib2
import time

def test_wsgi_hello():
    def test_control():
        time.sleep(3) #give the server time to start up
        try:
            verify_hello('127.0.0.1:7777')
        finally:
            ufork.LAST_ARBITER.stopping = True
    test_thread = threading.Thread(target=test_control)
    test_thread.daemon = True
    test_thread.start()
    ufork.serve_wsgi_gevent(wsgi_hello, ('0.0.0.0', 7777))

def test_wsgiref_hello():
    arbiter_thread = threading.Thread(
        target=ufork.serve_wsgiref_thread,
        args=(wsgi_hello, '0.0.0.0', 7777))
    arbiter_thread.daemon=True
    arbiter_thread.start()
    time.sleep(3) #give server time to start up
    try:
        verify_hello('127.0.0.1:7777')
    finally:
        ufork.LAST_ARBITER.stopping = True

def hello_print_test():
    def print_hello():
        print "hello"
    arbiter = ufork.Arbiter(print_hello)
    arbiter.run()

def worker_cycle_test():
    pass


def wsgi_hello(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    yield 'Hello World\n'

def verify_hello(addr):
    assert urllib2.urlopen('http://'+addr).read() == 'Hello World\n'
