uFork
=====

<a href="https://pypi.org/project/ufork/"><img src="https://img.shields.io/pypi/v/ufork.svg"></a>
<a href="https://calver.org/"><img src="https://img.shields.io/badge/calver-YY.MM.MICRO-22bfda.svg"></a>

A lightweight, pure-Python, pre-forking container.

Features:

* gevent supported (but not required)
* REPL compatibility
   a) start your server at the REPL
   b) get a special ufork>> interactive prompt while the server is runnign
   c) shut down the server at the REPL with Ctrl-C, just like breaking out of any other loop; workers will cleanly shutdown
* daemonization
* worker health monitoring


Example usage:

```python
>>> def wsgi_hello(environ, start_response):
...     start_response('200 OK', [('Content-Type', 'text/plain')])
...     yield 'Hello World\n'
...
>>> serve_wsgi_gevent(wsgi_hello, ('0.0.0.0', 7777))
ufork>>arbiter
<ufork.Arbiter object at 0x7f8f560e6250>
ufork>>^CTraceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "ufork.py", line 179, in serve_wsgi_gevent
    arbiter.run()
  File "ufork.py", line 120, in run
    time.sleep(1.0)
KeyboardInterrupt
>>>
```

See `example.py` for more.

Why uFork?
==========

Why was uFork written, and why should you consider using it?

uFork was written because existing WSGI containers make it
difficult to control process lifetime and socket behavior.
 To address this, uFork puts maximum control in the hands of the library user.

The basic API is an Arbiter object, which must be initialized
 with a post-fork function.  The arbiter does not know about sockets,
 doesn't know or care how the process was started.  In fact, the
  arbiter can even be run from the Python REPL.

Another primary goal of uFork is to provide high visibility into running processes.
Toward this end, standard out of forked workers is captured and echoed into
the arbiter process.  Further, if the arbiter process is daemonized,
stdout and stderr are captured to a (rotating) logfile.


uFork versus Gunicorn
=====================
Gunicorn is an application framework.  This means it is designed to own
the entire process.  Gunicorn involves itself in application configuration,
socket management, logging, and signal handling.

uFork on the other hand is a library focused on only one thing:
demonizing and keeping pre-forked processes running.  This makes
the library much smaller (~500 lines versus ~20k lines).


uFork versus os.fork()
======================
The os.fork() function does an excellent job of making the internals
of the Python runtime compatible with forking.  However, there are
a number of pitfalls:

* unless explicitly exited, forked processes will return to the same
call stack as the root

* random numbers will be the same in all forks unless explicitly
re-seeded

* forked processes will all read and write to the same
 stdin / stdout / stderr
