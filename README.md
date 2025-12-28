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

# Update existing key with optimistic locking (counter must match)
store.update(table: str, key: str, value: bytes, counter: int, expires_at=0) -> bool

# Delete a key
store.delete(table: str, key: str) -> bool

# List all keys in a table
store.list_keys(table: str) -> list[str]

# Clear all entries in a table
store.clear(table: str) -> None
```

The `counter` field enables optimistic locking. Since procedures run sequentially on a single thread, there are no race conditions *within* a procedure. However, if you read a value, return to the handler to do external work (like an HTTP call), and then update in a *separate* procedure call, another request's procedure may have modified the value in between. Pass the counter to `update()` to detect this—if it doesn't match, the update fails and returns `False`.

The `expires_at` and `timestamp` parameters enable TTL-based expiration. Set `expires_at` to a Unix timestamp when adding/updating, then pass the current timestamp when getting to filter expired entries.

### Storage best practices

1. **Keep routines simple**: The storage thread is single-threaded. Don't make HTTP calls or perform heavy computation inside storage routines.

2. **Handle errors in the handler**: Return error values from routines instead of raising exceptions. Raise exceptions in the handler where they won't crash the storage thread.

3. **Use optimistic locking for split operations**: When you need to read, do external work, then update, use the counter to detect concurrent modifications:

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
        return store.update("DATA", "key", new_value, counter)

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
from freetser import StorageError, EntryAlreadyExists

def handler(req: Request, store_queue) -> Response:
    try:
        def create_user(store):
            store.add("USERS", req.body.decode(), b"{}", 0)
            return "created"

        result = store_queue.execute(create_user)
        return Response.text(result, status_code=201)

    except EntryAlreadyExists:
        return Response.text("User already exists", status_code=409)
    except StorageError as e:
        return Response.text(f"Storage error: {e}", status_code=500)
```

## Development

```bash
uv run ruff check      # Linting
uv run ruff format     # Code formatting
uv run ty check        # Type checking
```

Run tests:

```bash
uv run python tests/main.py &   # Start test server (optionally pass a port number)
uv run pytest tests/ -v         # Run tests
```

## Benchmarks

In some basic stress testing on a local machine, we found that requests basically always take around 41-42 ms, giving a basic 25 requests per second. Note that we always perform at least a single SQLite operation, so every request has to go through the database thread.

However, throughput can rise all the way to 5500 requests per second (using 300 request threads firing off requests on a keep-alive connection) without any real hit to latency, with requests still taking around 43 ms to complete on average (and at most 160 ms, hats off to the OS scheduler). From that point on, average request times start to climb as you add threads.

Using 750 threads, throughput reaches 10,000 requests per second with an average request taking 53 ms. Using 1000 threads barely helps as throughput starts to level off rapidly, reaching 10,900 requests per second. 1200 threads wasn't possible to test without tuning OS settings.

Benchmark machine specs: Intel Core Ultra 7 155H (22 vCPUs), Linux 6.17, 32GB LPDDR5x-7467 memory

## Background

I wanted to minimize dependencies and use the standard library's sqlite3 interface. However, sqlite3 is not made for async. Therefore, I wanted a synchronous web server. However, while there exists projects like Flask and Bottle, I simply could not grok how to easily integrate them with sqlite3. Furthermore, they are not designed to utilize Python's recent free-threaded build.

Most of all, I wanted a project where everyone can read the code and understand what it's doing, while also providing a built-in storage mechanism so you can use it for small-scale production use cases.

[Claude Code](https://github.com/anthropics/claude-code) with Opus 4.5 was used significantly in the development of freetser. All architectural decisions were made by a human, and all code has been reviewed and vetted by a human.
