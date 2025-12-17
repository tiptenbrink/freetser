# Changelog

All notable changes to this project will be documented in this file.

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
