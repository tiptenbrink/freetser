# freetser

**freetser** is a **free**-**t**hreaded HTTP/1.1 **ser**ver for Python 3.14t+. It requires a free-threaded build of Python (GIL disabled) and provides a built-in SQLite-backed key-value storage layer. The only external dependency is [h11](https://github.com/python-hyper/h11), a pure Python sans-IO HTTP/1.1 library.

The SQLite storage layer uses a single thread that can execute Python functions, which makes it easy to think about concurrency. It also supports optimistic concurrency.

## When to use freetser

freetser is **not a web framework**. It's an extremely lightweight HTTP server layer + storage layer that you build on top of. There is no routing, no middleware, no CORS handling, no cookie parsing, no authentication—just raw requests and responses.

**Good fit:**
- You want a minimal foundation to build your own abstractions on
- Simple synchronous code that's easy to understand and debug
- Small to medium scale applications with built-in persistent storage
- Internal tools, personal projects, or learning projects

**Not a good fit:**
- You want batteries-included features (routing, auth, CORS, sessions, etc.)
- High-concurrency applications (use async frameworks instead)
- CPU-bound workloads in request handlers (blocks the connection thread)
- Applications requiring complex database queries (use a proper ORM)
- When you need WebSocket support or HTTP/2

## Architecture

- **Thread-per-connection**: each client connection runs in its own thread (no thread pool, no async)
- **Single storage thread**: all database operations go through one thread via a queue, ensuring serialized access
- **Keep-alive support**: connections are reused for multiple requests via HTTP/1.1 keep-alive
- **TCP and Unix sockets**: supports both `TcpServerConfig` and `UnixServerConfig`

## Quick start

Ensure you have a **free-threaded** build of Python. With [uv](https://github.com/astral-sh/uv):

```bash
uv python pin 3.14t
uv add freetser
```

Create `main.py`:

```python
from freetser import Request, Response, TcpServerConfig, setup_logging, start_server

def handler(req: Request, store_queue) -> Response:
    if req.path == "/":
        return Response.text("Hello world!")
    return Response.text("Not found!", status_code=404)

def main():
    listener = setup_logging()
    listener.start()
    try:
        start_server(TcpServerConfig(port=8000), handler)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        listener.stop()

if __name__ == "__main__":
    main()
```

Run with `uv run main.py`.

## API reference

### Server configuration

```python
from freetser import TcpServerConfig, UnixServerConfig

# TCP socket (default)
config = TcpServerConfig(
    host="127.0.0.1",      # default
    port=8000,             # default
    max_header_size=16384, # 16 KB, default
    max_body_size=2097152, # 2 MB, default
    listen_backlog=1024,   # default
)

# Unix domain socket (not supported on Windows)
config = UnixServerConfig(
    path="/tmp/freetser.sock",  # default
)
```

### Request and Response

```python
from freetser import Request, Response

def handler(req: Request, store_queue) -> Response:
    # Request fields
    req.method   # str: "GET", "POST", etc.
    req.path     # str: "/api/users"
    req.headers  # list[tuple[bytes, bytes]]
    req.body     # bytes

    # Response factory methods
    return Response.text("Hello", status_code=200)
    return Response.json({"key": "value"}, status_code=200)
    return Response.empty(status_code=204)
```

### Storage

The built-in storage is a key-value store backed by SQLite. All operations run on a single dedicated thread.

```python
from freetser import Storage, StorageQueue, start_storage_thread, start_server

# Start storage thread before server
store_queue = start_storage_thread(
    db_file="mydb.sqlite",      # or ":memory:" for in-memory
    db_tables=["USERS", "SESSIONS"],  # tables to create
)

# Pass to server
start_server(config, handler, store_queue=store_queue)
```

In your handler, execute database operations via the queue:

```python
def handler(req: Request, store_queue: StorageQueue) -> Response:
    # This function runs on the database thread!
    def get_user(store: Storage) -> tuple[bytes, int] | None:
        return store.get("USERS", "user123")

    result = store_queue.execute(get_user)
    if result is None:
        return Response.text("Not found", status_code=404)

    value, counter = result
    return Response.json({"data": value.decode()})
```

#### Storage methods

```python
# Get a value (returns (value, counter) or None)
store.get(table: str, key: str, timestamp=None) -> tuple[bytes, int] | None

# Add a new key (raises EntryAlreadyExists if key exists)
store.add(table: str, key: str, value: bytes, expires_at=0, timestamp=None) -> None

# Update existing key with optimistic locking (raises on counter mismatch)
store.update(table: str, key: str, value: bytes, counter: int, expires_at=0) -> None

# Try to update existing key with optimistic locking
store.try_update(table: str, key: str, value: bytes, counter: int, expires_at=0) -> bool

# Overwrite without checking the counter (insert if missing)
store.overwrite(table: str, key: str, value: bytes, expires_at=0) -> None

# Delete a key
store.delete(table: str, key: str) -> bool

# List all keys in a table
store.list_keys(table: str) -> list[str]

# Clear all entries in a table
store.clear(table: str) -> None
```

The `counter` field enables optimistic locking. Since procedures run sequentially on a single thread, there are no race conditions *within* a procedure. However, if you read a value, return to the handler to do external work (like an HTTP call), and then update in a *separate* procedure call, another request's procedure may have modified the value in between. Use `try_update()` when a stale counter is part of normal control flow and you want a `bool` result. Use `update()` when a stale counter should be treated as an exception via `UpdateCounterMismatch`.

`overwrite()` is different: it inserts missing keys, and if the key already exists it replaces the stored value and expiration without checking the counter. When overwriting an existing key it still increments the counter, so readers can observe that the row changed. Use it for cache rows, indexes, or other derived data where the latest write should simply win. Do not use it when you need to detect that another callback changed an important value in between.

The `expires_at` and `timestamp` parameters enable TTL-based expiration. Set `expires_at` to a Unix timestamp when adding/updating, then pass the current timestamp when getting to filter expired entries.

### Storage best practices

1. **Keep routines simple**: The storage thread is single-threaded. Don't make HTTP calls or perform heavy computation inside storage routines.

2. **Use `overwrite()` only for last-writer-wins data**: `overwrite()` is useful for derived rows such as caches or indexes when you are intentionally replacing whatever was there before. If another callback's change would be important, do not use `overwrite()`.

```python
def refresh_profile_cache(store: Storage, user_id: str, profile_bytes: bytes) -> None:
    # Cache data is derived state. We intentionally want the latest write to win.
    store.overwrite("CACHE", f"profile:{user_id}", profile_bytes, expires_at=300)
```

3. **Use `try_update()` for expected conflicts**: If a counter mismatch is part of normal request handling, use `try_update()` and handle the `False` result in the handler. Reserve `update()` for situations where a mismatch is truly exceptional.

4. **`StorageError` is recoverable, other exceptions are fatal**: If a procedure raises a `StorageError` such as `EntryAlreadyExists` or `UpdateCounterMismatch`, the storage thread rolls back, `execute()` raises that exception to the caller, and the storage thread continues. If a procedure raises any other exception, the storage thread rolls back, the triggering `execute()` call raises that exception, and the storage thread stops. Later calls to `execute()` raise `StorageThreadCrashed`. If rollback itself fails, that rollback error is raised and chained from the original procedure error.

5. **Use optimistic locking for split operations**: When you need to read, do external work, then update, use the counter to detect concurrent modifications:

```python
def handler(req: Request, store_queue: StorageQueue) -> Response:
    # First procedure: read the current value
    def get_data(store: Storage):
        return store.get("DATA", "key")

    result = store_queue.execute(get_data)
    if result is None:
        return Response.text("Not found", status_code=404)

    value, counter = result

    # Do external work in the handler (another procedure might run here!)
    new_value = call_external_api(value)

    # Second procedure: update only if counter still matches
    def save_data(store: Storage):
        return store.try_update("DATA", "key", new_value, counter)

    if store_queue.execute(save_data):
        return Response.text("Updated")
    return Response.text("Conflict - try again", status_code=409)
```

## Patterns

### Sharing storage between multiple servers

You can run multiple servers (e.g., public and internal) sharing one storage thread:

```python
import threading
from freetser import (
    TcpServerConfig, UnixServerConfig,
    start_server, start_storage_thread
)

def public_handler(req, store_queue):
    # Handle public API requests
    ...

def internal_handler(req, store_queue):
    # Handle internal/admin requests
    ...

def main():
    # Single storage thread shared by both servers
    store_queue = start_storage_thread("app.sqlite", ["USERS", "SESSIONS"])

    # Public API on TCP port
    public_config = TcpServerConfig(host="0.0.0.0", port=8080)
    threading.Thread(
        target=start_server,
        args=(public_config, public_handler),
        kwargs={"store_queue": store_queue},
        daemon=True,
    ).start()

    # Internal API on Unix socket (not exposed to network)
    internal_config = UnixServerConfig(path="/var/run/app-internal.sock")
    start_server(internal_config, internal_handler, store_queue=store_queue)
```

### Simple routing

```python
def handler(req: Request, store_queue) -> Response:
    if req.method == "GET" and req.path == "/users":
        return list_users(store_queue)
    if req.method == "POST" and req.path == "/users":
        return create_user(req, store_queue)
    if req.method == "GET" and req.path.startswith("/users/"):
        user_id = req.path.split("/")[-1]
        return get_user(user_id, store_queue)
    return Response.text("Not found", status_code=404)
```

### Error handling

```python
from freetser import EntryAlreadyExists, StorageThreadCrashed

def handler(req: Request, store_queue) -> Response:
    try:
        def create_user(store):
            store.add("USERS", req.body.decode(), b"{}", 0)
            return "created"

        result = store_queue.execute(create_user)
        return Response.text(result, status_code=201)

    except EntryAlreadyExists:
        return Response.text("User already exists", status_code=409)
    except StorageThreadCrashed:
        return Response.text("Storage thread crashed", status_code=500)
```

If a procedure raises a `StorageError`, that exception is raised back out of `store_queue.execute()` and the storage thread continues running. If a procedure raises any other exception, that exception is raised back out of `store_queue.execute()`, and after that the storage thread is no longer usable and future calls raise `StorageThreadCrashed`. For normal control flow, returning status values from the procedure or using non-throwing APIs like `try_update()` is often still clearer.

### Fatal Procedure Errors

Avoid raising plain exceptions from storage procedures for normal control flow. A non-`StorageError` is treated as a bug or broken invariant:

1. The current transaction is rolled back.
2. The `execute()` call that triggered the problem raises the original exception.
3. Any callers already queued behind it wake up and raise `StorageThreadCrashed`.
4. Future calls to `execute()` immediately raise `StorageThreadCrashed`.

```python
import threading
from freetser import Storage, StorageQueue, StorageThreadCrashed

def demonstrate_fatal_error(store_queue: StorageQueue) -> None:
    procedure_started = threading.Event()
    allow_crash = threading.Event()

    def crash(store: Storage) -> None:
        procedure_started.set()
        allow_crash.wait()
        raise ValueError("bug in procedure")

    def first_caller() -> None:
        try:
            store_queue.execute(crash)
        except ValueError:
            print("first caller got the original exception")

    def second_caller() -> None:
        procedure_started.wait()
        try:
            store_queue.execute(lambda store: "never runs")
        except StorageThreadCrashed:
            print("second caller woke up after the crash")

    threading.Thread(target=first_caller, daemon=True).start()
    threading.Thread(target=second_caller, daemon=True).start()
    allow_crash.set()
```

In that example, the second caller does not block forever. It is waiting on its own `execute()` call, notices that the storage thread died, and is woken up with `StorageThreadCrashed`. That is why plain exceptions inside procedures should be reserved for actual bugs or irrecoverable invariants, not expected request outcomes.

## Development

```bash
uv run ruff check      # Linting
uv run ruff format     # Code formatting
uv run ty check        # Type checking
```

Run tests:

```bash
uv run pytest
```

## Benchmarks

In some basic stress testing on a local machine and with TCP_NODELAY and default settings, average request latency is sub-ms with a mix of reads, updates and deletes (1:1:1 ratio) achieving 6k requests per second with a single connection thread. Note that on a local machine, if TCP_NODELAY is not set a request would basically always take at least 40ms on my machine, although when using >100 threads throughput was usually better, although again not always. Using default settings should be fine when you are using freetser for what it was designed: low-concurrency web servers with modest traffic. 

However, throughput can rise all the way to 20,000 requests per second (using 100 request threads firing off requests on a keep-alive connection), although average request-response times climb to 5ms.

When using more than 100 threads, contention starts to become a serious problem and request throughput starts to fall, although note that in this simple benchmark we're just logging every request to the terminal as well, I did not do extensive investigation to reduce bottlenecks.

Benchmark machine specs: Intel Core Ultra 7 155H (22 vCPUs), Linux 6.18, 32GB LPDDR5x-7467 memory

## Background

I wanted to minimize dependencies and use the standard library's sqlite3 interface. However, sqlite3 is not made for async. Therefore, I wanted a synchronous web server. However, while there exists projects like Flask and Bottle, I simply could not grok how to easily integrate them with sqlite3. Furthermore, they are not designed to utilize Python's recent free-threaded build.

Most of all, I wanted a project where everyone can read the code and understand what it's doing, while also providing a built-in storage mechanism so you can use it for small-scale production use cases.

Claude Code (Opus 4.5, 4.6) and Codex (GPT 5.4) were used significantly in the development of freetser. All architectural decisions were made by a human, and all code has been reviewed and vetted by a human.
