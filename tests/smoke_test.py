"""Smoke test to verify the package is correctly installed and importable."""


def test_imports() -> None:
    """Test that all public API can be imported."""
    from freetser import (
        EntryAlreadyExists,
        Request,
        Response,
        ServerConfig,
        Storage,
        StorageError,
        setup_logging,
        start_server,
    )

    # Verify the imports are the expected types
    assert callable(start_server)
    assert callable(setup_logging)
    assert isinstance(ServerConfig, type)
    assert isinstance(Request, type)
    assert isinstance(Response, type)
    assert isinstance(Storage, type)
    assert isinstance(StorageError, type)
    assert isinstance(EntryAlreadyExists, type)


if __name__ == "__main__":
    test_imports()
    print("Smoke test passed!")
