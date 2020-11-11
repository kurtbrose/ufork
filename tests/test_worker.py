from __future__ import absolute_import

import sys
import time
import threading

try:
    import _thread as thread
except ImportError:
    import thread  # py3

from tests.utils import check_leaked_workers
from ufork import Arbiter


def suicide_worker():
    def die_soon():
        time.sleep(2)
        thread.interrupt_main()  # sys.exit(0)

    suicide_thread = threading.Thread(target=die_soon)
    suicide_thread.daemon = True
    suicide_thread.start()


def test_worker_cycle_test():
    arbiter = Arbiter(post_fork=suicide_worker)
    arbiter_thread = threading.Thread(target=arbiter.run, kwargs={"repl": False})
    arbiter_thread.daemon = True
    arbiter_thread.start()
    time.sleep(6)  # give some time for workers to die
    arbiter.stopping = True
    arbiter_thread.join()
    time.sleep(1)  # give OS a chance to finish killing all child workers
    assert arbiter.dead_workers

    check_leaked_workers(arbiter)
