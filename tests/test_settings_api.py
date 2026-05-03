import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import src.main as main


def create_legacy_user_database(database_path, username="student"):
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
            (username, main.hash_password("password"), int(time.time())),
        )
        connection.commit()


class SettingsApiTest(unittest.TestCase):
    def test_settings_save_migrates_existing_auth_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            create_legacy_user_database(database_path)

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

    def test_legacy_auth_login_route_still_sets_session_cookie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                main.initialize_auth_database()
                main.create_user("student", "password")
                client = TestClient(main.app)

                response = client.post(
                    "/auth/login",
                    json={"username": "student", "password": "password"},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"authenticated": True})
                self.assertIn(main.AUTH_COOKIE_NAME, response.cookies)

                response = client.get("/auth/me")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"authenticated": True})

    def test_store_purchase_spends_coins_and_marks_item_owned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ), patch.object(main.coin_service, "database_path", database_path):
                main.initialize_auth_database()
                main.create_user("student", "password")
                main.coin_service.award_correct_answer("student", multiplier=10)
                token = main.create_session_token("student")
                client = TestClient(main.app)
                client.cookies.set(main.AUTH_COOKIE_NAME, token)

                response = client.get("/api/store")

                self.assertEqual(response.status_code, 200)
                store = response.json()
                self.assertEqual(store["balance"], 10)
                self.assertTrue(any(item["emoji"] == "🐱" for item in store["items"]))

                response = client.post("/api/store/purchase", json={"item_id": "cat"})

                self.assertEqual(response.status_code, 200)
                purchase = response.json()
                self.assertEqual(purchase["balance"], 5)
                self.assertEqual(purchase["item"]["emoji"], "🐱")
                self.assertTrue(purchase["item"]["owned"])

                response = client.get("/api/store")

                self.assertEqual(response.status_code, 200)
                cat = next(item for item in response.json()["items"] if item["id"] == "cat")
                self.assertTrue(cat["owned"])


