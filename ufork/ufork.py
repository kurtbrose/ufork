import os
import os.path
import sys
import time
import socket
import select
import multiprocessing #just for cpu_count!


def fork_and_serve(sock, handle_conn, select=select.select):
    sock.settimeout(1.0)
    stopping = False
    parent, child = socket.socketpair()
    ppid = os.getpid()
    pid = os.fork()
    if pid:
        return parent, pid

    while not stopping:
        if not os.path.exists('/proc/'+str(ppid)):
            break
        child.write('a')
        try:
            conn, addr = sock.accept()
        except socket.timeout:
            conn, addr = None, None
        if conn:
            handle_conn(conn, addr)

    sys.exit()


class ForkPool(object):
    def __init__(self, handle_conn, size=None):
        self.handle_conn = handle_conn
        if size is None:
            size = 2 * multiprocessing.cpu_count() + 1
        self.size = size

    def run(self):
        workers = {}
        update_times = {}
        while 1:
            #spawn additional workers as needed
            for i in range(self.size - len(workers)):
                sock, pid = fork_and_serve(self.handle_conn)
                workers[pid] = sock
                update_times[pid] = time.time()
            #check for heartbeats from workers
            for pid, sock in workers.items():
                if select.select([sock], [], []):
                    sock.recv(4096)
                    update_times[pid] = time.time()
            #kill workers which seem to have died
            for pid in workers:
                if time.time() - update_times[pid] > self.timeout:
                    os.kill(pid)
            #remove processes which no longer exist from workers
            for pid in workers:
                if not os.path.exists('/proc/'+str(pid)):
                    del workers[pid]
                    del update_times[pid]
            time.sleep(1.0)






