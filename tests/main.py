import logging
import threading

from freetser import (
    Request,
    Response,
    ServerConfig,
    Storage,
    StorageQueue,
    setup_logging,
    start_server,
    start_storage_thread,
)

logger = logging.getLogger("freetser.handler")


def handler(req: Request, store_queue: StorageQueue | None) -> Response:
    assert store_queue is not None

    if req.path.startswith("/stress-test/"):
        parts = req.path.split("/")
        if len(parts) >= 3:
            item_id = parts[2]

            if req.method == "GET":

                def get_or_create(store: Storage) -> str:
                    result = store.get("USERS", item_id)
                    if result is None:
                        value = f"item-{item_id}".encode()
                        store.add("USERS", item_id, value, 0)
                        return f"Created: {item_id}\n"
                    else:
                        value, counter = result
                        return f"Found: {item_id}, counter={counter}\n"

                text = store_queue.execute(get_or_create)
                return Response.text(text)

            elif req.method == "POST":

                def create_or_update(store: Storage) -> tuple[str, int]:
                    result = store.get("USERS", item_id)
                    value = req.body if req.body else f"item-{item_id}".encode()

                    if result is None:
                        store.add("USERS", item_id, value, 0)
                        return f"Created: {item_id}\n", 200
                    else:
                        _, counter = result
                        success = store.update(
                            "USERS", item_id, value, counter, assert_updated=False
                        )
                        if success:
                            return f"Updated: {item_id}\n", 200
                        else:
                            return f"Update conflict: {item_id}\n", 409

                text, status_code = store_queue.execute(create_or_update)
                return Response.text(text, status_code=status_code)

            elif req.method == "DELETE":

                def delete_item(store: Storage) -> tuple[str, int]:
                    success = store.delete("USERS", item_id)
                    if success:
                        return f"Deleted: {item_id}\n", 200
                    else:
                        return f"Not found: {item_id}\n", 404

                text, status_code = store_queue.execute(delete_item)
                return Response.text(text, status_code=status_code)

    elif req.path == "/items":

        def list_items(store: Storage) -> str:
            keys = store.list_keys("USERS")
            return f"Items: {len(keys)}\n{', '.join(keys[:10])}\n"

        text = store_queue.execute(list_items)
        return Response.text(text)

    text = (
        f"Hello from pyht!\nThread: {threading.current_thread().name}\n"
        f"Method: {req.method}\nPath: {req.path}\n"
        f"Body length: {len(req.body)} bytes\n"
    )

    return Response.text(text)


def main():
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    listener = setup_logging()
    listener.start()

    # Start the storage thread first
    store_queue = start_storage_thread(db_file="db.sqlite", db_tables=["USERS"])

    config = ServerConfig(port=port)
    try:
        start_server(config, handler, store_queue=store_queue)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
