# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0]

### Breaking Changes

- **Strict `update()` semantics**: The old `assert_updated` option has been replaced by two separate methods. `Storage.update()` is now always strict and raises `UpdateCounterMismatch` when the counter does not match. Use `Storage.try_update()` when a stale counter is expected and should return `False`.
- **Non-`StorageError` procedure exceptions now kill the storage thread**: If a procedure passed to `StorageQueue.execute()` raises an exception that is not a `StorageError`, that call now raises the original exception and the storage thread stops. Later calls to `execute()` raise `StorageThreadCrashed`. `StorageError` exceptions remain recoverable.

### Added

- `Storage.try_update()`: Non-throwing optimistic-locking update that returns `True` on success and `False` on counter mismatch.
- `UpdateCounterMismatch`: Raised by `Storage.update()` when the optimistic-lock counter does not match.
- `StorageThreadCrashed`: Raised when calling `StorageQueue.execute()` after the storage thread has already crashed.
- `Storage.overwrite()`: Unconditional insert-or-replace primitive for last-writer-wins rows such as caches, indexes, and other derived state. It inserts missing keys, replaces existing values without a counter check, and increments the counter when replacing an existing row.

### Changed

- **Startup failure propagation**: `start_storage_thread()` now raises startup errors directly instead of potentially blocking forever if the storage thread fails during initialization.
- **Rollback failure chaining**: If a procedure raises and `rollback()` also fails, the rollback error is raised with the original procedure error as its direct cause.
- **Self-contained test suite**: `uv run pytest` now starts the required test server automatically, and CI no longer launches a separate background server first.
- README examples now have matching tests in `test_readme_examples.py`. 

## [0.4.1]

### Added

- **TCP keepalive**: `TcpServerConfig` now enables TCP keepalive by default, with configurable idle time (`tcp_keepalive_time`, default 60s), probe interval (`tcp_keepalive_intvl`, default 10s), and probe count (`tcp_keepalive_probes`, default 3). This detects dead peers (e.g. client crash, network drop) much faster than the OS default of 2 hours.
- **TCP_NODELAY**: Nagle's algorithm is now disabled by default (`tcp_nodelay=True`), potentially reducing latency on small HTTP responses.
- **TCP_USER_TIMEOUT**: Configurable timeout (`tcp_user_timeout`, default 90s) for unacknowledged data, closing the gap where keepalive doesn't fire during active retransmission.

## [0.3.2]

### Added

- **Free-threaded Python check**: freetser now checks on import that the GIL is disabled and exits with a clear error message if not. This prevents confusing runtime errors when accidentally using a non-free-threaded build.
- **`py.typed` marker**: Added PEP 561 marker file so type checkers recognize freetser as a typed package.

### Changed

- **Type checker migration**: Switched from basedpyright to [ty](https://github.com/astral-sh/ty) for type checking.
- **Test port**: Test server now defaults to port 8020 (configurable via `FREETSER_TEST_PORT` environment variable) to avoid conflicts with running applications.

## [0.3.1]

### Changed

- **Improved connection logging**: Connection logs now include the server's listening address, making it easier to identify which server instance received a connection when running multiple freetser instances.

  **TCP:**
  ```
  [127.0.0.1:8000] Connection from 127.0.0.1:36954
  ```

  **Unix socket:**
  ```
  [unix:/tmp/myserver.sock] Connection from unix socket
  ```

## [0.3.0]

### Breaking Changes

- **`ServerConfig` split into `TcpServerConfig` and `UnixServerConfig`**: The base `ServerConfig` class now only contains shared settings. Use `TcpServerConfig` for TCP sockets or `UnixServerConfig` for Unix domain sockets.

  **Before:**
  ```python
  config = ServerConfig(host="127.0.0.1", port=8000)
  start_server(config, handler)
  ```

  **After (TCP):**
  ```python
  config = TcpServerConfig(host="127.0.0.1", port=8000)
  start_server(config, handler)
  ```

  **After (Unix domain socket):**
  ```python
  config = UnixServerConfig(path="/tmp/myserver.sock")
  start_server(config, handler)
  ```

### Added

- `TcpServerConfig`: Configuration class for TCP sockets with `host` and `port` fields.
- `UnixServerConfig`: Configuration class for Unix domain sockets with `path` field.
- Unix domain socket support: The server can now listen on a Unix domain socket instead of a TCP socket.

## [0.2.0]

### Breaking Changes

- **Storage thread management decoupled from server startup**: Users must now start the storage thread themselves using `start_storage_thread()` and pass the returned `StorageQueue` to `start_server()`.

  **Before:**
  ```python
  config = ServerConfig(db_file="mydb.sqlite", db_tables=["USERS"])
  start_server(config, handler)
  ```

  **After:**
  ```python
  store_queue = start_storage_thread(db_file="mydb.sqlite", db_tables=["USERS"])
  config = ServerConfig()
  start_server(config, handler, store_queue=store_queue)
  ```

- **Removed `db_file` and `db_tables` from `ServerConfig`**: These parameters are now passed directly to `start_storage_thread()`.

### Added

- `start_storage_thread(db_file, db_tables)`: New function that starts the storage thread and returns a `StorageQueue`. This function blocks until the storage thread is fully initialized and ready to accept requests.
- `StorageQueue` is now exported from the main `freetser` module (previously only available via `freetser.server`).

### Changed

- `start_server()` now accepts an optional `store_queue` parameter instead of creating the storage thread internally.
- `start_storage_thread()` blocks until the database connection is established and tables are created, ensuring the queue is ready for use immediately upon return.
