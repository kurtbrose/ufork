from __future__ import absolute_import
import os
import signal


def check_leaked_workers(arbiter):
    leaked_workers = []
    for worker in arbiter.workers.values():
        try:  # check if process still exists
            os.kill(worker.pid, signal.SIGKILL)
            leaked_workers.append(worker.pid)
        except OSError:
            pass  # good, worker dead
    if leaked_workers:
        raise Exception("leaked workers: " + repr(leaked_workers))
