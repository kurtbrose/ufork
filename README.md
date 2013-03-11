ufork
=====

a small, lightweight pre-forking container

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