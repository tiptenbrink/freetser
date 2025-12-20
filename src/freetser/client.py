"""HTTP client with persistent connections.

Usage:
    from freetser import client

    # Create a connection
    conn = client.Connection(client.TcpAddress("127.0.0.1", 8000))

    # Make requests
    response = conn.get("/api/users")
    response = conn.post("/api/data", body=b'{"key": "value"}')

    # Close when done
    conn.close()

    # Or use context manager
    with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
        response = conn.get("/api/users")

For parallelism, create multiple connections and use from different threads.
"""

import socket
from dataclasses import dataclass

import h11

from freetser.core import Response, get_next_event


@dataclass
class TcpAddress:
    """TCP server address."""

    host: str = "127.0.0.1"
    port: int = 8000


@dataclass
class UnixAddress:
    """Unix domain socket address."""

    path: str = "/tmp/freetser.sock"


Address = TcpAddress | UnixAddress


class Connection:
    """A persistent HTTP connection to a server.

    Requests are made synchronously on the calling thread.
    For parallelism, create multiple Connection instances
    and use them from different threads.

    Args:
        address: Server address (TcpAddress or UnixAddress).
        timeout: Socket timeout in seconds. None means no timeout (default).
    """

    def __init__(self, address: Address, timeout: float | None = None):
        self.address = address
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.h11_conn: h11.Connection | None = None

    def connect(self) -> None:
        """Establish connection."""
        if isinstance(self.address, UnixAddress):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.address.path)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.address.host, self.address.port))

        self.h11_conn = h11.Connection(h11.CLIENT)

    def disconnect(self) -> None:
        """Close the socket."""
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            self.h11_conn = None

    def reset_connection(self) -> None:
        """Reset h11 state for next request, or disconnect if needed."""
        if self.h11_conn is None:
            return

        if (
            self.h11_conn.our_state is h11.DONE
            and self.h11_conn.their_state is h11.DONE
        ):
            self.h11_conn.start_next_cycle()
        elif (
            self.h11_conn.our_state is h11.MUST_CLOSE
            or self.h11_conn.their_state is h11.MUST_CLOSE
        ):
            self.disconnect()

    def request(
        self,
        method: str,
        path: str,
        headers: list[tuple[str, str]] | None = None,
        body: bytes | None = None,
    ) -> Response:
        """Make an HTTP request."""
        for attempt in range(2):
            try:
                if self.sock is None:
                    self.connect()
                else:
                    self.reset_connection()
                    if self.sock is None:
                        self.connect()

                return self.send_request(method, path, headers, body)
            except Exception:
                self.disconnect()
                if attempt == 1:
                    raise

        raise RuntimeError("Request failed")

    def send_request(
        self,
        method: str,
        path: str,
        headers: list[tuple[str, str]] | None,
        body: bytes | None,
    ) -> Response:
        """Send request and read response."""
        assert self.sock is not None
        assert self.h11_conn is not None

        # Build headers
        req_headers: list[tuple[str, str]] = []
        if isinstance(self.address, UnixAddress):
            req_headers.append(("Host", "localhost"))
        else:
            req_headers.append(("Host", f"{self.address.host}:{self.address.port}"))

        if headers:
            req_headers.extend(headers)

        if body:
            req_headers.append(("Content-Length", str(len(body))))

        # Send request
        h11_request = h11.Request(
            method=method.encode(),
            target=path.encode(),
            headers=[(k.encode(), v.encode()) for k, v in req_headers],
        )
        self.sock.sendall(self.h11_conn.send(h11_request))

        if body:
            self.sock.sendall(self.h11_conn.send(h11.Data(data=body)))

        self.sock.sendall(self.h11_conn.send(h11.EndOfMessage()))

        # Read response
        status_code = 0
        response_headers: list[tuple[bytes, bytes]] = []
        body_parts: list[bytes] = []

        while True:
            event = get_next_event(self.h11_conn, self.sock)

            if event is None or isinstance(event, h11.ConnectionClosed):
                break

            if isinstance(event, h11.Response):
                status_code = event.status_code
                response_headers = list(event.headers)
            elif isinstance(event, h11.Data):
                body_parts.append(event.data)
            elif isinstance(event, h11.EndOfMessage):
                break

        return Response(
            status_code=status_code,
            headers=response_headers,
            body=b"".join(body_parts),
        )

    def get(self, path: str, headers: list[tuple[str, str]] | None = None) -> Response:
        """Make a GET request."""
        return self.request("GET", path, headers)

    def post(
        self,
        path: str,
        body: bytes | None = None,
        headers: list[tuple[str, str]] | None = None,
    ) -> Response:
        """Make a POST request."""
        return self.request("POST", path, headers, body)

    def put(
        self,
        path: str,
        body: bytes | None = None,
        headers: list[tuple[str, str]] | None = None,
    ) -> Response:
        """Make a PUT request."""
        return self.request("PUT", path, headers, body)

    def delete(
        self, path: str, headers: list[tuple[str, str]] | None = None
    ) -> Response:
        """Make a DELETE request."""
        return self.request("DELETE", path, headers)

    def close(self) -> None:
        """Close the connection."""
        self.disconnect()

    @property
    def closed(self) -> bool:
        """Return True if the connection is closed."""
        return self.sock is None

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *args) -> None:
        self.close()
