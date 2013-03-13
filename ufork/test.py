import ufork
import threading
import urllib2
import time
import sys
import os

def regression_test():
    'run all tests that do not require manual intervention'
    test_wsgi_hello()
    test_wsgiref_hello()
    worker_cycle_test()

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
        print "verified hello"
    finally:
        ufork.LAST_ARBITER.stopping = True
    arbiter_thread.join()

def hello_print_test():
    def print_hello():
        print "hello"
    arbiter = ufork.Arbiter(print_hello)
    arbiter.run()

def worker_cycle_test():
    arbiter = ufork.Arbiter(post_fork = suicide_worker)
    arbiter_thread = threading.Thread(target = arbiter.run())
    arbiter_thread.daemon = True
    arbiter_thread.start()
    time.sleep(6) #give some time for workers to die
    arbiter.stopping = True
    arbiter_thread.join()
    time.sleep(1) #give OS a chance to finish killing all child workers 
    assert arbiter.dead_workers
    print arbiter.dead_workers
    leaked_workers = []
    for worker in arbiter.workers:
        try: #check if process still exists
            os.kill(worker.pid, 0)
            leaked_workers.append(worker.pid)
        except OSError:
            pass #good, worker dead
    if leaked_workers:
        raise Exception("leaked workers: "+repr(leaked_workers))
    

def suicide_worker():
    def die_soon():
        time.sleep(2)
        sys.exit(0)
    suicide_thread = threading.Thread(target=die_soon)
    suicide_thread.daemon = True
    suicide_thread.start()

def wsgi_hello(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    yield 'Hello World\n'

def verify_hello(addr):
    assert urllib2.urlopen('http://'+addr).read() == 'Hello World\n'
