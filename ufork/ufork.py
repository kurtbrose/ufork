import os
import os.path
import time
import socket
import select
import multiprocessing #just for cpu_count!


def fork_and_serve(start_serve, sleep=time.sleep):
    parent, child = socket.socketpair()
    ppid = os.getpid()
    pid = os.fork()
    if pid:
        return parent, pid
    start_serve()
    while 1:
        if not os.path.exists('/proc/'+str(ppid)):
            break
        child.write('a')
        sleep(1.0)
    sys.exit()


class ForkPool(object):
    def __init__(self, start_serve, size=None):
        self.start_serve = start_serve
        if size is None:
            size = 2 * multiprocessing.cpu_count() + 1
        self.size = size

    def run(self):
        workers = {}
        update_times = {}
        while 1:
            for i in range(self.size - len(self.workers)):
                sock, pid = fork_and_serve(self.start_serve)
                workers[pid] = sock
                update_times[pid] = time.time()
            for pid, sock in workers.items():
                if select.select([sock], [], []):
                    sock.recv(4096)
                    update_times[pid] = time.time()
            for pid in workers:
                if time.time() - update_times[pid] > self.timeout:
                    os.kill(pid)
                    del workers[pid]
                    del update_times[pid]
            time.sleep(1.0)






