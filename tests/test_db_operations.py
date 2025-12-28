"""Quick test to verify database operations work correctly."""

import requests


def test_get_creates_item(base_url: str):
    """Test that GET creates item if it doesn't exist."""
    resp = requests.get(f"{base_url}/stress-test/test1", timeout=5.0)
    print(f"GET /stress-test/test1: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200
    assert "Created: test1" in resp.text or "Found: test1" in resp.text


def test_post_creates_and_updates(base_url: str):
    """Test POST creates or updates item."""
    # First POST should create
    resp = requests.post(
        f"{base_url}/stress-test/test2", data=b"hello world", timeout=5.0
    )
    print(f"\nPOST /stress-test/test2: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200

    # Second POST should update
    resp = requests.post(
        f"{base_url}/stress-test/test2", data=b"updated data", timeout=5.0
    )
    print(f"POST /stress-test/test2 (update): {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code in (200, 409)  # Either success or conflict


def test_delete_removes_item(base_url: str):
    """Test DELETE removes item."""
    # Create item first
    requests.get(f"{base_url}/stress-test/test3", timeout=5.0)

    # Then delete it
    resp = requests.delete(f"{base_url}/stress-test/test3", timeout=5.0)
    print(f"\nDELETE /stress-test/test3: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code in (200, 404)

    # Verify it's gone (should recreate)
    resp = requests.get(f"{base_url}/stress-test/test3", timeout=5.0)
    print(f"GET /stress-test/test3 (after delete): {resp.status_code}")
    print(f"Response: {resp.text}")
    assert "Created: test3" in resp.text


def test_list_items(base_url: str):
    """Test listing items."""
    resp = requests.get(f"{base_url}/items", timeout=5.0)
    print(f"\nGET /items: {resp.status_code}")
    print(f"Response: {resp.text}")
    assert resp.status_code == 200
    assert "Items:" in resp.text
