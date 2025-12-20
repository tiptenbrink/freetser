"""Shared core utilities for freetser server and client."""

import json
import logging
import socket
from dataclasses import dataclass
from typing import Optional, cast

import h11

MAX_RECV = 2**16

logger = logging.getLogger("freetser")


@dataclass
class Response:
    """HTTP response used by both server (to create) and client (to receive)."""

    status_code: int
    headers: list[tuple[bytes, bytes]]
    body: bytes

    def get_header(self, name: str) -> bytes | None:
        """Get a header value by name (case-insensitive)."""
        name_lower = name.lower().encode()
        for key, value in self.headers:
            if key.lower() == name_lower:
                return value
        return None

    @property
    def body_text(self) -> str:
        """Return body as UTF-8 text."""
        return self.body.decode("utf-8")

    @staticmethod
    def text(content: str, status_code: int = 200) -> "Response":
        """Create a text/plain response."""
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
    def json(
        content,
        headers: list[tuple[bytes, bytes]] | None = None,
        status_code: int = 200,
    ) -> "Response":
        """Create an application/json response."""
        if headers is None:
            headers = []
        body = json.dumps(content).encode("utf-8")
        headers.append((b"Content-Length", str(len(body)).encode("ascii")))
        headers.append((b"Content-Type", b"application/json"))
        return Response(status_code=status_code, headers=headers, body=body)

    @staticmethod
    def empty(
        headers: list[tuple[bytes, bytes]] | None = None, status_code: int = 200
    ) -> "Response":
        """Create an empty response."""
        if headers is None:
            headers = []
        headers.append((b"Content-Length", b"0"))
        return Response(status_code=status_code, headers=headers, body=b"")


def get_next_event(conn: h11.Connection, sock: socket.socket) -> Optional[h11.Event]:
    """Read the next h11 event from the socket.

    This function handles the h11 state machine, reading data from the socket
    as needed until a complete event is available.

    Args:
        conn: The h11 connection state machine.
        sock: The socket to read from.

    Returns:
        The next h11 event, or None if a socket error occurred.
    """
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
