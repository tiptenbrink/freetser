# Changelog

All notable changes to this project will be documented in this file.

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
