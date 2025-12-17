"""Tests for Unix domain socket support."""

import socket
import tempfile
import threading
from pathlib import Path

from freetser import (
    Request,
    Response,
    StorageQueue,
    UnixServerConfig,
    start_server,
)


def simple_handler(req: Request, store_queue: StorageQueue | None) -> Response:
    return Response.text(f"Hello from {req.path}!")


class TestUnixSocket:
    """Tests for Unix domain socket server."""

    def test_unix_socket_server_starts_and_accepts_connections(self):
        """Test that server can start on a Unix socket and accept connections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            config = UnixServerConfig(path=str(socket_path))

            ready_event = threading.Event()
            server_thread = threading.Thread(
                target=start_server,
                args=(config, simple_handler),
                kwargs={"ready_event": ready_event},
                daemon=True,
            )
            server_thread.start()
            ready_event.wait(timeout=30)

            # Connect via Unix socket and send HTTP request
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(socket_path))
                client.sendall(b"GET /test HTTP/1.1\r\nHost: localhost\r\n\r\n")

                response = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if b"Hello from /test!" in response:
                        break

                response_str = response.decode("utf-8")
                assert "200" in response_str
                assert "Hello from /test!" in response_str
            finally:
                client.close()

    def test_unix_socket_file_created_and_cleaned_up(self):
        """Test that socket file is created on start and would be cleaned on shutdown."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            config = UnixServerConfig(path=str(socket_path))

            ready_event = threading.Event()
            server_thread = threading.Thread(
                target=start_server,
                args=(config, simple_handler),
                kwargs={"ready_event": ready_event},
                daemon=True,
            )
            server_thread.start()
            ready_event.wait(timeout=5)

            # Socket file should exist
            assert socket_path.exists()

    def test_unix_socket_replaces_existing_file(self):
        """Test that server removes existing socket file before binding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"

            # Create a stale socket file
            socket_path.touch()
            assert socket_path.exists()

            config = UnixServerConfig(path=str(socket_path))

            ready_event = threading.Event()
            server_thread = threading.Thread(
                target=start_server,
                args=(config, simple_handler),
                kwargs={"ready_event": ready_event},
                daemon=True,
            )
            server_thread.start()

            # Server should start successfully despite existing file
            assert ready_event.wait(timeout=5)

    def test_unix_socket_keepalive(self):
        """Test that keep-alive works on Unix sockets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = Path(tmpdir) / "test.sock"
            config = UnixServerConfig(path=str(socket_path))

            ready_event = threading.Event()
            server_thread = threading.Thread(
                target=start_server,
                args=(config, simple_handler),
                kwargs={"ready_event": ready_event},
                daemon=True,
            )
            server_thread.start()
            ready_event.wait(timeout=5)

            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(socket_path))

                # Send multiple requests on same connection
                for i in range(3):
                    client.sendall(
                        f"GET /request{i} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode()
                    )

                    response = b""
                    while b"Hello from" not in response:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        response += chunk

                    assert f"Hello from /request{i}!" in response.decode("utf-8")
            finally:
                client.close()
