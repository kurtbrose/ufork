import os
import os.path
import sys
import time
import socket
import select
import multiprocessing #just for cpu_count!


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
        if not os.path.exists('/proc/'+str(ppid)):
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
            size = 2 * multiprocessing.cpu_count() + 1
        self.size = size
        self.address = address

    def run(self):
        sock = socket.socket()
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
                if not os.path.exists('/proc/'+str(pid)):
                    del workers[pid]
                    del update_times[pid]
            time.sleep(1.0)


def test():
   fp = ForkPool(lambda a,b: sys.stdout.write(repr(a)+" "+repr(b)), ("0.0.0.0", 9876), 1)
   fp.run()


