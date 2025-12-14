import sqlite3
import threading
import time

import pytest

from freetser.server import StorageQueue, run_store
from freetser.storage import (
    EntryAlreadyExists,
    Storage,
    StorageError,
    check_integrity_error,
)


class TestCheckIntegrityError:
    """Tests for the check_integrity_error helper function."""

    def test_unique_constraint_failure(self):
        """Test detection of UNIQUE constraint failure."""
        # Simulate a UNIQUE constraint error
        error = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        assert check_integrity_error(error, "users.email", "unique")

    def test_primary_key_constraint_failure(self):
        """Test detection of PRIMARY KEY constraint failure."""
        # SQLite reports PRIMARY KEY violations as UNIQUE constraint failures
        error = sqlite3.IntegrityError("UNIQUE constraint failed: sessions.key")
        assert check_integrity_error(error, "sessions.key", "unique")

    def test_column_mismatch(self):
        """Test that wrong column name returns False."""
        error = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        assert not check_integrity_error(error, "users.username", "unique")

    def test_category_mismatch(self):
        """Test that wrong category returns False."""
        error = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        assert not check_integrity_error(error, "users.email", "foreign key")

    def test_case_insensitive_category(self):
        """Test that category matching is case-insensitive (error message is lowercased)."""
        # The error message has uppercase "UNIQUE" but category is checked after lowercasing
        error = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        # Pass lowercase category - it will match against lowercased error message
        assert check_integrity_error(error, "users.email", "unique")
        assert check_integrity_error(error, "users.email", "constraint")

    def test_partial_column_match(self):
        """Test that column substring matching works as documented."""
        error = sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
        # Partial matches should work based on 'in' operator
        assert check_integrity_error(error, "email", "unique")

    def test_not_null_constraint(self):
        """Test detection of NOT NULL constraint failures."""
        error = sqlite3.IntegrityError("NOT NULL constraint failed: users.name")
        assert check_integrity_error(error, "users.name", "not null")


