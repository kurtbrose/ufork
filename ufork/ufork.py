import os
import sys
import time
import socket
from multiprocessing import cpu_count
import threading
import code
import signal

TIMEOUT = 10.0

class Worker(object):
    def __init__(self, post_fork, sleep=None):
        self.post_fork = post_fork
        self.sleep = sleep or time.sleep
        self.stopping = False
        self.sock = None
        self.pid = None
        self.last_update = time.time()

    def fork_and_run(self):
        parent, child = socket.socketpair()
        ppid = os.getpid()
        pid = os.fork()
        if pid: #in parent fork
            self.pid = pid
            self.sock = parent
            return
        #in child fork
        self.child_close_fds()
        sys.stdout = SockFile(child)
        sys.stderr = SockFile(child)
        os.close(0) #just close stdin for now so it doesnt mess up repl

        self.post_fork()

        while not self.stopping:
            try:
                os.kill(ppid, 0) #kill 0 sends no signal, but checks that process exists
            except:
                break
            child.send('\0')
            self.sleep(1.0)
        sys.exit()

    def parent_check(self):
        try:
            print "check"
            data = self.sock.recv(4096, socket.MSG_DONTWAIT)
        except socket.error:
            pass
        else:
            self.last_update = time.time()
            data = data.replace('\0', '')
            if data:
                print self.pid,':',data
        try: #check that process still exists
            os.kill(self.pid, 0)
        except:
            return False
        if time.time() - self.last_update > TIMEOUT:
            os.kill(self.pid)
            return False
        return True

    def parent_kill(self):
        try: #kill if proc still alive
            os.kill(self.pid)
        except:
            pass

    def child_close_fds(self):
        'close fds in the child after forking'
        pass #TODO

    def __del__(self): #TODO: better place to collect exit info?
        os.waitpid(self.pid, os.WNOHANG)

#signal handling serves two purposes:
# 1- graceful shutdown of workers when possible
# 2- worker management
SIGNAL_NAMES = ["SIGHUP", "SIGINT", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGTERM",
    "SIGCHLD", "SIGTTIN", "SIGTTOU", "SIGWINCH"]

SIGNALS = [getattr(signal, e) for e in SIGNAL_NAMES]

STOP_SIGNALS = set([signal.SIGINT, signal.SIGTERM])

class Arbiter(object):
    def __init__(self, post_fork, size=None, sleep=None):
        self.post_fork = post_fork
        if size is None:
            size = 2 * cpu_count() + 1
        self.size = size
        self.sleep = sleep or time.sleep

    def run(self):
        workers = set() #for efficient removal
        self._install_sig_handlers()
        self.stdin_handler = StdinHandler(self)
        self.stdin_handler.start()
        try:
            while 1:
                #spawn additional workers as needed
                for i in range(self.size - len(workers)):
                    worker = Worker(self.post_fork, self.sleep)
                    worker.fork_and_run()
                    workers.add(worker)
                #check for heartbeats from workers
                dead = set()
                for worker in workers:
                    if not worker.parent_check():
                        dead.add(worker)
                workers = workers - dead
                time.sleep(1.0)
        except:
            for worker in workers:
                worker.parent_kill()
            self._remove_sig_handlers()
            self.stdin_handler.stop()
            raise #shut down workers if main loop dies

    def _install_sig_handlers(self):
        #backup existing signal handlers
        self.prev_sig_handlers = [(sig, signal.getsignal(sig)) for sig in SIGNALS]
        

    def _remove_sig_handlers(self):
        #restore previous signal handlers
        for sigcode, handler in self.prev_sig_handlers:
            signal.signal(sigcode, handler)


class SockFile(object):
    def __init__(self, sock):
        self.sock = sock

    def write(self, data):
        try:
            self.sock.send(data, socket.MSG_DONTWAIT)
        except socket.error:
            pass #TODO: something smarter

    #TODO: more file-functions as needed

class StdinHandler(object):
    'provides command-line interaction for Arbiter'
    def __init__(self, arbiter):
        self.arbiter = arbiter
        self.stopping = False
        self.read_thread = None
        context = dict(globals())
        context['arbiter'] = self.arbiter
        self.console = code.InteractiveConsole(context)

    def _interact(self):
        while not self.stopping:
            inp = self.console.raw_input('ufork>>')
            self.console.runsource(inp)

    def start(self):
        threading.Thread(target=self._interact)
        self.read_thread.daemon = True
        self.read_thread.start()

    def stop(self):
        self.stopping = True

try:
    import gevent
except:
    pass #gevent worker not defined
else:
    import gevent.pywsgi 
    import gevent.socket

    def serve_wsgi_gevent(wsgi, address):
        sock = gevent.socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(address)
        sock.listen(128) #TODO: what value?
        server = gevent.pywsgi.WSGIServer(sock, wsgi)
        def post_fork():
            server.start()
        arbiter = Arbiter(post_fork, sleep=gevent.sleep)
        arbiter.run()


def test():

    def wsgi_hello(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain')])
        yield 'Hello World\n'

    serve_wsgi_gevent(wsgi_hello, ('0.0.0.0', 7777))

def hello_print_test():
    def print_hello():
        print "hello"
    arbiter = Arbiter(print_hello)
    arbiter.run()
