import os
import sys
import time
import socket
from multiprocessing import cpu_count
import threading
import code
import signal
import resource
import errno
from random import seed  # re-seed random number generator post-fork
from collections import deque, namedtuple
import logging
from logging.handlers import SysLogHandler
import traceback
import select

TIMEOUT = 10.0
# grace period before timeout is applied for post_fork initialization
CHILD_START_TIMEOUT = 10 * 60.0
CUR_WORKER = None


class Worker(object):
    def __init__(self, arbiter, index):
        self.arbiter = arbiter
        self.stopping = False
        self.sock = None
        self.pid = None
        self.last_update = None
        self.start_time = time.time()
        self.worker_id = index

    def fork_and_run(self):
        parent_io, child_io = socket.socketpair()
        parent_health, child_health = socket.socketpair()
        ppid = os.getpid()
        pid = self.arbiter.fork()
        if pid:  # in parent fork
            self.pid = pid
            self.child_io = parent_io
            self.child_health = parent_health
            child_io.close()
            child_health.close()
            self.arbiter.total_children += 1
            return
        #in child fork
        global CUR_WORKER
        CUR_WORKER = self
        self.arbiter.in_child = True
        try:
            parent_io.close()
            parent_health.close()
            signal.signal(signal.SIGTERM,
                          lambda signal, frame: self.child_stop())
            pid = os.getpid()
            self.child_close_fds()
            #TODO: should these go to UDP port 514? (syslog) set
            #stdout and stderr filenos to point to the child end of
            #the socket-pair
            os.dup2(child_io.fileno(), 0)
            os.dup2(child_io.fileno(), 1)
            os.dup2(child_io.fileno(), 2)
            #TODO: prevent blocking when stdout buffer full?
            # (SockFile class provides this behavior)
            seed()  # re-seed random number generator post-fork
            if self.arbiter.child_console:
                self.stdin_handler = StdinHandler(self)
                self.stdin_handler.start()
            self.arbiter.post_fork()
            failed = False
            try:
                self.arbiter.printfunc('worker starting '+str(pid))
                fd_path = '/proc/{0}/fd'.format(pid)
                check_fd = os.path.exists(fd_path)
                while not self.stopping:
                    try:
                        os.kill(ppid, 0)  # check parent process exists
                    except OSError as e:
                        self.arbiter.printfunc("worker parent died "+str(ppid))
                        break
                    if os.uname()[0] != 'Darwin':
                        res = resource.getrusage(resource.RUSAGE_SELF)
                        if res.ru_maxrss * 1024 > self.arbiter.child_memlimit:
                            raise OSError("memory usage {1} * {2} exceeded limit"
                                          " {0} MiB".format(self.arbiter.child_memlimit/1024,
                                                            res.ru_maxrss,
                                                            1024))
                        if check_fd:
                            fd_count = len(os.listdir(fd_path))
                            fd_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
                            if fd_count > fd_limit - 10 or fd_count > fd_limit * 0.9:
                                raise OSError("open fd count {0} too close"
                                              " to fd limit {1}".format(fd_count, fd_limit))
                            num_open_fds = len(os.listdir('/proc/{0}/fd'.format(pid)))
                    child_health.send('\0')
                    self.arbiter.sleep(1.0)
            except Exception as e:
                self.arbiter.printfunc("worker error " + repr(e))
                failed = True
            finally:
                if self.arbiter.child_pre_exit:
                    self.arbiter.child_pre_exit()
        except SystemExit:
            self.arbiter.printfunc("worker shutting down with SystemExit")
            raise
        except:
            self.arbiter.printfunc("worker shutting down with error")
            self.arbiter.printfunc(traceback.format_exc())
            raise SystemExit(1)  # prevent arbiter code from executing in child
        else:
            raise SystemExit()  # prevent arbiter code from executing in child

    def parent_print_io(self):
        try:
            data = self.child_io.recv(4096, socket.MSG_DONTWAIT)
        except socket.error:
            pass
        else:
            self.last_update = time.time()
            if data:
                self.arbiter.printfunc(str(self.pid) + ':' + data.rstrip('\n'))

    def parent_check(self):
        try:
            data = self.child_health.recv(4096, socket.MSG_DONTWAIT)
        except socket.error:
            pass
        else:
            self.last_update = time.time()
        try:  # check that process still exists
            os.kill(self.pid, 0)
        except OSError:
            self.arbiter.printfunc("worker died " + str(self.pid))
            return False
        timeout = False
        if self.last_update is None:
            if time.time() - self.start_time > CHILD_START_TIMEOUT:
                timeout = True
        elif time.time() - self.last_update > TIMEOUT:
            timeout = True
        if timeout:
            self.arbiter.printfunc("worker timed out" + str(self.pid))
            self.arbiter.timed_out_children += 1
            total_children, timed_out_children, last_logged_child_issue = \
                self.arbiter.total_children, self.arbiter.timed_out_children, self.arbiter.last_logged_child_issue
            if total_children > 5 and timed_out_children > 0.5 * total_children and \
                    time.time() - last_logged_child_issue > 60 * 10:
                self.arbiter.last_logged_child_issue = time.time()
                self.arbiter.printfunc("Most children are wedging!  {0} time outs, {1} total".format(
                    timed_out_children, total_children))
            self.parent_kill()
            print 'returning false for', self.pid
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
        return "ufork.Worker<pid=" + str(self.pid) + ">"


