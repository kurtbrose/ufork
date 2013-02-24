import os
import sys
import time
import socket
import select
from multiprocessing import cpu_count


TIMEOUT = 10.0

def fork_and_serve(sock, handle_conn, select=select.select):
    stopping = False
    parent, child = socket.socketpair()
    ppid = os.getpid()
    pid = os.fork()
    if pid:
        return parent, pid

    sock.settimeout(1.0)
    #TODO: this is a debug hack
    class Writer(object):
       def write(self, data): child.send(data)
    sys.stdout = Writer()
    sys.stderr = Writer()

    while not stopping:
        try:
            os.kill(ppid, 0) #kill 0 sends no signal, but checks that process exists
        except:
            break
        child.send('a')
        try:
            conn, addr = sock.accept()
        except socket.timeout:
            conn, addr = None, None
        if conn:
            handle_conn(conn, addr)

    sys.exit()


class ForkPool(object):
    def __init__(self, handle_conn, address, size=None):
        self.handle_conn = handle_conn
        if size is None:
            size = 2 * cpu_count() + 1
        self.size = size
        self.address = address

    def run(self):
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self.address)
        sock.listen(5)
        workers = {}
        update_times = {}
        while 1:
            #spawn additional workers as needed
            for i in range(self.size - len(workers)):
                sock, pid = fork_and_serve(sock, self.handle_conn)
                workers[pid] = sock
                update_times[pid] = time.time()
            #check for heartbeats from workers
            for pid, sock in workers.items():
                if select.select([sock], [], []):
                    print pid, ":", sock.recv(4096)
                    update_times[pid] = time.time()
            #kill workers which seem to have died
            for pid in workers:
                if time.time() - update_times[pid] > TIMEOUT:
                    os.kill(pid)
            #remove processes which no longer exist from workers
            for pid in workers:
                try: #will not send a signal, just check proc exists
                    os.kill(pid, 0)
                except: #failure means process no longer exists
                    del workers[pid]
                    del update_times[pid]
                    #clear zombie processes from OS's process table
                    os.waitpid(pid)
                    #TODO: confirm this is the right thing to do
            time.sleep(1.0)


try:
    import gevent
except:
    pass #gevent worker not defined
else:
    from gevent.pywsgi import WSGIHandler

    class GeventServer(object):
        pass

    class GeventWorker(object):
        def __init__(self, wsgi_app, concurrent=100):
            self.concurrent = 100
            self.wsgi_app = wsgi_app

        def __call__(self, socket, address):
            if self.concurrent:
                pass
            #TODO: server
            WSGIHandler(socket, address, GeventServer()).handle()


def test():
   fp = ForkPool(lambda a,b: sys.stdout.write(repr(a)+" "+repr(b)), ("0.0.0.0", 9876), 1)
   fp.run()


