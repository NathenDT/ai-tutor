import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class SettingsApiTest(unittest.TestCase):
    def test_settings_save_migrates_existing_auth_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO users (username, password_hash, created_at)
                    VALUES (?, ?, ?)
                    """,
                    ("student", main.hash_password("password"), int(time.time())),
                )
                connection.commit()

            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                token = main.create_session_token("student")
                client = TestClient(main.app)
                client.cookies.set(main.AUTH_COOKIE_NAME, token)

                response = client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), {"message": "Settings saved successfully."}
                )

                response = client.get("/api/settings")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["settings"],
                    {
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )


if __name__ == "__main__":
    unittest.main()
