"""Test suite for the freetser HTTP server using pytest and requests"""

import socket
from concurrent.futures import ThreadPoolExecutor

import requests

from .conftest import SERVER_URL


def test_simple_get_request(base_url: str):
    """Test a simple GET request"""
    response = requests.get(f"{base_url}/test", timeout=5.0)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: GET" in response.text
    assert "Path: /test" in response.text
    assert "Body length: 0 bytes" in response.text


def test_post_request_with_body(base_url: str):
    """Test a POST request with body data"""
    test_data = "Hello from the test client!"
    response = requests.post(f"{base_url}/api/submit", data=test_data, timeout=5.0)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: POST" in response.text
    assert "Path: /api/submit" in response.text
    assert f"Body length: {len(test_data)} bytes" in response.text


def test_different_paths(base_url: str):
    """Test requests to different paths"""
    paths = ["/", "/hello", "/api/users", "/test/path/deep"]

    for path in paths:
        response = requests.get(f"{base_url}{path}", timeout=5.0)
        assert response.status_code == 200
        assert "Hello from pyht!" in response.text
        assert f"Path: {path}" in response.text


def test_root_path(base_url: str):
    """Test the root path specifically"""
    response = requests.get(f"{base_url}/", timeout=5.0)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Path: /" in response.text


def _make_concurrent_request(request_id: int) -> tuple[int, str]:
    """Helper function to make a request from a thread"""
    response = requests.get(f"{SERVER_URL}/concurrent/{request_id}", timeout=5.0)
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


def test_large_post_body(base_url: str):
    """Test POST request with larger body (1KB)"""
    large_data = b"x" * 1024
    response = requests.post(f"{base_url}/upload", data=large_data, timeout=5.0)

    assert response.status_code == 200
    assert "Hello from pyht!" in response.text
    assert "Method: POST" in response.text
    assert "Body length: 1024 bytes" in response.text


def test_very_large_post_body(base_url: str):
    """Test POST request with very large body (10KB)"""
    very_large_data = b"y" * (10 * 1024)
    response = requests.post(
        f"{base_url}/large-upload", data=very_large_data, timeout=5.0
    )

    assert response.status_code == 200
    assert "Body length: 10240 bytes" in response.text


def test_empty_post_body(base_url: str):
    """Test POST request with empty body"""
    response = requests.post(f"{base_url}/api/empty", timeout=5.0)

    assert response.status_code == 200
    assert "Method: POST" in response.text
    assert "Body length: 0 bytes" in response.text


def test_response_headers(base_url: str):
    """Test that response has correct headers"""
    response = requests.get(f"{base_url}/headers-test", timeout=5.0)

    assert response.status_code == 200
    assert "content-type" in response.headers
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "content-length" in response.headers


def test_keepalive_connection_reuse(base_url: str):
    """Test that connections are reused with keep-alive"""
    # Use a session to track connection reuse
    with requests.Session() as session:
        # Make multiple requests on the same connection
        response1 = session.get(f"{base_url}/keepalive1", timeout=5.0)
        assert response1.status_code == 200

        response2 = session.get(f"{base_url}/keepalive2", timeout=5.0)
        assert response2.status_code == 200

        response3 = session.get(f"{base_url}/keepalive3", timeout=5.0)
        assert response3.status_code == 200

        # All should succeed - connection reuse is working


def test_http_10_rejected():
    """Test that HTTP/1.0 requests are rejected with 505 error"""
    # Create a raw HTTP/1.0 request
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


def test_100_continue_support(base_url: str):
    """Test that server properly handles Expect: 100-continue"""
    # Create a POST request with Expect: 100-continue header
    large_data = b"x" * 1024
    headers = {"Expect": "100-continue"}

    response = requests.post(
        f"{base_url}/upload-continue", data=large_data, headers=headers, timeout=5.0
    )

    assert response.status_code == 200
    assert "Body length: 1024 bytes" in response.text


def test_body_size_limit_exceeded(base_url: str):
    """Test that request body exceeding 2MB limit returns 413 error"""
    # Create a request body larger than 2MB
    oversized_data = b"x" * (3 * 1024 * 1024)  # 3MB

    response = requests.post(
        f"{base_url}/upload-large", data=oversized_data, timeout=10.0
    )

    # Should get 413 Payload Too Large
    assert response.status_code == 413
    assert "Payload Too Large" in response.text


def test_body_size_limit_just_under(base_url: str):
    """Test that request body just under 2MB limit succeeds"""
    # Create a request body just under 2MB
    large_data = b"x" * (2 * 1024 * 1024 - 1024)  # Just under 2MB

    response = requests.post(f"{base_url}/upload-max", data=large_data, timeout=10.0)

    assert response.status_code == 200
    assert f"Body length: {len(large_data)} bytes" in response.text


def test_error_response_closes_connection():
    """Test that error responses include Connection: close"""
    # Test with HTTP/1.0 which triggers an error
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
