import ufork
import threading
import urllib2
import time

def test_wsgi_hello():
    server_thread = threading.Thread(
        target=ufork.serve_wsgi_gevent, 
        args=(wsgi_hello, ('0.0.0.0', 7777)))
    server_thread.daemon = True
    server_thread.start()
    time.sleep(3) #give the server time to start up
    assert urllib2.urlopen('127.0.0.1:7777').read() == 'Hello World\n'
    ufork.LAST_ARBITER.stopping = True
    server_thread.join()

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
