import json
import logging
import queue
import socket
import sys
import threading
from dataclasses import dataclass, field
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import SimpleQueue
from typing import Callable, Optional, cast

import h11

import freetser.storage as storage

MAX_RECV = 2**16
logger = logging.getLogger("freetser.server")


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    max_header_size: int = 16 * 1024
    max_body_size: int = 2 * 1024 * 1024
    # Parameter passed to `socket.listen()`
    listen_backlog: int = 1024
    # Path to sqlite database file, will be created if it does not exist
    db_file: str | None = None
    # All tables that must be present, will be created if they do not exist
    db_tables: list[str] | None = None


@dataclass
class Request:
    method: str
    path: str
    headers: list[tuple[bytes, bytes]]
    body: bytes


@dataclass
class Response:
    status_code: int
    headers: list[tuple[bytes, bytes]]
    body: bytes

    @staticmethod
    def text(content: str, status_code: int = 200) -> "Response":
        body = content.encode("utf-8")
        return Response(
            status_code=status_code,
            headers=[
                (b"Content-Type", b"text/plain; charset=utf-8"),
                (b"Content-Length", str(len(body)).encode("ascii")),
            ],
            body=body,
        )

    @staticmethod
    def empty(
        headers: list[tuple[bytes, bytes]] | None = None, status_code: int = 200
    ) -> "Response":
        if headers is None:
            headers = []
        headers.append(
            (b"Content-Length", "0".encode("ascii")),
        )
        return Response(status_code=status_code, headers=headers, body=b"")

    @staticmethod
    def json(
        content,
        headers: list[tuple[bytes, bytes]] | None = None,
        status_code: int = 200,
    ) -> "Response":
        if headers is None:
            headers = []
        body = json.dumps(content).encode("utf-8")
        headers.append(
            (b"Content-Length", str(len(body)).encode("ascii")),
        )
        headers.append(
            (b"Content-Type", b"application/json"),
        )
        return Response(status_code=status_code, headers=headers, body=body)


@dataclass
class ConnectionContext:
    client_socket: socket.socket
    client_address: tuple
    store_queue: StorageQueue | None
    config: ServerConfig


def setup_logging() -> QueueListener:
    """Configures non-blocking logging via QueueHandler/QueueListener."""
    log_queue = queue.SimpleQueue()
    queue_handler = QueueHandler(log_queue)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(queue_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("[%(threadName)s] %(message)s"))

    listener = QueueListener(log_queue, console_handler)
    return listener


type Handler = Callable[[Request, StorageQueue | None], Response]


def handle_client(ctx: ConnectionContext, handler: Handler):
    logger.info(f"Connection from {ctx.client_address}")
    conn = h11.Connection(
        h11.SERVER, max_incomplete_event_size=ctx.config.max_header_size
    )

    try:
        while True:
            try:
                # This is where we actually handle the request and response
                if not handle_request_response(conn, ctx, handler):
                    break

                if (
                    conn.our_state is h11.MUST_CLOSE
                    or conn.their_state is h11.MUST_CLOSE
                ):
                    break

                if conn.our_state is h11.DONE and conn.their_state is h11.DONE:
                    conn.start_next_cycle()
                else:
                    break
            except h11.RemoteProtocolError as e:
                logger.error(f"Protocol error: {e}")
                send_error_response(conn, ctx, 400, f"Bad Request: {e}")
                break
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        ctx.client_socket.close()
        logger.info("Connection closed")


def handle_request_response(
    conn: h11.Connection, ctx: ConnectionContext, handler: Handler
) -> bool:
    event = get_next_event(conn, ctx.client_socket)
    if event is None:
        logger.debug("No event, ending request/response")
        return False

    if isinstance(event, h11.ConnectionClosed):
        return False

    if not isinstance(event, h11.Request):
        raise Exception(f"Unexpected event: {event}!")

    if event.http_version != b"1.1":
        logger.debug(f"Rejecting HTTP/{event.http_version.decode()}")
        send_error_response(conn, ctx, 505, "HTTP Version Not Supported")
        return False

    logger.info(f"{event.method.decode()} {event.target.decode()}")

    if conn.they_are_waiting_for_100_continue:
        logger.debug("Sending 100 Continue")
        ctx.client_socket.sendall(
            conn.send(h11.InformationalResponse(status_code=100, headers=[]))
        )

    try:
        request_body = read_request_body(conn, ctx)
    except ValueError as e:
        logger.error(f"Body too large: {e}")
        send_error_response(conn, ctx, 413, f"Payload Too Large: {e}")
        return False

    req = Request(
        method=event.method.decode(),
        path=event.target.decode(),
        headers=list(event.headers),
        body=request_body,
    )

    # Call the actual request handler that determines the response
    try:
        resp = handler(req, ctx.store_queue)
    except Exception as e:
        logger.error(f"Handler error: {e}")
        send_error_response(conn, ctx, 500, "Internal Server Error")
        # Close connection in case of internal server error
        return False

    send_response(conn, ctx, resp)
    return True


def get_next_event(conn: h11.Connection, sock: socket.socket) -> Optional[h11.Event]:
    while True:
        event = conn.next_event()
        # We shouldn't ever be paused here because then we didn't properly call start_next_cycle
        assert event is not h11.PAUSED
        if event is h11.NEED_DATA:
            try:
                data = sock.recv(MAX_RECV)
                # `receive_data` sees an empty `bytes` object as EOF, which matches `recv`
                conn.receive_data(data)
            except Exception as e:
                logger.error(f"Socket error: {e}")
                return None
        else:
            # We know it has to be Event in this case
            # Unfortunately the 'sentinel' stuff means the type checker cannot narrow properly
            return cast(h11.Event, event)


