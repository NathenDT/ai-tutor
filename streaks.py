import sqlite3
import time
from pathlib import Path


SECONDS_PER_DAY = 60 * 60 * 24
STREAK_GRACE_SECONDS = SECONDS_PER_DAY * 2


class StreakService:
    """Tracks login streaks in the app's SQLite database."""

    def __init__(self, database_path):
        self.database_path = Path(database_path).expanduser()

    def initialize(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_streaks (
                    username TEXT PRIMARY KEY,
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    longest_streak INTEGER NOT NULL DEFAULT 0,
                    last_counted_login_at INTEGER,
                    last_seen_login_at INTEGER,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.commit()

    def record_login(self, username, now=None):
        """Count at most one streak day per 24-hour login window."""
        now = int(now or time.time())
        self.initialize()

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT username, current_streak, longest_streak, last_counted_login_at
                FROM user_streaks
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

            if row is None:
                streak = {
                    "username": username,
                    "current_streak": 1,
                    "longest_streak": 1,
                    "last_counted_login_at": now,
                    "last_seen_login_at": now,
                    "counted_today": True,
                }
                connection.execute(
                    """
                    INSERT INTO user_streaks (
                        username,
                        current_streak,
                        longest_streak,
                        last_counted_login_at,
                        last_seen_login_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        streak["current_streak"],
                        streak["longest_streak"],
                        streak["last_counted_login_at"],
                        streak["last_seen_login_at"],
                        now,
                    ),
                )
                connection.commit()
                return streak

            seconds_since_counted = now - (row["last_counted_login_at"] or 0)
            counted_today = seconds_since_counted >= SECONDS_PER_DAY

            if counted_today:
                if seconds_since_counted <= STREAK_GRACE_SECONDS:
                    current_streak = row["current_streak"] + 1
                else:
                    current_streak = 1

                longest_streak = max(row["longest_streak"], current_streak)
                last_counted_login_at = now
            else:
                current_streak = row["current_streak"]
                longest_streak = row["longest_streak"]
                last_counted_login_at = row["last_counted_login_at"]

            connection.execute(
                """
                UPDATE user_streaks
                SET current_streak = ?,
                    longest_streak = ?,
                    last_counted_login_at = ?,
                    last_seen_login_at = ?,
                    updated_at = ?
                WHERE username = ?
                """,
                (
                    current_streak,
                    longest_streak,
                    last_counted_login_at,
                    now,
                    now,
                    username,
                ),
            )
            connection.commit()

        return {
            "username": username,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_counted_login_at": last_counted_login_at,
            "last_seen_login_at": now,
            "counted_today": counted_today,
        }

    def get_streak(self, username):
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT username,
                       current_streak,
                       longest_streak,
                       last_counted_login_at,
                       last_seen_login_at
                FROM user_streaks
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

        if row is None:
            return {
                "username": username,
                "current_streak": 0,
                "longest_streak": 0,
                "last_counted_login_at": None,
                "last_seen_login_at": None,
                "counted_today": False,
            }

        return dict(row)

    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection
