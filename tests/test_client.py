"""Tests for the freetser HTTP client."""

import tempfile
import threading
from pathlib import Path

from freetser import (
    Request,
    Response,
    StorageQueue,
    UnixServerConfig,
    client,
    start_server,
)


def simple_handler(req: Request, store_queue: StorageQueue | None) -> Response:
    """Simple handler for testing."""
    if req.method == "POST":
        return Response.text(f"POST {req.path}: {len(req.body)} bytes")
    return Response.text(f"{req.method} {req.path}")


class TestConnectionTcp:
    """Tests for TCP HTTP requests using the running test server."""

    def test_get_request(self):
        """Test GET request via TCP."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.get("/test")
            assert response.status_code == 200
            assert "Hello from pyht!" in response.body_text

    def test_post_request(self):
        """Test POST request via TCP."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.post("/api/data", body=b"hello world")
            assert response.status_code == 200

    def test_multiple_requests_same_connection(self):
        """Test multiple requests reuse the same connection (keep-alive)."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            for i in range(3):
                response = conn.get(f"/test/{i}")
                assert response.status_code == 200

    def test_get_header(self):
        """Test getting response headers."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.get("/test")
            content_type = response.get_header("Content-Type")
            assert content_type == b"text/plain; charset=utf-8"

    def test_all_http_methods(self):
        """Test all HTTP methods work."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.get("/test")
            assert response.status_code == 200

            response = conn.post("/api/data", body=b"test")
            assert response.status_code == 200

            response = conn.put("/api/data", body=b"test")
            assert response.status_code == 200

            response = conn.delete("/api/data")
            assert response.status_code == 200

    def test_custom_headers(self):
        """Test that custom headers are sent."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.get("/test", headers=[("X-Custom", "value")])
            assert response.status_code == 200


class TestConnectionUnix:
    """Tests for Unix socket HTTP requests."""

    def test_get_request_unix(self):
        """Test GET request via Unix socket."""
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

            with client.Connection(client.UnixAddress(str(socket_path))) as conn:
                response = conn.get("/hello")
                assert response.status_code == 200
                assert response.body_text == "GET /hello"

    def test_post_request_unix(self):
        """Test POST request via Unix socket."""
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

            with client.Connection(client.UnixAddress(str(socket_path))) as conn:
                response = conn.post("/upload", body=b"test data")
                assert response.status_code == 200
                assert "9 bytes" in response.body_text

    def test_multiple_requests_unix(self):
        """Test multiple requests on same Unix socket connection."""
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

            with client.Connection(client.UnixAddress(str(socket_path))) as conn:
                for i in range(3):
                    response = conn.get(f"/request/{i}")
                    assert response.status_code == 200
                    assert f"GET /request/{i}" in response.body_text


class TestConnection:
    """Tests for Connection behavior."""

    def test_context_manager(self):
        """Test connection works as context manager."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            response = conn.get("/test")
            assert response.status_code == 200
        assert conn.closed

    def test_close(self):
        """Test closing connection."""
        conn = client.Connection(client.TcpAddress("127.0.0.1", 8000))
        response = conn.get("/test")
        assert response.status_code == 200
        conn.close()
        assert conn.closed

    def test_multiple_connections_parallel(self):
        """Test multiple independent connections can work in parallel."""
        import concurrent.futures

        def make_request(i: int) -> int:
            with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
                response = conn.get(f"/test/{i}")
                return response.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(make_request, i) for i in range(4)]
            results = [f.result() for f in futures]

        assert all(code == 200 for code in results)

    def test_sequential_requests_reuse_socket(self):
        """Test that sequential requests reuse the same socket."""
        with client.Connection(client.TcpAddress("127.0.0.1", 8000)) as conn:
            for i in range(10):
                response = conn.get(f"/test/{i}")
                assert response.status_code == 200

    def test_timeout_parameter(self):
        """Test that timeout can be set."""
        with client.Connection(
            client.TcpAddress("127.0.0.1", 8000), timeout=30.0
        ) as conn:
            response = conn.get("/test")
            assert response.status_code == 200
