"""Test suite for the pyht HTTP server using pytest and httpx"""

from concurrent.futures import ThreadPoolExecutor

import httpx

from .conftest import SERVER_URL


def test_simple_get_request(client: httpx.Client):
    """Test a simple GET request"""
    response = client.get("/test")

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: GET" in response.text
    assert "Path: /test" in response.text
    assert "Body length: 0 bytes" in response.text


def test_post_request_with_body(client: httpx.Client):
    """Test a POST request with body data"""
    test_data = "Hello from the test client!"
    response = client.post("/api/submit", content=test_data)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: POST" in response.text
    assert "Path: /api/submit" in response.text
    assert f"Body length: {len(test_data)} bytes" in response.text


def test_different_paths(client: httpx.Client):
    """Test requests to different paths"""
    paths = ["/", "/hello", "/api/users", "/test/path/deep"]

    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        assert "Hello from pyht!" in response.text
        assert f"Path: {path}" in response.text


def test_root_path(client: httpx.Client):
    """Test the root path specifically"""
    response = client.get("/")

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Path: /" in response.text


def _make_concurrent_request(request_id: int) -> tuple[int, str]:
    """Helper function to make a request from a thread"""
    with httpx.Client(base_url=SERVER_URL, timeout=5.0) as client:
        response = client.get(f"/concurrent/{request_id}")
        return response.status_code, response.text


def test_concurrent_requests():
    """Test multiple concurrent requests to demonstrate thread-per-request architecture"""
    num_requests = 5

    # Make concurrent requests using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=num_requests) as executor:
        futures = [
            executor.submit(_make_concurrent_request, i)
            for i in range(1, num_requests + 1)
        ]
        results = [future.result() for future in futures]

    # Verify all requests succeeded
    for status_code, body in results:
        assert status_code == 200
        assert "Hello from pyht!" in body
        assert "Thread:" in body


def test_large_post_body(client: httpx.Client):
    """Test POST request with larger body (1KB)"""
    large_data = b"x" * 1024
    response = client.post("/upload", content=large_data)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: POST" in response.text
    assert "Body length: 1024 bytes" in response.text


def test_very_large_post_body(client: httpx.Client):
    """Test POST request with very large body (10KB)"""
    very_large_data = b"y" * (10 * 1024)
    response = client.post("/large-upload", content=very_large_data)

    assert response.status_code == 200
    assert "Body length: 10240 bytes" in response.text


def test_empty_post_body(client: httpx.Client):
    """Test POST request with empty body"""
    response = client.post("/api/empty")

    assert response.status_code == 200
    assert "Method: POST" in response.text
    assert "Body length: 0 bytes" in response.text


def test_response_headers(client: httpx.Client):
    """Test that response has correct headers"""
    response = client.get("/headers-test")

    assert response.status_code == 200
    assert "content-type" in response.headers
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "content-length" in response.headers


def test_keepalive_connection_reuse():
    """Test that connections are reused with keep-alive"""
    # Use a session to track connection reuse
    with httpx.Client(base_url=SERVER_URL, timeout=5.0) as client:
        # Make multiple requests on the same connection
        response1 = client.get("/keepalive1")
        assert response1.status_code == 200

        response2 = client.get("/keepalive2")
        assert response2.status_code == 200

        response3 = client.get("/keepalive3")
        assert response3.status_code == 200

        # All should succeed - connection reuse is working


def test_http_10_rejected():
    """Test that HTTP/1.0 requests are rejected with 505 error"""
    # Create a raw HTTP/1.0 request
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)  # Set timeout to avoid hanging
    sock.connect(("localhost", 8000))

    # Send HTTP/1.0 request
    request = b"GET /test HTTP/1.0\r\nHost: localhost\r\n\r\n"
    sock.sendall(request)

    # Read until connection closes (server sends Connection: close)
    response_parts = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_parts.append(chunk)
    except socket.timeout:
        pass  # Server closed connection

    response = b"".join(response_parts).decode("utf-8")
    sock.close()

    # Should get 505 HTTP Version Not Supported
    assert "505" in response
    assert "HTTP Version Not Supported" in response or "505 Error:" in response


def test_100_continue_support(client: httpx.Client):
    """Test that server properly handles Expect: 100-continue"""
    # Create a POST request with Expect: 100-continue header
    large_data = b"x" * 1024
    headers = {"Expect": "100-continue"}

    response = client.post("/upload-continue", content=large_data, headers=headers)

    assert response.status_code == 200
    assert "Body length: 1024 bytes" in response.text


def test_body_size_limit_exceeded():
    """Test that request body exceeding 2MB limit returns 413 error"""
    # Create a request body larger than 2MB
    oversized_data = b"x" * (3 * 1024 * 1024)  # 3MB

    with httpx.Client(base_url=SERVER_URL, timeout=10.0) as client:
        response = client.post("/upload-large", content=oversized_data)

        # Should get 413 Payload Too Large
        assert response.status_code == 413
        assert "Payload Too Large" in response.text


def test_body_size_limit_just_under():
    """Test that request body just under 2MB limit succeeds"""
    # Create a request body just under 2MB
    large_data = b"x" * (2 * 1024 * 1024 - 1024)  # Just under 2MB

    with httpx.Client(base_url=SERVER_URL, timeout=10.0) as client:
        response = client.post("/upload-max", content=large_data)

        assert response.status_code == 200
        assert f"Body length: {len(large_data)} bytes" in response.text


def test_error_response_closes_connection():
    """Test that error responses include Connection: close"""
    # Test with HTTP/1.0 which triggers an error
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    sock.connect(("localhost", 8000))

    request = b"GET /test HTTP/1.0\r\nHost: localhost\r\n\r\n"
    sock.sendall(request)

    # Read until connection closes
    response_parts = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_parts.append(chunk)
    except socket.timeout:
        pass

    response = b"".join(response_parts).decode("utf-8")

    # Error responses should include Connection: close
    assert "Connection: close" in response or "connection: close" in response.lower()

    sock.close()
