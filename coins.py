import sqlite3
import time
from pathlib import Path


class CoinService:
    """Tracks persistent coin balances in the app's SQLite database."""

    def __init__(self, database_path):
        self.database_path = Path(database_path).expanduser()

    def initialize(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_coins (
                    username TEXT PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.commit()

    def get_balance(self, username):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT username, balance, updated_at
                FROM user_coins
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

        if row is None:
            return {
                "username": username,
                "balance": 0,
                "updated_at": None,
            }

        return dict(row)

    def award_correct_answer(self, username, multiplier, now=None):
        now = int(now or time.time())
        multiplier = max(1, int(multiplier or 1))
        amount = multiplier
        self.initialize()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_coins (username, balance, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    balance = balance + excluded.balance,
                    updated_at = excluded.updated_at
                """,
                (username, amount, now),
            )
            row = connection.execute(
                """
                SELECT username, balance, updated_at
                FROM user_coins
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
            connection.commit()

        result = dict(row)
        result["awarded"] = amount
        result["multiplier"] = multiplier
        return result

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