def read_request_body(conn: h11.Connection, ctx: ConnectionContext) -> bytes:
    """Throws ValueError if max body size is exceeded."""
    body_parts = []
    total_size = 0
    while True:
        event = get_next_event(conn, ctx.client_socket)
        if event is None:
            break
        if isinstance(event, h11.Data):
            total_size += len(event.data)
            if total_size > ctx.config.max_body_size:
                raise ValueError(f"Exceeded limit {ctx.config.max_body_size}")
            body_parts.append(event.data)
        elif isinstance(event, h11.EndOfMessage):
            break
    return b"".join(body_parts)


def send_error_response(
    conn: h11.Connection, ctx: ConnectionContext, status_code: int, message: str
):
    if conn.our_state not in {h11.IDLE, h11.SEND_RESPONSE}:
        return
    body = f"{status_code} Error: {message}\n".encode("utf-8")
    try:
        ctx.client_socket.sendall(
            conn.send(
                h11.Response(
                    status_code=status_code,
                    headers=[
                        (b"Content-Type", b"text/plain; charset=utf-8"),
                        (b"Content-Length", str(len(body)).encode("ascii")),
                        (b"Connection", b"close"),
                    ],
                )
            )
        )
        ctx.client_socket.sendall(conn.send(h11.Data(data=body)))
        ctx.client_socket.sendall(conn.send(h11.EndOfMessage()))
    except Exception as e:
        logger.error(f"Send error: {e}")


def send_response(conn: h11.Connection, ctx: ConnectionContext, response: Response):
    try:
        ctx.client_socket.sendall(
            conn.send(
                h11.Response(status_code=response.status_code, headers=response.headers)
            )
        )
        ctx.client_socket.sendall(conn.send(h11.Data(data=response.body)))
        ctx.client_socket.sendall(conn.send(h11.EndOfMessage()))
    except Exception as e:
        logger.error(f"Send error: {e}")


class UnsetType:
    """Sentinel value indicating that a value has not been set yet."""

    def __repr__(self):
        return "<UNSET>"


UNSET = UnsetType()


class StorageQueue:
    queue: SimpleQueue

    def __init__(self):
        self.queue = SimpleQueue()

    def execute[T](self, procedure: Callable[[storage.Storage], T]) -> T:
        """Execute the given function on the storage thread. Can raise a StorageException, in which case the execution was rolled back."""
        item: QueueItem[T] = QueueItem(procedure=procedure)
        self.queue.put(item)
        item.event.wait()
        # StorageException is caught by the database thread and returned
        if item.exception is not None:
            raise item.exception
        if isinstance(item.to_return, UnsetType):
            raise RuntimeError("Event signaled but value not set")
        return item.to_return


@dataclass
class QueueItem[T]:
    procedure: Callable[[storage.Storage], T]
    # The `field` is important, since otherwise we share a singel event for all items
    event: threading.Event = field(default_factory=threading.Event)
    to_return: T | UnsetType = UNSET
    exception: storage.StorageError | None = None


def run_store(store_queue: StorageQueue, db_file: str, db_tables: list[str] | None):
    if db_file == ":memory:":
        # Special string that opens a new database in memory
        path = db_file
    else:
        # Get the absolute path of the parent and then rejoin to make sure what we show is what is
        # actually used.
        path = Path(db_file)
        path_parent = path.parent.resolve(strict=True)
        path = path_parent.joinpath(path.parts[-1])
    store = storage.Storage(db_path=path, tables=db_tables)
    logger.info(f"Opened SQLite database at {path}.")
    while True:
        try:
            # We put a timeout just so that we occasionally do something in this thread
            item = store_queue.queue.get(block=True, timeout=0.1)
        except queue.Empty:
            continue

        if not isinstance(item, QueueItem):
            continue
        store.conn.execute("BEGIN IMMEDIATE")
        try:
            value = item.procedure(store)
        except storage.StorageError as e:
            # Rollback the transaction for recoverable errors
            store.conn.rollback()
            # Return the error to the caller instead of crashing the storage thread
            item.exception = e
            item.event.set()
            continue
        except Exception as e:
            # Still try to rollback if we can
            store.conn.rollback()
            raise e

        store.conn.commit()
        item.to_return = value
        item.event.set()


def start_server(
    config: ServerConfig,
    handler: Handler,
    ready_event: threading.Event | None = None,
):
    """Start the HTTP server and begin accepting connections.

    Args:
        config: Server configuration options.
        handler: Function called to handle each request and produce a response.
        ready_event: If provided, this event is set once the server is ready to
            accept connections (after socket binding and before the accept loop).
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((config.host, config.port))
    server_socket.listen(config.listen_backlog)

    logger.info(f"Server listening on {config.host}:{config.port}")
    logger.info(f"Limits: Header={config.max_header_size}, Body={config.max_body_size}")

    # We run 1 thread that has access to the SQLite database
    # This ensures every operation is atomic
    # Procedures are sent through the `store_queue`
    # `daemon=True` ensures that we do not wait for the thread to finish when exiting
    if config.db_file is not None:
        store_queue = StorageQueue()
        threading.Thread(
            target=run_store,
            args=(store_queue, config.db_file, config.db_tables),
            daemon=True,
        ).start()
    else:
        store_queue = None

    if ready_event is not None:
        ready_event.set()

    try:
        # This is the main accept loop, we create a new thread for every new connection
        while True:
            try:
                client, addr = server_socket.accept()
                ctx = ConnectionContext(client, addr, store_queue, config)
                threading.Thread(
                    target=handle_client, args=(ctx, handler), daemon=True
                ).start()
            except Exception as e:
                logger.error(f"Accept error: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        server_socket.close()