class TestStorageInMemory:
    """Tests for Storage class using an in-memory database."""

    @pytest.fixture
    def storage(self):
        """Create a Storage instance with in-memory database."""
        storage = Storage(":memory:", tables=["test_table"])
        yield storage
        storage.close()

    def test_add_and_get(self, storage):
        """Test adding and retrieving a value."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"
        assert counter == 0

    def test_add_duplicate_key_raises_exception(self, storage):
        """Test that adding a duplicate key raises EntryAlreadyExists."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        with pytest.raises(EntryAlreadyExists) as exc_info:
            storage.add("test_table", "key1", b"value2", 9999999999)

        assert "Key already exists: key1" in str(exc_info.value)

    def test_check_integrity_error_is_used(self, storage):
        """Test that check_integrity_error is being used in the add method."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        # This should trigger the check_integrity_error function
        with pytest.raises(EntryAlreadyExists):
            storage.add("test_table", "key1", b"value2", 9999999999)

        # Verify original value wasn't overwritten
        result = storage.get("test_table", "key1")
        assert result is not None
        assert result[0] == b"value1"

    def test_update_increments_counter(self, storage):
        """Test that update increments the counter."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        # Get initial state
        value, counter = storage.get("test_table", "key1")
        assert counter == 0

        # Update
        storage.update("test_table", "key1", b"value2", counter, 9999999999)

        # Verify counter incremented
        value, new_counter = storage.get("test_table", "key1")
        assert value == b"value2"
        assert new_counter == 1

    def test_update_with_wrong_counter_fails(self, storage):
        """Test optimistic locking with wrong counter."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        # Try to update with wrong counter
        with pytest.raises(AssertionError):
            storage.update("test_table", "key1", b"value2", 999, 9999999999)

    def test_update_with_wrong_counter_returns_false(self, storage):
        """Test update returns False when counter doesn't match."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        # Update with assert_updated=False
        result = storage.update(
            "test_table",
            "key1",
            b"value2",
            999,
            9999999999,
            assert_updated=False,
        )
        assert result is False

        # Verify value wasn't changed
        value, counter = storage.get("test_table", "key1")
        assert value == b"value1"

    def test_delete_existing_key(self, storage):
        """Test deleting an existing key."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        result = storage.delete("test_table", "key1")
        assert result is True

        # Verify it's gone
        assert storage.get("test_table", "key1") is None

    def test_delete_nonexistent_key(self, storage):
        """Test deleting a nonexistent key returns False."""
        result = storage.delete("test_table", "nonexistent")
        assert result is False

    def test_list_keys(self, storage):
        """Test listing all keys in a table."""
        storage.add("test_table", "key1", b"value1", 9999999999)
        storage.add("test_table", "key2", b"value2", 9999999999)
        storage.add("test_table", "key3", b"value3", 9999999999)

        keys = storage.list_keys("test_table")
        assert sorted(keys) == ["key1", "key2", "key3"]

    def test_clear_table(self, storage):
        """Test clearing all entries from a table."""
        storage.add("test_table", "key1", b"value1", 9999999999)
        storage.add("test_table", "key2", b"value2", 9999999999)

        storage.clear("test_table")

        keys = storage.list_keys("test_table")
        assert keys == []

    def test_get_nonexistent_key(self, storage):
        """Test getting a nonexistent key returns None."""
        result = storage.get("test_table", "nonexistent")
        assert result is None

    def test_multiple_tables(self):
        """Test storage with multiple tables."""
        storage = Storage(":memory:", tables=["table1", "table2"])

        try:
            # Add to both tables
            storage.add("table1", "key1", b"value1", 9999999999)
            storage.add("table2", "key1", b"value2", 9999999999)

            # Verify they're separate
            result1 = storage.get("table1", "key1")
            result2 = storage.get("table2", "key1")
            assert result1 is not None
            assert result2 is not None

            value1, _ = result1
            value2, _ = result2

            assert value1 == b"value1"
            assert value2 == b"value2"
        finally:
            storage.close()

    def test_binary_data(self, storage):
        """Test storing arbitrary binary data."""
        binary_data = b"\x00\x01\x02\xff\xfe\xfd"
        storage.add("test_table", "binary_key", binary_data, 9999999999)

        value, _ = storage.get("test_table", "binary_key")
        assert value == binary_data

    def test_concurrent_updates_with_optimistic_locking(self, storage):
        """Test that optimistic locking prevents lost updates."""
        storage.add("test_table", "key1", b"value1", 9999999999)

        # Simulate two concurrent readers
        value1, counter1 = storage.get("test_table", "key1")
        value2, counter2 = storage.get("test_table", "key1")

        # First update succeeds
        result1 = storage.update(
            "test_table", "key1", b"update1", counter1, 9999999999, assert_updated=False
        )
        assert result1 is True

        # Second update fails due to stale counter
        result2 = storage.update(
            "test_table", "key1", b"update2", counter2, 9999999999, assert_updated=False
        )
        assert result2 is False

        # Verify only first update applied
        value, counter = storage.get("test_table", "key1")
        assert value == b"update1"
        assert counter == 1

    def test_get_with_timestamp_expired(self, storage):
        """Test that get() returns None when entry is expired based on timestamp."""
        # Add entry that expires at timestamp 1000
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Get with timestamp after expiration
        result = storage.get("test_table", "key1", timestamp=1001)
        assert result is None

    def test_get_with_timestamp_not_expired(self, storage):
        """Test that get() returns value when entry is not expired."""
        # Add entry that expires at timestamp 1000
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Get with timestamp before expiration
        result = storage.get("test_table", "key1", timestamp=999)
        assert result is not None
        value, counter = result
        assert value == b"value1"
        assert counter == 0

    def test_get_with_timestamp_no_expiration(self, storage):
        """Test that get() returns value when expiration is 0 (never expires)."""
        # Add entry with expiration=0 (no expiration)
        storage.add("test_table", "key1", b"value1", expires_at=0)

        # Get with any timestamp should succeed
        result = storage.get("test_table", "key1", timestamp=9999999999)
        assert result is not None
        value, counter = result
        assert value == b"value1"

    def test_get_without_timestamp_ignores_expiration(self, storage):
        """Test that get() without timestamp returns even expired entries."""
        # Add entry that would be considered expired
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Get without timestamp should still return the value
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"

    def test_add_with_timestamp_overwrite_expired(self, storage):
        """Test that add() with timestamp can overwrite expired entries."""
        # Add entry that expires at timestamp 1000
        storage.add("test_table", "key1", b"old_value", expires_at=1000)

        # Add with timestamp after expiration should succeed
        storage.add("test_table", "key1", b"new_value", expires_at=2000, timestamp=1001)

        # Verify the value was overwritten and counter reset to 0
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"new_value"
        assert counter == 0

    def test_add_with_timestamp_fails_if_not_expired(self, storage):
        """Test that add() with timestamp raises EntryAlreadyExists if entry not expired."""
        # Add entry that expires at timestamp 1000
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Try to add with timestamp before expiration
        with pytest.raises(EntryAlreadyExists) as exc_info:
            storage.add("test_table", "key1", b"value2", expires_at=2000, timestamp=999)

        assert "Key already exists: key1" in str(exc_info.value)

        # Verify original value wasn't changed
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"

    def test_add_with_timestamp_fails_if_expiration_zero(self, storage):
        """Test that add() with timestamp fails if existing entry has no expiration (0)."""
        # Add entry with no expiration
        storage.add("test_table", "key1", b"value1", expires_at=0)

        # Try to add with timestamp should fail (entry never expires)
        with pytest.raises(EntryAlreadyExists) as exc_info:
            storage.add(
                "test_table", "key1", b"value2", expires_at=9999999999, timestamp=1000
            )

        assert "Key already exists: key1" in str(exc_info.value)

    def test_add_without_timestamp_always_fails_on_duplicate(self, storage):
        """Test that add() without timestamp behaves as before (always fails on duplicate)."""
        # Add entry
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Try to add again without timestamp (even if expired)
        with pytest.raises(EntryAlreadyExists):
            storage.add("test_table", "key1", b"value2", expires_at=2000)

        # Verify original value wasn't changed
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"

    def test_add_already_expired_entry_raises_error(self, storage):
        """Test that adding an already-expired entry raises ValueError."""
        # Try to add entry with expiration in the past relative to timestamp
        with pytest.raises(ValueError) as exc_info:
            storage.add(
                "test_table", "key1", b"value1", expires_at=1000, timestamp=2000
            )

        assert "already expired" in str(exc_info.value).lower()
        assert "expires_at=1000" in str(exc_info.value)
        assert "timestamp=2000" in str(exc_info.value)

    def test_add_at_exact_expiration_time(self, storage):
        """Test that adding an entry where timestamp equals expires_at is allowed."""
        # Add entry where timestamp equals expiration (not yet expired)
        storage.add("test_table", "key1", b"value1", expires_at=1000, timestamp=1000)

        # Entry should exist
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"

        # At exact expiration time, entry is not yet expired
        result = storage.get("test_table", "key1", timestamp=1000)
        assert result is not None

    def test_add_with_expiration_zero_ignores_timestamp(self, storage):
        """Test that entries with expiration=0 (never expire) can be added with any timestamp."""
        # Add entry with no expiration and a timestamp
        storage.add("test_table", "key1", b"value1", expires_at=0, timestamp=9999999999)

        # Entry should exist
        result = storage.get("test_table", "key1")
        assert result is not None
        value, counter = result
        assert value == b"value1"


class TestIntegrityErrorHandling:
    """Tests demonstrating IntegrityError handling in add() method."""

    @pytest.fixture
    def storage(self):
        """Create a Storage instance with in-memory database."""
        storage = Storage(":memory:", tables=["test_table"])
        yield storage
        storage.close()

    def test_timestamp_branch_integrity_error_unreachable(self, storage):
        """
        Demonstrate that IntegrityError is unreachable in timestamp branch under normal schema.

        The ON CONFLICT(key) clause handles the PRIMARY KEY constraint, so even when
        a key collision occurs, it doesn't raise IntegrityError - it triggers the
        DO UPDATE clause instead.
        """
        # Add initial entry
        storage.add("test_table", "key1", b"value1", expires_at=1000)

        # Try to add again with timestamp but not expired - this triggers the
        # RETURNING/fetchone() check, not an IntegrityError
        with pytest.raises(EntryAlreadyExists):
            storage.add("test_table", "key1", b"value2", expires_at=2000, timestamp=500)

        # The only way to trigger IntegrityError in timestamp branch would be:
        # 1. Adding triggers that raise errors
        # 2. Adding CHECK constraints
        # 3. Adding other constraints beyond PRIMARY KEY
        # None of these exist in the current schema

    def test_can_trigger_integrity_error_with_trigger(self, storage):
        """
        Demonstrate that IntegrityError CAN be triggered if we add a trigger.
        This shows why the exception handler exists (defensive programming).
        """
        # Add a trigger that raises an error on certain conditions
        storage.conn.execute("""
            CREATE TRIGGER prevent_special_key
            BEFORE INSERT ON test_table
            WHEN NEW.key = 'forbidden'
            BEGIN
                SELECT RAISE(ABORT, 'Key "forbidden" is not allowed');
            END;
        """)

        # Without timestamp, the trigger fires and raises IntegrityError
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            storage.add("test_table", "forbidden", b"value", expires_at=1000)
        assert "not allowed" in str(exc_info.value).lower()

        # With timestamp, the trigger also fires and raises IntegrityError
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            storage.add(
                "test_table", "forbidden", b"value", expires_at=2000, timestamp=1000
            )
        assert "not allowed" in str(exc_info.value).lower()


class TestRollbackBehavior:
    """Tests for transaction rollback with manual transaction control."""

    @pytest.fixture
    def storage(self):
        """Create a Storage instance with in-memory database."""
        storage = Storage(":memory:", tables=["test_table"])
        yield storage
        storage.close()

    def test_rollback_undoes_changes(self, storage):
        """Test that rollback undoes all changes in a transaction."""
        # Add initial value
        storage.add("test_table", "key1", b"initial", 9999999999)

        # Start a transaction
        storage.conn.execute("BEGIN IMMEDIATE")

        # Make changes within the transaction
        storage.conn.execute(
            "UPDATE test_table SET value = ? WHERE key = ?",
            (b"modified", "key1"),
        )
        storage.conn.execute(
            "INSERT INTO test_table (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
            ("key2", b"new_value", 9999999999),
        )

        # Verify changes are visible within the transaction
        cursor = storage.conn.execute(
            "SELECT value FROM test_table WHERE key = ?", ("key1",)
        )
        assert cursor.fetchone()[0] == b"modified"

        cursor = storage.conn.execute(
            "SELECT value FROM test_table WHERE key = ?", ("key2",)
        )
        assert cursor.fetchone()[0] == b"new_value"

        # Rollback the transaction
        storage.conn.rollback()

        # Verify changes were undone
        value, _ = storage.get("test_table", "key1")
        assert value == b"initial"  # Should be back to initial value

        result = storage.get("test_table", "key2")
        assert result is None  # key2 should not exist

    def test_rollback_after_integrity_error(self, storage):
        """Test that rollback works after an IntegrityError with manual transaction control."""
        # Add initial key
        storage.add("test_table", "key1", b"value1", 9999999999)

        # Start a transaction
        storage.conn.execute("BEGIN IMMEDIATE")

        # Add another key successfully
        storage.conn.execute(
            "INSERT INTO test_table (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
            ("key2", b"value2", 9999999999),
        )

        # Try to add duplicate key (should fail)
        try:
            storage.add("test_table", "key1", b"duplicate", 9999999999)
        except EntryAlreadyExists:
            pass  # Expected

        # Rollback should work even after IntegrityError
        storage.conn.rollback()

        # Verify key2 was also rolled back (not committed)
        result = storage.get("test_table", "key2")
        assert result is None

        # Verify key1 still has original value
        value, _ = storage.get("test_table", "key1")
        assert value == b"value1"


class TestStorageQueueErrorHandling:
    """Tests for error handling and propagation through StorageQueue."""

    @pytest.fixture
    def storage_queue_setup(self):
        """Set up a StorageQueue with a running storage thread."""
        queue = StorageQueue()
        thread = threading.Thread(
            target=run_store,
            args=(queue, ":memory:", ["test_table"]),
            daemon=True,
        )
        thread.start()
        # Give the thread time to initialize
        time.sleep(0.1)
        yield queue
        # Thread will be cleaned up automatically (daemon thread)

    def test_storage_error_propagates_to_caller(self, storage_queue_setup):
        """Test that StorageError is propagated from storage thread to caller."""
        queue = storage_queue_setup

        # Add a key first
        def add_key1(store: Storage) -> None:
            store.add("test_table", "key1", b"value1", 9999999999)

        queue.execute(add_key1)

        # Try to add duplicate key - should raise EntryAlreadyExists
        def add_duplicate(store: Storage) -> None:
            store.add("test_table", "key1", b"duplicate", 9999999999)

        with pytest.raises(EntryAlreadyExists) as exc_info:
            queue.execute(add_duplicate)

        assert "Key already exists: key1" in str(exc_info.value)

    def test_storage_thread_continues_after_error(self, storage_queue_setup):
        """Test that storage thread continues processing after a StorageError."""
        queue = storage_queue_setup

        # Add a key first
        def add_key1(store: Storage) -> None:
            store.add("test_table", "key1", b"value1", 9999999999)

        queue.execute(add_key1)

        # Cause an error
        def add_duplicate(store: Storage) -> None:
            store.add("test_table", "key1", b"duplicate", 9999999999)

        with pytest.raises(EntryAlreadyExists):
            queue.execute(add_duplicate)

        # Storage thread should still work after the error
        def add_key2(store: Storage) -> str:
            store.add("test_table", "key2", b"value2", 9999999999)
            return "success"

        result = queue.execute(add_key2)
        assert result == "success"

        # Verify both keys exist
        def check_keys(store: Storage) -> list[str]:
            return store.list_keys("test_table")

        keys = queue.execute(check_keys)
        assert sorted(keys) == ["key1", "key2"]

    def test_transaction_rolled_back_on_error(self, storage_queue_setup):
        """Test that transaction is rolled back when StorageError occurs."""
        queue = storage_queue_setup

        # Define a procedure that makes multiple changes then fails
        def multi_change_then_fail(store: Storage) -> None:
            # Add key1 successfully
            store.conn.execute(
                "INSERT INTO test_table (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
                ("key1", b"value1", 9999999999),
            )
            # Add key2 successfully
            store.conn.execute(
                "INSERT INTO test_table (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
                ("key2", b"value2", 9999999999),
            )
            # Try to add key1 again (will fail with IntegrityError -> EntryAlreadyExists)
            store.add("test_table", "key1", b"duplicate", 9999999999)

        # This should raise EntryAlreadyExists
        with pytest.raises(EntryAlreadyExists):
            queue.execute(multi_change_then_fail)

        # Verify that BOTH key1 and key2 were rolled back (neither should exist)
        def check_keys(store: Storage) -> list[str]:
            return store.list_keys("test_table")

        keys = queue.execute(check_keys)
        assert keys == []  # Both keys should be rolled back

    def test_custom_storage_error_propagates(self, storage_queue_setup):
        """Test that custom StorageError subclasses propagate correctly."""
        queue = storage_queue_setup

        # Define a custom StorageError
        class CustomStorageError(StorageError):
            pass

        # Define a procedure that raises a custom error
        def raise_custom_error(store: Storage) -> None:
            # Make some changes first
            store.conn.execute(
                "INSERT INTO test_table (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
                ("key1", b"value1", 9999999999),
            )
            raise CustomStorageError("Custom error occurred")

        # This should propagate the custom error
        with pytest.raises(CustomStorageError) as exc_info:
            queue.execute(raise_custom_error)

        assert "Custom error occurred" in str(exc_info.value)

        # Verify that the transaction was rolled back (key1 should not exist)
        def check_keys(store: Storage) -> list[str]:
            return store.list_keys("test_table")

        keys = queue.execute(check_keys)
        assert keys == []
