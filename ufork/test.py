import ufork
import threading
import urllib2
import time

def test_wsgi_hello():
    def test_control():
        time.sleep(3) #give the server time to start up
        try:
            assert urllib2.urlopen('127.0.0.1:7777').read() == 'Hello World\n'
        finally:
            ufork.LAST_ARBITER.stopping = True
    test_thread = threading.Thread(target=test_control)
    test_thread.daemon = True
    test_thread.start()
    ufork.serve_wsgi_gevent(wsgi_hello, ('0.0.0.0', 7777))

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
