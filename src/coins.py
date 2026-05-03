import sqlite3
import time
from pathlib import Path


STORE_ITEMS = [
    {"id": "cat", "emoji": "🐔", "name": "Study Cat", "price": 5},
    {"id": "dog", "emoji": "🐷", "name": "Homework Dog", "price": 10},
    {"id": "fox", "emoji": "🐮", "name": "Clever Fox", "price": 20},
    {"id": "panda", "emoji": "🐼", "name": "Focus Panda", "price": 50},
    {"id": "owl", "emoji": "🦅", "name": "Wise Owl", "price": 100},
    {"id": "dragon", "emoji": "🐉", "name": "Legend Dragon", "price": 500},
    {"id": "dragon", "emoji": "🦖", "name": "Legend Dragon", "price": 1000},
]


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_store_items (
                    username TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    purchased_at INTEGER NOT NULL,
                    PRIMARY KEY (username, item_id)
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

    def get_store(self, username):
        owned_items = self.get_owned_item_ids(username)
        balance = self.get_balance(username)["balance"]
        return {
            "balance": balance,
            "items": [
                {
                    **item,
                    "owned": item["id"] in owned_items,
                    "affordable": balance >= item["price"],
                }
                for item in STORE_ITEMS
            ],
        }

    def get_owned_item_ids(self, username):
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_id
                FROM user_store_items
                WHERE username = ?
                """,
                (username,),
            ).fetchall()
        return {row["item_id"] for row in rows}

    def purchase_store_item(self, username, item_id, now=None):
        self.initialize()
        item = next((item for item in STORE_ITEMS if item["id"] == item_id), None)
        if item is None:
            return {"ok": False, "error": "Store item was not found.", "status_code": 404}

        now = int(now or time.time())
        with self._connect() as connection:
            existing_item = connection.execute(
                """
                SELECT item_id
                FROM user_store_items
                WHERE username = ? AND item_id = ?
                """,
                (username, item_id),
            ).fetchone()
            if existing_item:
                balance = self._get_balance_in_connection(connection, username)
                return {
                    "ok": True,
                    "already_owned": True,
                    "balance": balance,
                    "item": {**item, "owned": True, "affordable": True},
                }

            balance = self._get_balance_in_connection(connection, username)
            if balance < item["price"]:
                return {
                    "ok": False,
                    "error": "Not enough coins.",
                    "status_code": 400,
                    "balance": balance,
                    "item": {**item, "owned": False, "affordable": False},
                }

            connection.execute(
                """
                INSERT INTO user_coins (username, balance, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    balance = user_coins.balance - ?,
                    updated_at = excluded.updated_at
                """,
                (username, 0, now, item["price"]),
            )
            connection.execute(
                """
                INSERT INTO user_store_items (username, item_id, purchased_at)
                VALUES (?, ?, ?)
                """,
                (username, item_id, now),
            )
            balance = self._get_balance_in_connection(connection, username)
            connection.commit()

        return {
            "ok": True,
            "already_owned": False,
            "balance": balance,
            "item": {**item, "owned": True, "affordable": balance >= item["price"]},
        }

    def _get_balance_in_connection(self, connection, username):
        row = connection.execute(
            """
            SELECT balance
            FROM user_coins
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
        return int(row["balance"]) if row else 0

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
