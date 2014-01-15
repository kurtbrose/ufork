import os
import sys
import time
import socket
from multiprocessing import cpu_count
import threading
import code
import signal
import resource
from random import seed  # re-seed random number generator post-fork
from collections import deque, namedtuple
import logging
from logging.handlers import SysLogHandler
import traceback

TIMEOUT = 10.0

log = logging.getLogger(__name__)


class Worker(object):
    def __init__(self, arbiter):
        self.arbiter = arbiter
        self.stopping = False
        self.sock = None
        self.pid = None
        self.last_update = time.time()

    def fork_and_run(self):
        parent, child = socket.socketpair()
        ppid = os.getpid()
        pid = self.arbiter.fork()
        if pid:  # in parent fork
            self.pid = pid
            self.sock = parent
            child.close()
            return
        #in child fork
        parent.close()
        signal.signal(signal.SIGTERM, lambda signal, frame: self.child_stop())
        pid = os.getpid()
        self.child_close_fds()
        #TODO: should these go to UDP port 514? (syslog)
        #set stdout and stderr filenos to point to the child end of the socket-pair
        os.dup2(child.fileno(), 0)
        os.dup2(child.fileno(), 1)
        os.dup2(child.fileno(), 2)
        #TODO: prevent blocking when stdout buffer full?
        # (SockFile class provides this behavior)
        seed()  # re-seed random number generator post-fork
        self.stdin_handler = StdinHandler(self)
        self.stdin_handler.start()
        self.arbiter.post_fork()

        try:
            log.info('worker starting '+str(pid))
            fd_path = '/proc/{0}/fd'.format(pid)
            check_fd = os.path.exists(fd_path)
            while not self.stopping:
                try:
                    os.kill(ppid, 0)  # check parent process exists
                except OSError as e:
                    log.info("worker parent died "+str(ppid))
                    break
                res = resource.getrusage(resource.RUSAGE_SELF)
                if res.ru_maxrss * resource.getpagesize() > self.arbiter.child_memlimit:
                    raise OSError("memory usage exceeded limit"
                                  " {0} MiB".format(self.arbiter.child_memlimit/1024))
                if check_fd:
                    fd_count = len(os.listdir(fd_path))
                    fd_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
                    if fd_count > fd_limit - 10 or fd_count > fd_limit * 0.9:
                        raise OSError("open fd count {0} too close"
                                      " to fd limit {1}".format(fd_count, fd_limit))
                num_open_fds = len(os.listdir('/proc/{0}/fd'.format(pid)))
                child.send('\0')
                self.arbiter.sleep(1.0)
        except Exception as e:
            log.error("worker error "+repr(e))
            raise
        finally:
            if self.arbiter.child_pre_exit:
                self.arbiter.child_pre_exit()
        log.info("worker shutting down "+str(pid))
        os._exit(0)  # prevent arbiter code from executing in child

    def parent_check(self):
        try:
            data = self.sock.recv(4096, socket.MSG_DONTWAIT)
        except socket.error:
            pass
        else:
            self.last_update = time.time()
            data = data.replace('\0', '')
            if data:
                self.arbiter.printfunc(str(self.pid) + ':' + data)
        try:  # check that process still exists
            os.kill(self.pid, 0)
        except OSError:
            log.info("worker died " + str(self.pid))
            return False
        if time.time() - self.last_update > TIMEOUT:
            self.parent_kill()
            return False
        return True

    def parent_kill(self):
        try:  # kill if proc still alive
            os.kill(self.pid, signal.SIGKILL)
        except OSError as e:
            self.arbiter.printfunc("SIGKILL exception:" + repr(e))

    def parent_notify_stop(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError as e:
            self.arbiter.printfunc("SIGTERM exception:" + repr(e))

    def child_close_fds(self):
        'close fds in the child after forking'
        pass  # TODO -- figure out which should and shouldn't be closed

    def child_stop(self):
        self.stopping = True

    def send(self, data):
        'send some data down to child process stdin'
        self.sock.sendall(data)

    def __repr__(self):
        return "ufork.Worker<pid="+str(self.pid)+">"

#SIGINT and SIGTERM mean shutdown cleanly


class Arbiter(object):
    '''
    Object for managing a group of worker processes.
    '''
    def __init__(self, post_fork, child_pre_exit=None, parent_pre_stop=None,
                 size=None, sleep=None, fork=None, printfunc=None, 
                 child_memlimit=2**30, extra=None):
        self.post_fork = post_fork
        self.child_pre_exit = child_pre_exit
        self.parent_pre_stop = parent_pre_stop
        if size is None:
            size = cpu_count() + 1  # hyper-threading cores are counted in cpu_count
        self.size = size
        self.sleep = sleep or time.sleep
        self.fork = fork or os.fork
        self.printfunc = printfunc or _printfunc
        self.child_memlimit = child_memlimit
        self.extra = extra  # a place to put additional data for CLI
        global LAST_ARBITER
        LAST_ARBITER = self  # for testing/debugging, a hook to get a global pointer

    def spawn_thread(self):
        'causes run to be executed in a thread'
        self.thread = threading.Thread(target=self.run, args=(False,))
        self.thread.daemon = True
        self.thread.start()

    def spawn_daemon(self, pidfile=None, outfile="out.txt"):
        '''
        Causes this arbiters run() function to be executed in a newly spawned
        daemon process.

        Parameters
        ----------
        pidfile : str, optional
            Path at which to write a pidfile (file containing the pid of
                the daemon process).
        outfile : str, optional
            Path to text file to write stdout and stderr of workers to.
            (Daemonized arbiter process no longer has a stdout to write
            to.)  Defaults to "out.txt".
        '''
        if spawn_daemon(self.fork, pidfile, outfile):
            return
        signal.signal(signal.SIGTERM, lambda signal, frame: self.stop())
        self.run(False)

    def run(self, repl=True):
        self.workers = set()  # for efficient removal
        if repl:
            self.stdin_handler = StdinHandler(self)
            self.stdin_handler.start()
        else:
            self.stdin_handler = None
        self.stopping = False  # for manual stopping
        self.dead_workers = deque()
        try:
            log.info('starting arbiter '+repr(self))
            while not self.stopping:
                #spawn additional workers as needed
                for i in range(self.size - len(self.workers)):
                    worker = Worker(self)
                    worker.fork_and_run()
                    log.info('started worker '+str(worker.pid))
                    self.workers.add(worker)
                self._cull_workers()
                self._reap()
                time.sleep(1.0)
        finally:
            try:
                log.info('shutting down arbiter '+repr(self))
                if self.parent_pre_stop:
                    self.parent_pre_stop()  # hope this doesn't error
                #give workers the opportunity to shut down cleanly
                for worker in self.workers:
                    worker.parent_notify_stop()
                shutdown_time = time.time()
                while self.workers and time.time() < shutdown_time + TIMEOUT:
                    self._cull_workers()
                    time.sleep(1.0)
                #if workers have not shut down cleanly by now, kill them
                for w in self.workers:
                    w.parent_kill()
                self._reap()
            except:
                log.error("warning, arbiter shutdown had exception: "+traceback.format_exc())
            finally:
                if repl:
                    self.stdin_handler.stop()
                else:
                    os._exit(0)  # in case arbiter was daemonized, exit here

    def _cull_workers(self):  # remove workers which have died from self.workers
        dead = set()
        for worker in self.workers:
            if not worker.parent_check():
                dead.add(worker)
        self.workers = self.workers - dead

    def _reap(self):
        try:  # reap dead workers to avoid filling up OS process table
            res = os.waitpid(-1, os.WNOHANG)
            while res != (0, 0):
                name = EXIT_CODE_NAMES.get(res[1])
                log.info('worker {0} exit status {1} ({2})'.format(
                    res[0], res[1], name))
                self.dead_workers.append(DeadWorker(res[0], res[1], name))
                res = os.waitpid(-1, os.WNOHANG)
        except OSError as e:
            if getattr(e, "errno", None) == 10:  # errno 10 is "no child processes"
                log.info("all workers dead")
            else:
                log.info("reap caught exception"+repr(e))

    def stop(self):
        self.stopping = True


def _printfunc(msg):
    print msg


DeadWorker = namedtuple('dead', 'pid code name')


def _init_exit_code_names():
    import posix
    for name in [a for a in dir(posix) if "EX_" in a]:
        value = getattr(posix, name)
        EXIT_CODE_NAMES[value] = name

EXIT_CODE_NAMES = {}
_init_exit_code_names()


def spawn_daemon(fork=None, pidfile=None, outfile='out.txt'):
    'causes run to be executed in a newly spawned daemon process'
    fork = fork or os.fork
    open(outfile, 'a').close()  # TODO: configurable output file
    if pidfile and os.path.exists(pidfile):
        cur_pid = int(open(pidfile).read())
        try:
            os.kill(cur_pid, 0)
            raise Exception("arbiter still running with pid:"+str(cur_pid))
        except OSError:
            pass
    if fork():  # return True means we are in parent
        return True
    else:
        os.setsid()  # break association with terminal via new session id
        if fork():  # fork one more layer to ensure child will not re-acquire terminal
            os._exit(0)
        if pidfile:
            with open(pidfile, 'w') as f:
                f.write(str(os.getpid()))
        logging.root.addHandler(SysLogHandler())
        rotating_out = RotatingStdoutFile(outfile)
        rotating_out.start()
        return False  # return False means we are in daemonized process


class RotatingStdoutFile(object):
    '''
    Manages rotation of a file to which stdout and stderr are redirected.

    NOTE: Although structured as a class, there can really only be one of these,
    since each process only has a single standard out (-:

    NOTE: there are a variety of schemes possible here, fd rotation was chosen
    for its simplicity.
    '''
    def __init__(self, path, num_files=8, file_size=2**23):
        self.path = path
        self.num_files = num_files
        self.file_size = file_size
        self.fd = None
        self.stopping = False
        self._rotate()

    def stop(self):
        self.stopping = True

    def start(self):
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def _run(self):
        while not self.stopping:
            time.sleep(10.0)
            if os.stat(self.path).st_size > self.file_size:
                self._rotate()

    def _rotate(self):
        # rotate previous files if they exist
        files = [self.path] + [self.path + "." + str(i) 
                               for i in range(1, self.num_files)]
        for src, dst in reversed(zip(files[:-1], files[1:])):
            if os.path.exists(src):
                os.rename(src, dst)
        # hold onto previous fd
        old_fd = self.fd
        # re-open current file
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
        os.dup2(self.fd, 1)
        os.dup2(self.fd, 2)
        if old_fd is not None:  # close previous fd if it was open
            os.close(old_fd)


class StdinHandler(object):
    'provides command-line interaction for Arbiter'
    def __init__(self, repl_self):
        self.repl_self = repl_self
        self.stopping = False
        self.read_thread = None
        context = dict(globals())
        context['self'] = self.repl_self
        self.console = code.InteractiveConsole(context)

    def _interact(self):
        sys.stdout.flush()
        print ''  # newline on startup to clear prompt
        while not self.stopping:
            inp = self.console.raw_input('ufork>> ')
            self.console.runsource(inp)
        print ''  # newline after done to clear prompt
        sys.stdout.flush()

    def start(self):
        if self.stopping:
            raise Exception("StdinHandler is not restartable")
        self.read_thread = threading.Thread(target=self._interact)
        self.read_thread.daemon = True
        self.read_thread.start()

    def stop(self):
        self.stopping = True

try:
    import gevent
except:
    pass  # gevent worker not defined
else:
    import gevent.pywsgi
    import gevent.socket

    class GeventWsgiArbiter(Arbiter):
        def __init__(self, wsgi, address, stop_timeout=30):
            self.sock = gevent.socket.socket()
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.address = address
            self.sock.bind(address)
            self.sock.listen(128)
            self.wsgi = wsgi
            self.server = gevent.pywsgi.WSGIServer(self.sock, wsgi)
            self.server.stop_timeout = stop_timeout

            def close_sock():
                self.sock.close()
                self.server.socket.close()  # TODO: cleaner way to work with gevent?

            Arbiter.__init__(self, post_fork=self.server.start,
                             child_pre_exit=self.server.stop,
                             parent_pre_stop=close_sock,
                             sleep=gevent.sleep, fork=gevent.fork)

    def serve_wsgi_gevent(wsgi, address, stop_timeout=30):
        GeventWsgiArbiter(wsgi, address, stop_timeout).run()


def wsgiref_thread_arbiter(wsgi, host, port):
    'probably not suitable for production use; example of threaded server'
    import wsgiref.simple_server
    httpd = wsgiref.simple_server.make_server(host, port, wsgi)
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def start_server():
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()

    def close_socket():
        httpd.socket.close()

    arbiter = Arbiter(post_fork=start_server, child_pre_exit=httpd.shutdown,
                      parent_pre_stop=close_socket)
    return arbiter


def serve_wsgiref_thread(wsgi, host, port):
    wsgiref_thread_arbiter(wsgi, host, port).run()


LAST_ARBITER = None
