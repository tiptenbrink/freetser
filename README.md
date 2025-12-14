# freetser

**freetser** is a **free**-**t**hreaded HTTP/1.1 **ser**ver, i.e. it relies on a free-threaded build of Python where the GIL is disabled. Furthermore, it provides a built-in KV storage layer (which uses SQLite under the hood). It has only a single dependency outside the standard library, the wonderful pure Python sans IO-style HTTP/1.1 library known as [h11](https://github.com/python-hyper/h11).

It aims to be a very simple synchronous web server that should work for a lot of projects that do not require multiple thousands of requests per second, although with a lot of cores and threads it can actually achieve about 10,000 requests per second on an untuned Linux system.

## Architecture

- Thread-per-connection (no thread pool), **no async**
- Uses a pure Python HTTP/1.1 library (h11)
- `socket` from the standard library for the actual TCP reading/writing
- Single SQLite database thread (using `sqlite3` from the standard library), other threads simply send Python functions through a queue for it to execute

## Quick start

Ensure you are using a **free-threaded** build of Python, see [documentation here](https://docs.python.org/3/howto/free-threading-python.html). If using [`uv`](https://github.com/astral-sh/uv), which I highly recommend, you could use `uv python pin 3.14t` (where the `t` stands for the free-threaded version).

Then, install `freetser` from PyPI with `uv add freetser`. 

Finally, create a Python script (e.g. `main.py`) with the following code:

```python
import logging

from freetser import (
    Request,
    Response,
    ServerConfig,
    Storage,
    setup_logging,
    start_server,
)
from freetser.server import StorageQueue

logger = logging.getLogger("freetser.handler")

def handler(req: Request, store_queue: StorageQueue | None) -> Response:
    if req.path == "/":
        return Response.text("Hello world!")

    return Response.text("Not found!", status_code=404)


def main():
    listener = setup_logging()
    listener.start()

    config = ServerConfig(port=8000)
    try:
        start_server(config, handler)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
```

Then if you do `uv run main.py`, it will start the server on the default port of 8000.

## Using the built-in storage

`freetser` provides a built-in key-value (KV) store built on top of SQLite. It is not designed for speed, but for simplicity. First, define a database routine:

```python
def get_or_create(store: Storage) -> str:
    key = "my_user_email"
    result = store.get("USERS", key)
    if result is None:
        value = b"my.user@freetser.com"
        store.add("USERS", key, value, 0)
        return f"Created: {key}\n"
    else:
        value, counter = result
        return f"Found: {key}, counter={counter}\n"
```

A database routine is simply a Python function or lambda that takes a `Storage` argument. Then, in your handler, call `result = store_queue.execute(get_or_create)`. The server will then execute this function on the database thread in a transaction, ensuring it either succeeds or fails. 

This has some important consequences:
- If any non-expected database error occurs (i.e. it does not derive from `StorageError`), the database thread will crash and the server will have to be restarted.
- Therefore, you should **not** throw when you encounter application errors inside the routine, but instead return a value and handle the error in the handler. You can even just raise the error there, as when errors occur in the handler the server will simply return a 500 Internal Server Error but not crash (since the error is raised in the connection thread). 
- Furthermore, try to only perform simple logic in the routines. Since we only have 1 database thread, all other threads have to wait on your routine to finish. So don't make any HTTP calls or other blocking requests. Put those in the handler instead. If this is a limitation, **don't use this library**. This library is explicitly not designed for highly concurrent use cases or high performance applications with hundreds of thousands of users. However, it should handle thousands just fine.

For more examples, see `main.py` in the tests directory or check out the tests themselves.

## Benchmarks

In some basic stress testing on a local machine, we found that requests basically always take around 41-42 ms, giving a basic 25 requests per second. Note that we always perform at least a single SQLite operation, so every request has to go through the database thread.

However, throughput can rise all the way to 5500 requests per second (using 300 request threads firing off requests on a keep-alive connection) without any real hit to latency, with requests still taking around 43 ms to complete on average (and at most 160 ms, hats off to the OS scheduler). From that point on, average request times start to climb as you add threads.

Using 750 threads, throughput reaches 10,000 requests per second with an average request taking 53 ms. Using 1000 threads barely helps as throughput starts to level off rapidly, reaching 10,900 requests per second. 1200 threads wasn't possible to test without tuning OS settings.

Benchmark machine specs: Intel Core Ultra 7 155H (22 vCPUs), Linux 6.17, 32GB LPDDR5x-7467 memory

## Background

I wanted to minimize dependencies and use the standard library's sqlite3 interface. However, sqlite3 is not made for async. Therefore, I wanted a synchronous web server. However, while there exists projects like Flask and Bottle, I simply could not grok how to easily integrate them with sqlite3. Furthermore, they are not designed to utilize Python's recent free-threaded build. 

Most of all, I wanted a project where everyone can read the code and understand what it's doing, while also providing a built-in storage mechanism so you can use it for small-scale production use cases.
