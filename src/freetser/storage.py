import logging
import sqlite3
from os import PathLike

logger = logging.getLogger("freetser.storage")


def check_integrity_error(
    e: sqlite3.IntegrityError, column: str, category: str
) -> bool:
    """For column 'email' in table 'user', 'user.email' would be the column. For category, at least 'unique' works."""
    assert isinstance(e.args[0], str)
    return column in e.args[0] and category in e.args[0].lower()


class StorageError(Exception):
    """Base exception for storage errors."""

    pass


class EntryAlreadyExists(StorageError):
    """Raised when trying to add a key that already exists."""

    pass


class Storage:
    """
    Creates the necessary tables and sets up connections.
    """

    conn: sqlite3.Connection

    def __init__(self, db_path: str | PathLike[str], tables: list[str] | None = None):
        # Set persistent settings (WAL mode persists across connections)
        # And create tables
        # We use LEGACY_TRANSACTION_CONTROL so that we can use isolation_leve=None
        # This allows us to manually perform transaction control so there are no transactions
        # implicitly opened and we can avoid "database is locked" errors when readers upgrade to
        # writers.
        conn = sqlite3.connect(
            db_path,
            autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,  # pyright: ignore [reportArgumentType]
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")
        conn.execute("PRAGMA busy_timeout = 500;")
        conn.commit()
        if tables:
            conn.execute("BEGIN IMMEDIATE")
            for table in tables:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        key TEXT PRIMARY KEY,
                        counter INTEGER NOT NULL,
                        expiration INTEGER NOT NULL,
                        value BLOB NOT NULL
                    ) STRICT;
                """)
            conn.commit()

        self.conn = conn

    def close(self):
        self.conn.close()

    def get(
        self, table_name: str, key: str, timestamp=None
    ) -> tuple[bytes, int] | None:
        """
        Retrieve a value and its version counter.
        """
        cursor = self.conn.execute(
            f"SELECT value, counter, expiration FROM {table_name} WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        if row is None:
            return None

        expiration: int = row[2]
        # If timestamp is provided, the expiration is set to positive and if expired, return None
        if timestamp is not None and expiration > 0 and timestamp > expiration:
            return None

        return row[0], row[1]

    def add(
        self, table_name: str, key: str, value: bytes, expires_at=0, timestamp=None
    ) -> None:
        """
        Add a new key-value pair.
        If timestamp is provided and an entry exists but is expired, overwrite it.
        """

        # Validate that we're not adding an already-expired entry
        if timestamp is not None and expires_at > 0 and timestamp > expires_at:
            raise ValueError(
                f"Cannot add entry that is already expired: expires_at={expires_at} < timestamp={timestamp}"
            )

        if timestamp is None:
            # Simple insert without expiration check
            try:
                self.conn.execute(
                    f"INSERT INTO {table_name} (key, value, counter, expiration) VALUES (?, ?, 0, ?)",
                    (key, value, expires_at),
                )
            except sqlite3.IntegrityError as e:
                self.conn.rollback()
                if check_integrity_error(e, f"{table_name}.key", "unique"):
                    raise EntryAlreadyExists(f"Key already exists: {key}") from e
                raise e
        else:
            # Insert with expiration check - allow overwriting expired entries
            cursor = self.conn.execute(
                f"""
                INSERT INTO {table_name} (key, value, counter, expiration)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    counter = 0,
                    expiration = excluded.expiration
                WHERE expiration > 0 AND ? > expiration
                RETURNING key
                """,
                (key, value, expires_at, timestamp),
            )
            if cursor.fetchone() is None:
                # Conflict occurred but WHERE clause prevented update (key exists and not expired)
                raise EntryAlreadyExists(f"Key already exists: {key}")

    def update(
        self,
        table_name: str,
        key: str,
        value: bytes,
        counter: int,
        expires_at=0,
        assert_updated: bool = True,
    ) -> bool:
        cursor = self.conn.execute(
            f"""
            UPDATE {table_name}
            SET value = ?, counter = counter + 1, expiration = ?
            WHERE key = ? AND counter = ?
            """,
            (value, expires_at, key, counter),
        )
        result = cursor.rowcount == 1
        if assert_updated:
            assert result
        return result

    def delete(self, table_name: str, key: str) -> bool:
        cursor = self.conn.execute(f"DELETE FROM {table_name} WHERE key = ?", (key,))
        return cursor.rowcount == 1

    def list_keys(self, table_name: str) -> list[str]:
        cursor = self.conn.execute(f"SELECT key FROM {table_name}")
        result = [row[0] for row in cursor.fetchall()]
        return result

    def clear(self, table_name: str) -> None:
        """Remove all entries from the table."""

        self.conn.execute(f"DELETE FROM {table_name}")