class FakeCanvasResponse:
    def __init__(self, status_code, payload, links=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.links = links or {}
        self.content = content

    def json(self):
        return self._payload


class FakeCanvasClient:
    responses = []
    calls = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self.responses.pop(0)


class CanvasCoursesApiTest(unittest.TestCase):
    def setUp(self):
        main.CANVAS_COURSE_INDEX_STATUSES.clear()
        main.CANVAS_COURSE_INDEX_TASKS.clear()

    def build_client(self, database_path):
        main.initialize_auth_database()
        main.create_user("student", "password")
        token = main.create_session_token("student")
        client = TestClient(main.app)
        client.cookies.set(main.AUTH_COOKIE_NAME, token)
        return client

    def test_canvas_courses_requires_authentication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = TestClient(main.app)

                response = client.get("/api/canvas/courses")

                self.assertEqual(response.status_code, 401)

    def test_canvas_courses_reports_missing_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)

                response = client.get("/api/canvas/courses")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {
                        "connected": False,
                        "courses": [],
                        "message": "Canvas settings are missing.",
                    },
                )

    def test_canvas_courses_returns_normalized_saved_canvas_courses(self):
        courses = [
            {
                "id": 42,
                "name": "Biology",
                "course_code": "BIO-101",
                "workflow_state": "available",
                "start_at": "2026-01-10T00:00:00Z",
                "end_at": None,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main, "fetch_canvas_courses", new=AsyncMock(return_value=courses)
                ) as fetch_courses:
                    response = client.get("/api/canvas/courses")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), {"connected": True, "courses": courses}
                )
                fetch_courses.assert_awaited_once_with(
                    "https://school.instructure.com", "token-123"
                )

    def test_canvas_courses_reports_canvas_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main, "fetch_canvas_courses", new=AsyncMock(return_value=None)
                ):
                    response = client.get("/api/canvas/courses")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(),
                    {
                        "connected": False,
                        "courses": [],
                        "message": "Could not load Canvas courses.",
                    },
                )

    def test_fetch_canvas_courses_combines_paginated_results(self):
        FakeCanvasClient.responses = [
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 1,
                        "name": "Algebra",
                        "course_code": "MATH-100",
                        "workflow_state": "available",
                        "start_at": None,
                        "end_at": None,
                    }
                ],
                {
                    "next": {
                        "url": "https://school.instructure.com/api/v1/courses?page=2"
                    }
                },
            ),
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 2,
                        "course_code": "ENG-200",
                        "workflow_state": "available",
                        "start_at": "2026-02-01T00:00:00Z",
                        "end_at": "2026-05-01T00:00:00Z",
                    }
                ],
            ),
        ]
        FakeCanvasClient.calls = []

        with patch.object(main.httpx, "AsyncClient", FakeCanvasClient):
            courses = asyncio.run(
                main.fetch_canvas_courses(
                    "https://school.instructure.com/", "token-123"
                )
            )

        self.assertEqual(
            courses,
            [
                {
                    "id": 1,
                    "name": "Algebra",
                    "course_code": "MATH-100",
                    "workflow_state": "available",
                    "start_at": None,
                    "end_at": None,
                },
                {
                    "id": 2,
                    "name": "Course 2",
                    "course_code": "ENG-200",
                    "workflow_state": "available",
                    "start_at": "2026-02-01T00:00:00Z",
                    "end_at": "2026-05-01T00:00:00Z",
                },
            ],
        )
        self.assertEqual(len(FakeCanvasClient.calls), 2)
        self.assertEqual(
            FakeCanvasClient.calls[0]["url"],
            "https://school.instructure.com/api/v1/courses",
        )
        self.assertEqual(
            FakeCanvasClient.calls[0]["params"],
            {"enrollment_state": "active", "per_page": 100},
        )
        self.assertEqual(FakeCanvasClient.calls[1]["params"], None)
        self.assertEqual(
            FakeCanvasClient.calls[0]["headers"],
            {"Authorization": "Bearer token-123"},
        )

    def test_fetch_canvas_course_pdf_files_filters_and_paginates(self):
        FakeCanvasClient.responses = [
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 11,
                        "display_name": "Week 1.pdf",
                        "content-type": "application/pdf",
                    },
                    {
                        "id": 12,
                        "display_name": "notes.txt",
                        "content-type": "text/plain",
                    },
                ],
                {
                    "next": {
                        "url": "https://school.instructure.com/api/v1/courses/42/files?page=2"
                    }
                },
            ),
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 13,
                        "display_name": "Week 2.pdf",
                        "content-type": "application/octet-stream",
                    }
                ],
            ),
        ]
        FakeCanvasClient.calls = []

        with patch.object(main.httpx, "AsyncClient", FakeCanvasClient):
            files = asyncio.run(
                main.fetch_canvas_course_pdf_files(
                    "https://school.instructure.com/",
                    "token-123",
                    42,
                )
            )

        self.assertEqual([file_item["id"] for file_item in files], [11, 13])
        self.assertEqual(len(FakeCanvasClient.calls), 2)
        self.assertEqual(
            FakeCanvasClient.calls[0]["url"],
            "https://school.instructure.com/api/v1/courses/42/files",
        )
        self.assertEqual(
            FakeCanvasClient.calls[0]["params"],
            {"content_types[]": "application/pdf", "per_page": 100},
        )
        self.assertEqual(FakeCanvasClient.calls[1]["params"], None)

    def test_fetch_canvas_course_modules_combines_pages_and_details(self):
        FakeCanvasClient.responses = [
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 5,
                        "name": "Week 1",
                        "position": 1,
                        "items": [
                            {
                                "id": 91,
                                "title": "Lab Report",
                                "type": "Assignment",
                                "content_id": 77,
                                "url": "https://school.instructure.com/api/v1/courses/42/assignments/77",
                            }
                        ],
                    }
                ],
                {
                    "next": {
                        "url": "https://school.instructure.com/api/v1/courses/42/modules?page=2"
                    }
                },
            ),
            FakeCanvasResponse(
                200,
                [{"id": 6, "name": "Week 2", "items": []}],
            ),
            FakeCanvasResponse(
                200,
                {
                    "id": 77,
                    "description": "<p>Explain the experiment results.</p>",
                    "html_url": "https://school.instructure.com/courses/42/assignments/77",
                    "published": True,
                },
            ),
        ]
        FakeCanvasClient.calls = []

        with patch.object(main.httpx, "AsyncClient", FakeCanvasClient):
            modules = asyncio.run(
                main.fetch_canvas_course_modules(
                    "https://school.instructure.com/",
                    "token-123",
                    42,
                )
            )

        self.assertEqual([module["id"] for module in modules], [5, 6])
        self.assertEqual(
            modules[0]["items"][0]["details"]["description"],
            "<p>Explain the experiment results.</p>",
        )
        self.assertEqual(modules[0]["items"][0]["published"], True)
        self.assertEqual(len(FakeCanvasClient.calls), 3)
        self.assertEqual(
            FakeCanvasClient.calls[0]["url"],
            "https://school.instructure.com/api/v1/courses/42/modules",
        )
        self.assertEqual(
            FakeCanvasClient.calls[0]["params"],
            {"include[]": "items", "per_page": 100},
        )
        self.assertEqual(FakeCanvasClient.calls[1]["params"], None)

    def test_fetch_canvas_course_assignments_normalizes_and_paginates(self):
        FakeCanvasClient.responses = [
            FakeCanvasResponse(
                200,
                [
                    {
                        "id": 101,
                        "name": "Essay",
                        "description": "<p>Write about cells.</p>",
                        "due_at": "2026-06-01T00:00:00Z",
                        "points_possible": 10,
                        "html_url": "https://school.instructure.com/courses/42/assignments/101",
                        "published": True,
                    }
                ],
                {
                    "next": {
                        "url": "https://school.instructure.com/api/v1/courses/42/assignments?page=2"
                    }
                },
            ),
            FakeCanvasResponse(200, []),
        ]
        FakeCanvasClient.calls = []

        with patch.object(main.httpx, "AsyncClient", FakeCanvasClient):
            assignments = asyncio.run(
                main.fetch_canvas_course_assignments(
                    "https://school.instructure.com/",
                    "token-123",
                    42,
                )
            )

        self.assertEqual(assignments[0]["id"], 101)
        self.assertEqual(assignments[0]["description"], "Write about cells.")
        self.assertEqual(assignments[0]["course_id"], 42)
        self.assertEqual(len(FakeCanvasClient.calls), 2)
        self.assertEqual(
            FakeCanvasClient.calls[0]["url"],
            "https://school.instructure.com/api/v1/courses/42/assignments",
        )
        self.assertEqual(FakeCanvasClient.calls[0]["params"], {"per_page": 100})

    def test_download_canvas_pdf_reports_failed_download(self):
        FakeCanvasClient.responses = [
            FakeCanvasResponse(404, {"error": "not found"}),
        ]
        FakeCanvasClient.calls = []

        with patch.object(main.httpx, "AsyncClient", FakeCanvasClient):
            with self.assertRaisesRegex(RuntimeError, "Could not download"):
                asyncio.run(
                    main.download_canvas_pdf(
                        "https://school.instructure.com",
                        "token-123",
                        42,
                        {"id": 11, "display_name": "Week 1.pdf"},
                    )
                )

    def test_index_canvas_course_pdfs_marks_empty_when_no_pdfs(self):
        course = {"id": 42, "name": "Biology", "course_code": "BIO-101"}
        namespace = main.build_canvas_course_namespace("student", course)

        async def no_pdf_files(canvas_url, canvas_token, course_id):
            return []

        async def no_modules(canvas_url, canvas_token, course_id):
            return []

        with patch.object(
            main,
            "fetch_canvas_course_pdf_files",
            new=no_pdf_files,
        ), patch.object(
            main,
            "fetch_canvas_course_modules",
            new=no_modules,
        ):
            asyncio.run(
                main.index_canvas_course_pdfs(
                    "https://school.instructure.com",
                    "token-123",
                    course,
                    namespace,
                )
            )

        status = main.CANVAS_COURSE_INDEX_STATUSES[namespace]
        self.assertEqual(status["status"], "empty")
        self.assertEqual(status["indexedFileCount"], 0)
        self.assertEqual(status["chunkCount"], 0)
        self.assertEqual(status["moduleItemCount"], 0)

    def test_index_canvas_course_pdfs_upserts_extracted_chunks(self):
        course = {"id": 42, "name": "Biology", "course_code": "BIO-101"}
        namespace = main.build_canvas_course_namespace("student", course)
        calls = {}

        async def one_pdf_file(canvas_url, canvas_token, course_id):
            return [
                {
                    "id": 11,
                    "display_name": "Week 1.pdf",
                    "content-type": "application/pdf",
                }
            ]

        async def pdf_content(canvas_url, canvas_token, course_id, file_item):
            return b"%PDF"

        async def no_modules(canvas_url, canvas_token, course_id):
            return []

        def fake_extract_pdf_pages(content):
            return [{"page_number": 1, "text": "photosynthesis creates glucose"}]

        def fake_upsert(records, record_namespace):
            calls["records"] = records
            calls["namespace"] = record_namespace

        with patch.object(main, "fetch_canvas_course_pdf_files", new=one_pdf_file), patch.object(
            main, "download_canvas_pdf", new=pdf_content
        ), patch.object(main, "fetch_canvas_course_modules", new=no_modules), patch.object(
            main, "extract_pdf_pages", fake_extract_pdf_pages
        ), patch.object(
            main, "upsert_records_to_pinecone", fake_upsert
        ):
            asyncio.run(
                main.index_canvas_course_pdfs(
                    "https://school.instructure.com",
                    "token-123",
                    course,
                    namespace,
                )
            )

        status = main.CANVAS_COURSE_INDEX_STATUSES[namespace]
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["indexedFileCount"], 1)
        self.assertEqual(status["chunkCount"], 1)
        self.assertEqual(calls["namespace"], namespace)
        self.assertEqual(calls["records"][0]["_id"], "canvas-42-11-p1-c0")
        self.assertEqual(calls["records"][0]["source"], "canvas")
        self.assertEqual(calls["records"][0]["course_name"], "Biology")

    def test_index_canvas_course_marks_ready_from_module_records_without_pdfs(self):
        course = {"id": 42, "name": "Biology", "course_code": "BIO-101"}
        namespace = main.build_canvas_course_namespace("student", course)
        calls = {}

        async def no_pdf_files(canvas_url, canvas_token, course_id):
            return []

        async def one_module(canvas_url, canvas_token, course_id):
            return [
                {
                    "id": 5,
                    "name": "Week 1",
                    "items": [
                        {
                            "id": 91,
                            "title": "Lab Report",
                            "type": "Assignment",
                            "details": {"description": "<p>Explain the lab.</p>"},
                        }
                    ],
                }
            ]

        def fake_upsert(records, record_namespace):
            calls["records"] = records
            calls["namespace"] = record_namespace

        with patch.object(main, "fetch_canvas_course_pdf_files", new=no_pdf_files), patch.object(
            main, "fetch_canvas_course_modules", new=one_module
        ), patch.object(main, "upsert_records_to_pinecone", fake_upsert):
            asyncio.run(
                main.index_canvas_course_pdfs(
                    "https://school.instructure.com",
                    "token-123",
                    course,
                    namespace,
                )
            )

        status = main.CANVAS_COURSE_INDEX_STATUSES[namespace]
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["indexedFileCount"], 0)
        self.assertEqual(status["chunkCount"], 0)
        self.assertEqual(status["moduleItemCount"], 1)
        self.assertEqual(calls["namespace"], namespace)
        self.assertEqual(
            calls["records"][0]["_id"],
            "canvas-42-module-5-item-91",
        )
        self.assertIn("Explain the lab.", calls["records"][0][main.PINECONE_TEXT_FIELD])

    def test_canvas_course_tutor_route_requires_auth_and_serves_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)

                response = client.get("/tutor/42")

                self.assertEqual(response.status_code, 200)
                self.assertIn("Tutor", response.text)

    def test_create_user_page_does_not_redirect_authenticated_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)

                response = client.get("/create-user")

                self.assertEqual(response.status_code, 200)
                self.assertIn("Create user", response.text)

    def test_canvas_course_index_requires_pinecone_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ), patch.object(main, "PINECONE_API_KEY", ""):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ):
                    response = client.post("/api/canvas/courses/42/index")

                self.assertEqual(response.status_code, 503)
                self.assertIn("PINECONE_API_KEY", response.json()["error"])

    def test_canvas_course_index_refreshes_modules_for_existing_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ), patch.object(main, "PINECONE_API_KEY", "test-key"):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ), patch.object(
                    main,
                    "pinecone_namespace_has_records",
                    return_value=True,
                ), patch.object(
                    main,
                    "index_canvas_course_modules_metadata",
                    new=AsyncMock(),
                ) as index_modules:
                    response = client.post("/api/canvas/courses/42/index")

                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(result["status"], "indexing")
                self.assertEqual(result["namespace"], "student-42")
                self.assertEqual(result["course"]["id"], 42)
                index_modules.assert_awaited_once()

    def test_canvas_course_index_rejects_unknown_course(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ), patch.object(main, "PINECONE_API_KEY", "test-key"):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ):
                    response = client.post("/api/canvas/courses/99/index")

                self.assertEqual(response.status_code, 404)

    def test_canvas_course_assignments_requires_authentication(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = TestClient(main.app)

                response = client.get("/api/canvas/courses/42/assignments")

                self.assertEqual(response.status_code, 401)

    def test_canvas_course_assignments_reports_missing_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)

                response = client.get("/api/canvas/courses/42/assignments")

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Canvas settings are missing.")

    def test_canvas_course_assignments_returns_course_assignments(self):
        assignments = [
            {
                "id": 101,
                "course_id": 42,
                "name": "Essay",
                "description": "Write about cells.",
                "due_at": None,
                "points_possible": 10,
                "html_url": "https://school.instructure.com/courses/42/assignments/101",
                "published": True,
                "locked_for_user": False,
                "lock_at": None,
                "unlock_at": None,
            }
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ), patch.object(
                    main,
                    "fetch_canvas_course_assignments",
                    new=AsyncMock(return_value=assignments),
                ) as fetch_assignments:
                    response = client.get("/api/canvas/courses/42/assignments")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["assignments"], assignments)
                fetch_assignments.assert_awaited_once_with(
                    "https://school.instructure.com",
                    "token-123",
                    42,
                )

    def test_canvas_course_assignments_rejects_unknown_course(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ):
                    response = client.get("/api/canvas/courses/99/assignments")

                self.assertEqual(response.status_code, 404)

    def test_canvas_course_assignments_reports_canvas_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "auth.db"
            with patch.object(main, "AUTH_DATABASE_PATH", database_path), patch.object(
                main, "AUTH_SESSION_SECRET", "test-session-secret"
            ):
                client = self.build_client(database_path)
                client.post(
                    "/api/settings",
                    json={
                        "canvas_url": "https://school.instructure.com",
                        "canvas_token": "token-123",
                    },
                )

                async def failing_assignments(canvas_url, canvas_token, course_id):
                    raise RuntimeError("Canvas exploded")

                with patch.object(
                    main,
                    "fetch_canvas_courses",
                    new=AsyncMock(
                        return_value=[
                            {"id": 42, "name": "Biology", "course_code": "BIO-101"}
                        ]
                    ),
                ), patch.object(
                    main,
                    "fetch_canvas_course_assignments",
                    new=failing_assignments,
                ):
                    response = client.get("/api/canvas/courses/42/assignments")

                self.assertEqual(response.status_code, 502)
                self.assertIn("Canvas exploded", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