def cur_worker_id():
    if CUR_WORKER:
        return CUR_WORKER.worker_id
    return None


#SIGINT and SIGTERM mean shutdown cleanly


class Arbiter(object):
    '''
    Object for managing a group of worker processes.
    '''
    def __init__(self, post_fork, child_pre_exit=None, parent_pre_stop=None,
                 size=None, sleep=None, fork=None, printfunc=None,
                 child_memlimit=2**30, max_no_ping_children=1, extra=None):
        self.post_fork = post_fork
        self.child_pre_exit = child_pre_exit
        self.parent_pre_stop = parent_pre_stop
        if size is None:
            size = max(cpu_count() - 1, 2)  # hyper-threading cores are counted in cpu_count
        self.size = size
        self.sleep = sleep or time.sleep
        self.fork = fork or os.fork
        self.no_ping_children = set()  # children which have not yet pinged back
        self.max_no_ping_children = max_no_ping_children
        self.printfunc = printfunc or _printfunc
        self.child_memlimit = child_memlimit
        self.extra = extra  # a place to put additional data for CLI
        self.child_console = False
        global LAST_ARBITER
        LAST_ARBITER = self  # for testing/debugging, a hook to get a global pointer

        self.total_children = 0
        self.timed_out_children = 0
        self.last_logged_child_issue = 0
        self.in_child = False

    def spawn_thread(self):
        'causes run to be executed in a thread'
        self.thread = threading.Thread(target=self.run, args=(False,))
        self.thread.daemon = True
        self.thread.start()

    def spawn_daemon(self, pgrpfile=None, outfile="out.txt"):
        '''
        Causes this arbiters run() function to be executed in a newly spawned
        daemon process.

        Parameters
        ----------
        pgrpfile : str, optional
            Path at which to write a pgrpfile (file containing the process
            group id of the daemon process and its children).
        outfile : str, optional
            Path to text file to write stdout and stderr of workers to.
            (Daemonized arbiter process no longer has a stdout to write
            to.)  Defaults to "out.txt".
        '''
        if spawn_daemon(self.fork, pgrpfile, outfile):
            return
        signal.signal(signal.SIGTERM, lambda signal, frame: self.stop())
        self.run(False)

    def log_children(self):
        while True:
            try:
                worker_ios = dict((worker.child_io, worker)
                                  for worker in self.workers.values())
                try:
                    readable, _, _ = select.select(worker_ios,
                                                   [], [], 0.1)
                except ValueError:
                    # one of the workers died after worker_ios was
                    # created but before select started, and we were
                    # monitoring some python *socket* object it owned.
                    continue
                except OSError as e:
                    if e.errno == errno.EBADF:
                        # one of the workers died after worker_ios was
                        # created but before select started, and we
                        # were monitoring some *integer* file
                        # descriptor it owned.
                        continue
                    else:
                        raise
                else:
                    for worker_io in readable:
                        # there should never be a key error here, because
                        # nothing alters workers_ios
                        worker_ios[worker_io].parent_print_io()
            except Exception:
                self.printfunc(
                    "error in arbiter's log_children:\n"
                    + traceback.format_exc())

    def _ensure_pgrp(self):
        """Ensures that the pgrp file is present and up to date. There have
        been production cases where the file was lost or not
        immediately emitted due to disk space issues.
        """
        if not LAST_PGRP_PATH:  # global
            return
        try:
            with open(LAST_PGRP_PATH, 'w') as f:
                f.write(str(os.getpgrp()) + "\n")
        except IOError:
            # raised if no permissions or disk space
            pass

    def run(self, repl=True):
        self.workers = {}
        if repl:
            self.stdin_handler = StdinHandler(self)
            self.stdin_handler.start()
        else:
            self.stdin_handler = None
        self.stopping = False  # for manual stopping
        self.dead_workers = deque(maxlen=10)

        self.io_log_thread = threading.Thread(target=self.log_children)
        self.io_log_thread.daemon = True
        self.io_log_thread.start()

        try:
            self.printfunc('starting arbiter ' + repr(self) + ' ' + str(os.getpid()))
            while not self.stopping:
                self.no_ping_children = set(
                    [e for e in self.no_ping_children if e.last_update is None])
                #spawn additional workers as needed
                for worker_id in range(self.size):
                    if worker_id in self.workers:
                        continue
                    if len(self.no_ping_children) >= self.max_no_ping_children:
                        break
                    worker = Worker(self, worker_id)
                    worker.fork_and_run()
                    self.printfunc('started worker ' + str(worker.pid))
                    self.workers[worker_id] = worker
                    self.no_ping_children.add(worker)
                self._cull_workers()
                self._reap()
                time.sleep(1.0)
                if int(time.time()) % 30 == 0:
                    self._ensure_pgrp()
        except Exception:
            self.printfunc('arbiter loop exiting due to: ' + traceback.format_exc())
        else:
            self.printfunc('aribter loop exiting without exception, self.stopping=' + repr(self.stopping))
        finally:
            if not self.in_child:  # just let child SystemExit raise
                try:
                    self._shutdown_all_workers()
                except:
                    self.printfunc("warning, arbiter shutdown had exception: " + traceback.format_exc())
                finally:
                    if repl:
                        self.stdin_handler.stop()
                    else:
                        raise SystemExit()  # in case arbiter was daemonized, exit here

    def _shutdown_all_workers(self):
        self.printfunc('shutting down arbiter ' + repr(self))
        if self.parent_pre_stop:
            self.parent_pre_stop()  # hope this doesn't error
        #give workers the opportunity to shut down cleanly
        for worker in self.workers.values():
            worker.parent_notify_stop()
        shutdown_time = time.time()
        while self.workers and time.time() < shutdown_time + TIMEOUT:
            self._cull_workers()
            self._reap()
            time.sleep(1.0)
        #if workers have not shut down cleanly by now, kill them
        for w in self.workers.values():
             w.parent_kill()
        self._reap()

    def _cull_workers(self):  # remove workers which have died from self.workers
        for worker_id, worker in self.workers.items():
            if not worker.parent_check():
                # don't leak sockets
                worker.child_io.close()
                worker.child_health.close()
                del self.workers[worker_id]

    def _reap(self):
        try:  # reap dead workers to avoid filling up OS process table
            res = os.waitpid(-1, os.WNOHANG)
            while res != (0, 0):
                name = EXIT_CODE_NAMES.get(res[1])
                self.printfunc('worker {0} exit status {1} ({2})'.format(
                    res[0], res[1], name))
                self.dead_workers.append(DeadWorker(res[0], res[1], name))
                res = os.waitpid(-1, os.WNOHANG)
        except OSError as e:
            if getattr(e, "errno", None) == 10:  # errno 10 is "no child processes"
                self.printfunc("all workers dead")
            else:
                self.printfunc("reap caught exception" + repr(e))

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


def spawn_daemon(fork=None, pgrpfile=None, outfile='out.txt'):
    'causes run to be executed in a newly spawned daemon process'
    global LAST_PGRP_PATH
    fork = fork or os.fork
    open(outfile, 'a').close()  # TODO: configurable output file
    if pgrpfile and os.path.exists(pgrpfile):
        try:
            cur_pid = int(open(pgrpfile).read().rstrip("\n"))
            os.killpg(cur_pid, 0)
            raise Exception("arbiter still running with pid:" + str(cur_pid))
        except (OSError, ValueError):
            pass
    if fork():  # return True means we are in parent
        return True
    else:
        os.setsid()  # break association with terminal via new session id
        if fork():  # fork one more layer to ensure child will not re-acquire terminal
            os._exit(0)
        LAST_PGRP_PATH = pgrpfile
        if pgrpfile:
            with open(pgrpfile, 'w') as f:
                f.write(str(os.getpgrp()) + "\n")
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
LAST_PGRP_PATH = None
