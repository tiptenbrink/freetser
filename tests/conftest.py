"""Shared pytest fixtures for all tests"""

import os
import tempfile
import threading
import time
from pathlib import Path

import pytest
import requests

from freetser import TcpServerConfig, setup_logging, start_server, start_storage_thread

from .main import handler

SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("FREETSER_TEST_PORT", "8020"))
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


def wait_for_http_server(base_url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/", timeout=1.0)
        except requests.RequestException:
            time.sleep(0.1)
            continue

        if response.status_code == 200:
            return
        time.sleep(0.1)

    raise RuntimeError(f"HTTP test server did not become ready at {base_url}")


@pytest.fixture(scope="session")
def running_server():
    listener = setup_logging()
    listener.start()

    tempdir = tempfile.TemporaryDirectory()
    db_path = Path(tempdir.name) / "test.sqlite"
    store_queue = start_storage_thread(db_file=str(db_path), db_tables=["USERS"])

    ready_event = threading.Event()
    startup_exception: list[BaseException] = []

    def run_server() -> None:
        try:
            start_server(
                TcpServerConfig(host=SERVER_HOST, port=SERVER_PORT),
                handler,
                ready_event=ready_event,
                store_queue=store_queue,
            )
        except BaseException as exc:
            startup_exception.append(exc)
            ready_event.set()

    threading.Thread(
        target=run_server,
        daemon=True,
        name="freetser-test-server",
    ).start()

    if not ready_event.wait(timeout=10.0):
        listener.stop()
        tempdir.cleanup()
        pytest.fail("Timed out waiting for the HTTP test server to start")

    if startup_exception:
        listener.stop()
        tempdir.cleanup()
        if isinstance(startup_exception[0], PermissionError):
            pytest.skip("TCP sockets are not permitted in this environment")
        raise startup_exception[0]

    wait_for_http_server(SERVER_URL)

    try:
        yield
    finally:
        listener.stop()
        tempdir.cleanup()


@pytest.fixture
def client(running_server):
    """Create a requests session for testing"""
    return requests.Session()


@pytest.fixture
def base_url(running_server):
    """Return the base URL for the test server"""
    return SERVER_URL


@pytest.fixture
def server_port(running_server):
    """Return the TCP port for the test server."""
    return SERVER_PORT
