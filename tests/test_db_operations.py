"""Quick test to verify database operations work correctly."""

import httpx


def test_get_creates_item(client: httpx.Client):
    """Test that GET creates item if it doesn't exist."""
    resp = client.get("/stress-test/test1")
    print(f"GET /stress-test/test1: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200
    assert "Created: test1" in resp.text or "Found: test1" in resp.text


def test_post_creates_and_updates(client: httpx.Client):
    """Test POST creates or updates item."""
    # First POST should create
    resp = client.post("/stress-test/test2", content=b"hello world")
    print(f"\nPOST /stress-test/test2: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200

    # Second POST should update
    resp = client.post("/stress-test/test2", content=b"updated data")
    print(f"POST /stress-test/test2 (update): {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code in (200, 409)  # Either success or conflict


def test_delete_removes_item(client: httpx.Client):
    """Test DELETE removes item."""
    # Create item first
    client.get("/stress-test/test3")

    # Then delete it
    resp = client.delete("/stress-test/test3")
    print(f"\nDELETE /stress-test/test3: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code in (200, 404)

    # Verify it's gone (should recreate)
    resp = client.get("/stress-test/test3")
    print(f"GET /stress-test/test3 (after delete): {resp.status_code}")
    print(f"Response: {resp.text}")
    assert "Created: test3" in resp.text


def test_list_items(client: httpx.Client):
    """Test listing items."""
    resp = client.get("/items")
    print(f"\nGET /items: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200
    assert "Items:" in resp.text
