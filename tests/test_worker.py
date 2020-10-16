import os
import time
import threading
import thread

import ufork


def suicide_worker():
    print "suicide worker started"

    def die_soon():
        time.sleep(2)
        print "suicide worker dieing"
        thread.interrupt_main()  # sys.exit(0)

    suicide_thread = threading.Thread(target=die_soon)
    suicide_thread.daemon = True
    suicide_thread.start()


def test_worker_cycle_test():
    arbiter = ufork.ufork.Arbiter(post_fork=suicide_worker)
    arbiter_thread = threading.Thread(target=arbiter.run)
    arbiter_thread.daemon = True
    arbiter_thread.start()
    time.sleep(6)  # give some time for workers to die
    arbiter.stopping = True
    arbiter_thread.join()
    time.sleep(1)  # give OS a chance to finish killing all child workers
    assert arbiter.dead_workers
    print arbiter.dead_workers
    leaked_workers = []
    for worker in arbiter.workers.values():
        try:  # check if process still exists
            os.kill(worker.pid, 0)
            leaked_workers.append(worker.pid)
        except OSError:
            pass  # good, worker dead
    if leaked_workers:
        raise Exception("leaked workers: " + repr(leaked_workers))