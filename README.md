uFork
=====

a lightweight, pure python, pre-forking container

Features:

* gevent supported (but not required)
* REPL compatibility
   a) start your server at the REPL
   b) get a special ufork>> interactive prompt while the server is runnign
   c) shut down the server at the REPL with Ctrl-C, just like breaking out of any other loop; workers will cleanly shutdown

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

Why uFork?
==========

Why was uFork written, and why should you consider using it?

uFork was written because existing WSGI containers make it difficult to control process lifetime and socket behavior.  To address this, uFork puts maximum control in the hands of the library user.

The basic API is an Arbiter object, which must be initialized with a post-fork function.  The arbiter does not know about sockets, doesn't know or care how the process was started.  In fact, the arbiter can even be run from the Python REPL.

Another primary goal of uFork is to provide high visibility into running processes.