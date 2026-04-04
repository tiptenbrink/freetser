import sys

if sys._is_gil_enabled():
    print(
        "ERROR: Free-threading is disabled (GIL is enabled). "
        "freetser requires a free-threaded build of Python (preferably 3.14t+).",
        file=sys.stderr,
    )
    sys.exit(1)

from .server import (
    Request,
    Response,
    ServerConfig,
    StorageThreadCrashed,
    StorageQueue,
    TcpServerConfig,
    UnixServerConfig,
    setup_logging,
    start_server,
    start_storage_thread,
)
from .storage import (
    EntryAlreadyExists,
    Storage,
    StorageError,
    UpdateCounterMismatch,
)

__all__ = [
    "start_server",
    "start_storage_thread",
    "ServerConfig",
    "TcpServerConfig",
    "UnixServerConfig",
    "StorageThreadCrashed",
    "StorageQueue",
    "Request",
    "Response",
    "setup_logging",
    "Storage",
    "StorageError",
    "EntryAlreadyExists",
    "UpdateCounterMismatch",
]
