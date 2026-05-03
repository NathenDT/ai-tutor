import sqlite3
import logging
import time

from . import config
from .coins import CoinService
from .streaks import StreakService


logger = logging.getLogger(__name__)
streak_service = StreakService(config.AUTH_DATABASE_PATH)
coin_service = CoinService(config.AUTH_DATABASE_PATH)


def get_db_connection():
    connection = sqlite3.connect(config.AUTH_DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_auth_database():
    from .auth import hash_password

    config.AUTH_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (user_id, key),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        user_count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 0 and config.AUTH_BOOTSTRAP_USERNAME and config.AUTH_BOOTSTRAP_PASSWORD:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    config.AUTH_BOOTSTRAP_USERNAME,
                    hash_password(config.AUTH_BOOTSTRAP_PASSWORD),
                    int(time.time()),
                ),
            )
            logger.info(
                "Created initial local auth user '%s' in %s",
                config.AUTH_BOOTSTRAP_USERNAME,
                config.AUTH_DATABASE_PATH,
            )
        connection.commit()


def get_saved_user_settings(username):
    initialize_auth_database()
    with get_db_connection() as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not user_id:
            return None

        rows = connection.execute(
            "SELECT key, value FROM user_settings WHERE user_id = ?",
            (user_id[0],),
        ).fetchall()

    return {row["key"]: row["value"] for row in rows}
