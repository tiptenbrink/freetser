import json
import socket
import threading
import time

import pytest
import requests

from freetser import (
    EntryAlreadyExists,
    Request,
    Response,
    Storage,
    StorageQueue,
    StorageThreadCrashed,
    TcpServerConfig,
    UnixServerConfig,
    start_server,
    start_storage_thread,
)


def wait_for_server(base_url: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            requests.get(f"{base_url}/", timeout=1.0)
            return
        except requests.RequestException:
            time.sleep(0.1)
    raise RuntimeError(f"HTTP test server did not become ready at {base_url}")


def free_tcp_port(host: str = "127.0.0.1") -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("TCP sockets are not permitted in this environment")


def start_test_server(
    config: TcpServerConfig,
    handler,
    store_queue: StorageQueue | None = None,
) -> str:
    ready_event = threading.Event()
    startup_exception: list[BaseException] = []

    def run_server() -> None:
        try:
            start_server(
                config,
                handler,
                ready_event=ready_event,
                store_queue=store_queue,
            )
        except BaseException as exc:
            startup_exception.append(exc)
            ready_event.set()

    threading.Thread(target=run_server, daemon=True).start()

    assert ready_event.wait(timeout=10.0)
    if startup_exception:
        if isinstance(startup_exception[0], PermissionError):
            pytest.skip("TCP sockets are not permitted in this environment")
        raise startup_exception[0]

    base_url = f"http://{config.host}:{config.port}"
    wait_for_server(base_url)
    return base_url


def test_readme_quick_start_handler_example():
    def handler(req: Request, store_queue) -> Response:
        if req.path == "/":
            return Response.text("Hello world!")
        return Response.text("Not found!", status_code=404)

    root_response = handler(Request("GET", "/", [], b""), None)
    assert root_response.status_code == 200
    assert root_response.body == b"Hello world!"

    missing_response = handler(Request("GET", "/missing", [], b""), None)
    assert missing_response.status_code == 404
    assert missing_response.body == b"Not found!"


def test_readme_server_configuration_examples():
    tcp_config = TcpServerConfig(
        host="127.0.0.1",
        port=8000,
        max_header_size=16384,
        max_body_size=2097152,
        listen_backlog=1024,
    )
    assert tcp_config.host == "127.0.0.1"
    assert tcp_config.port == 8000
    assert tcp_config.max_header_size == 16384
    assert tcp_config.max_body_size == 2097152
    assert tcp_config.listen_backlog == 1024

    unix_config = UnixServerConfig(path="/tmp/freetser.sock")
    assert unix_config.path == "/tmp/freetser.sock"


def test_readme_request_and_response_examples():
    request = Request(
        method="POST",
        path="/api/users",
        headers=[(b"content-type", b"application/json")],
        body=b'{"hello":"world"}',
    )
    assert request.method == "POST"
    assert request.path == "/api/users"
    assert request.headers == [(b"content-type", b"application/json")]
    assert request.body == b'{"hello":"world"}'

    text_response = Response.text("Hello", status_code=200)
    assert text_response.status_code == 200
    assert text_response.body == b"Hello"
    assert (b"Content-Type", b"text/plain; charset=utf-8") in text_response.headers

    json_response = Response.json({"key": "value"}, status_code=200)
    assert json_response.status_code == 200
    assert json.loads(json_response.body) == {"key": "value"}
    assert (b"Content-Type", b"application/json") in json_response.headers

    empty_response = Response.empty(status_code=204)
    assert empty_response.status_code == 204
    assert empty_response.body == b""
    assert (b"Content-Length", b"0") in empty_response.headers


def test_readme_storage_queue_example(tmp_path):
    store_queue = start_storage_thread(str(tmp_path / "readme.sqlite"), ["USERS"])

    def seed_user(store: Storage) -> None:
        store.add("USERS", "user123", b"alice", 0)

    store_queue.execute(seed_user)

    def handler(req: Request, store_queue: StorageQueue) -> Response:
        def get_user(store: Storage) -> tuple[bytes, int] | None:
            return store.get("USERS", "user123")

        result = store_queue.execute(get_user)
        if result is None:
            return Response.text("Not found", status_code=404)

        value, counter = result
        assert counter == 0
        return Response.json({"data": value.decode()})

    response = handler(Request("GET", "/users/user123", [], b""), store_queue)
    assert response.status_code == 200
    assert json.loads(response.body) == {"data": "alice"}


def test_readme_overwrite_example():
    storage = Storage(":memory:", tables=["CACHE"])
    try:
        storage.overwrite("CACHE", "profile:user123", b"first", expires_at=300)
        storage.overwrite("CACHE", "profile:user123", b"second", expires_at=300)

        result = storage.get("CACHE", "profile:user123")
        assert result is not None
        value, counter = result
        assert value == b"second"
        assert counter == 1
    finally:
        storage.close()


def test_readme_optimistic_locking_example(tmp_path):
    store_queue = start_storage_thread(str(tmp_path / "optimistic.sqlite"), ["DATA"])

    def seed_data(store: Storage) -> None:
        store.add("DATA", "key", b"old", 0)

    store_queue.execute(seed_data)

    def get_data(store: Storage):
        return store.get("DATA", "key")

    result = store_queue.execute(get_data)
    assert result is not None
    value, counter = result
    assert value == b"old"

    def concurrent_update(store: Storage) -> None:
        store.update("DATA", "key", b"other", counter)

    store_queue.execute(concurrent_update)

    new_value = value.upper()

    def save_data(store: Storage) -> bool:
        return store.try_update("DATA", "key", new_value, counter)

    assert store_queue.execute(save_data) is False


def test_readme_simple_routing_example():
    def list_users(store_queue) -> Response:
        assert store_queue == "store"
        return Response.text("list")

    def create_user(req: Request, store_queue) -> Response:
        assert req.body == b"new-user"
        assert store_queue == "store"
        return Response.text("create", status_code=201)

    def get_user(user_id: str, store_queue) -> Response:
        assert store_queue == "store"
        return Response.text(f"user:{user_id}")

    def handler(req: Request, store_queue) -> Response:
        if req.method == "GET" and req.path == "/users":
            return list_users(store_queue)
        if req.method == "POST" and req.path == "/users":
            return create_user(req, store_queue)
        if req.method == "GET" and req.path.startswith("/users/"):
            user_id = req.path.split("/")[-1]
            return get_user(user_id, store_queue)
        return Response.text("Not found", status_code=404)

    assert handler(Request("GET", "/users", [], b""), "store").body == b"list"

    created = handler(Request("POST", "/users", [], b"new-user"), "store")
    assert created.status_code == 201
    assert created.body == b"create"

    fetched = handler(Request("GET", "/users/alice", [], b""), "store")
    assert fetched.body == b"user:alice"

    missing = handler(Request("DELETE", "/users/alice", [], b""), "store")
    assert missing.status_code == 404
    assert missing.body == b"Not found"


def test_readme_error_handling_example(tmp_path):
    store_queue = start_storage_thread(str(tmp_path / "errors.sqlite"), ["USERS"])

    def handler(req: Request, store_queue: StorageQueue) -> Response:
        try:
            def create_user(store: Storage):
                store.add("USERS", req.body.decode(), b"{}", 0)
                return "created"

            result = store_queue.execute(create_user)
            return Response.text(result, status_code=201)

        except EntryAlreadyExists:
            return Response.text("User already exists", status_code=409)
        except StorageThreadCrashed:
            return Response.text("Storage thread crashed", status_code=500)

    created = handler(Request("POST", "/users", [], b"user123"), store_queue)
    assert created.status_code == 201
    assert created.body == b"created"

    duplicate = handler(Request("POST", "/users", [], b"user123"), store_queue)
    assert duplicate.status_code == 409
    assert duplicate.body == b"User already exists"

    def crash(store: Storage) -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        store_queue.execute(crash)

    crashed = handler(Request("POST", "/users", [], b"user456"), store_queue)
    assert crashed.status_code == 500
    assert crashed.body == b"Storage thread crashed"


def test_readme_fatal_procedure_error_example(tmp_path):
    store_queue = start_storage_thread(str(tmp_path / "fatal.sqlite"), ["USERS"])
    procedure_started = threading.Event()
    allow_crash = threading.Event()
    results: dict[str, BaseException] = {}

    def crash(store: Storage) -> None:
        procedure_started.set()
        allow_crash.wait(timeout=5.0)
        raise ValueError("bug in procedure")

    def first_caller() -> None:
        try:
            store_queue.execute(crash)
        except BaseException as exc:
            results["first"] = exc

    def second_caller() -> None:
        procedure_started.wait(timeout=5.0)
        try:
            store_queue.execute(lambda store: "never runs")
        except BaseException as exc:
            results["second"] = exc

    first = threading.Thread(target=first_caller, daemon=True)
    second = threading.Thread(target=second_caller, daemon=True)

    first.start()
    assert procedure_started.wait(timeout=5.0)
    second.start()

    allow_crash.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert isinstance(results["first"], ValueError)
    assert isinstance(results["second"], StorageThreadCrashed)

    with pytest.raises(StorageThreadCrashed):
        store_queue.execute(lambda store: "still dead")


def test_readme_shared_storage_pattern(tmp_path):
    store_queue = start_storage_thread(str(tmp_path / "shared.sqlite"), ["USERS"])
    public_port = free_tcp_port()
    internal_port = free_tcp_port()

    def public_handler(req: Request, store_queue: StorageQueue | None) -> Response:
        assert store_queue is not None
        if req.method == "GET" and req.path == "/":
            return Response.text("public")

        if req.method == "POST" and req.path.startswith("/users/"):
            user_id = req.path.split("/")[-1]

            def save_user(store: Storage) -> None:
                result = store.get("USERS", user_id)
                if result is None:
                    store.add("USERS", user_id, req.body, 0)
                else:
                    _, counter = result
                    store.update("USERS", user_id, req.body, counter)

            store_queue.execute(save_user)
            return Response.text("ok")

        return Response.text("Not found", status_code=404)

    def internal_handler(req: Request, store_queue: StorageQueue | None) -> Response:
        assert store_queue is not None
        if req.method == "GET" and req.path == "/":
            return Response.text("internal")

        if req.method == "GET" and req.path.startswith("/users/"):
            user_id = req.path.split("/")[-1]

            def get_user(store: Storage) -> tuple[bytes, int] | None:
                return store.get("USERS", user_id)

            result = store_queue.execute(get_user)
            if result is None:
                return Response.text("Not found", status_code=404)

            value, _ = result
            return Response.text(value.decode())

        return Response.text("Not found", status_code=404)

    public_url = start_test_server(
        TcpServerConfig(host="127.0.0.1", port=public_port),
        public_handler,
        store_queue=store_queue,
    )
    internal_url = start_test_server(
        TcpServerConfig(host="127.0.0.1", port=internal_port),
        internal_handler,
        store_queue=store_queue,
    )

    response = requests.post(f"{public_url}/users/alice", data=b"shared", timeout=5.0)
    assert response.status_code == 200

    response = requests.get(f"{internal_url}/users/alice", timeout=5.0)
    assert response.status_code == 200
    assert response.text == "shared"
