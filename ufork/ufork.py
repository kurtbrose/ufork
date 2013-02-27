import os
import sys
import time
import socket
from multiprocessing import cpu_count

TIMEOUT = 10.0

class ForkWorker(object):
    def __init__(self, post_fork, sleep=None):
        self.post_form = post_fork
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

    def child_close_fds(self):
        'close fds in the child after forking'
        pass #TODO

    def __del__(self): #TODO: better place to collect exit info?
        os.waitpid(self.pid, os.WNOHANG)


class ForkPool(object):
    def __init__(self, post_fork, size=None, sleep=None):
        self.post_fork = post_fork
        if size is None:
            size = 2 * cpu_count() + 1
        self.size = size
        self.sleep = sleep

    def run(self):
        #TODO: context manager around workers, so they will exit if main loop breaks?
        workers = set() #for efficient removal
        while 1:
            #spawn additional workers as needed
            for i in range(self.size - len(workers)):
                worker = ForkWorker(self.post_fork, self.sleep)
                worker.fork_and_run()
                worker.add(worker)
            #check for heartbeats from workers
            dead = set()
            for worker in workers:
                if not worker.parent_check():
                    dead.add(worker)
            workers = workers - dead
            self.sleep(1.0)


class SockFile(object):
    def __init__(self, sock):
        self.sock = sock

    def write(self, data):
        try:
            self.sock.send(data, socket.MSG_DONTWAIT)
        except socket.error:
            pass #TODO: something smarter

    #TODO: more file-functions as needed


try:
    import gevent
except:
    pass #gevent worker not defined
else:
    import gevent.pywsgi 

    def serve_wsgi_gevent(wsgi, address):
        server = gevent.pywsgi.WSGIServer(address, wsgi)
        server.init_socket()
        def post_fork():
            server.start()
        pool = ForkPool(post_fork)
        pool.run()





def test():
   fp = ForkPool(lambda a,b: sys.stdout.write(repr(a)+" "+repr(b)), ("0.0.0.0", 9876), 1)
   fp.run()


