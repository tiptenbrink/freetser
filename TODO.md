# HTTP Client Refactor Plan

## Rename

Rename `http.py` module to `client.py`.

## Design

### ConnectionPool is per-address

Create a pool for a specific server address. The pool manages multiple connection threads to that address.

```python
@dataclass
class TcpAddress:
    host: str = "127.0.0.1"
    port: int = 8000

@dataclass
class UnixAddress:
    path: str
```

### Pool has connection limit

```python
pool = ConnectionPool(address, max_connections=4)
```

### Threading model

- Pool contains multiple connection threads (up to `max_connections`)
- Each thread maintains a persistent HTTP connection
- Threads keep connection alive until pool is closed
- When `pool.get()` / `pool.post()` is called:
  - Find an available thread (not busy)
  - If none available and under limit: create new connection thread
  - If at limit: wait for a thread to become available
- Request is queued to the chosen thread, caller waits for response

## Expected Usage

```python
from freetser import client

# Create pool for a specific address
tcp_pool = client.ConnectionPool(client.TcpAddress("127.0.0.1", 8000), max_connections=4)
unix_pool = client.ConnectionPool(client.UnixAddress("/tmp/server.sock"), max_connections=2)

# Make requests - pool manages connections
response = tcp_pool.get("/api/users")
response = tcp_pool.post("/api/users", body=b'{"name": "Alice"}')

response = unix_pool.post("/command", body=b'{"cmd": "reset"}')

# Close pools when done
tcp_pool.close()
unix_pool.close()
```

## Files to Update

- `src/freetser/http.py` → rename to `src/freetser/client.py`
- `src/freetser/__init__.py` - Export new classes
- `tests/test_client.py` - Update for new API
- `tests/smoke_test.py` - Update imports
