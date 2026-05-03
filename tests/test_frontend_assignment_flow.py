from pathlib import Path
import unittest


BASE_DIR = Path(__file__).resolve().parents[1]


class FrontendAssignmentFlowTest(unittest.TestCase):
    def test_frontend_uses_current_auth_api_routes(self):
        frontend_scripts = [
            BASE_DIR / "frontend" / "jss" / "login.js",
            BASE_DIR / "frontend" / "jss" / "logout.js",
            BASE_DIR / "frontend" / "jss" / "main.js",
            BASE_DIR / "frontend" / "jss" / "create-user.js",
        ]
        combined_scripts = "\n".join(
            path.read_text(encoding="utf-8") for path in frontend_scripts
        )

        self.assertIn("/api/auth/login", combined_scripts)
        self.assertIn("/api/auth/logout", combined_scripts)
        self.assertIn("/api/auth/me", combined_scripts)
        self.assertIn("/api/auth/register", combined_scripts)
        self.assertNotIn('"/auth/', combined_scripts)

    def test_upload_content_links_to_tutor(self):
        upload_html = (BASE_DIR / "frontend" / "upload-content.html").read_text(
            encoding="utf-8"
        )
        upload_js = (BASE_DIR / "frontend" / "jss" / "upload-content.js").read_text(
            encoding="utf-8"
        )

        self.assertEqual(upload_html.count('href="/tutor"'), 1)
        self.assertIn('class="btn upload-tutor-action"', upload_html)
        self.assertNotIn("tutorLink", upload_js)

    def test_store_page_sells_animal_emoji_for_coins(self):
        store_html = (BASE_DIR / "frontend" / "store-page.html").read_text(
            encoding="utf-8"
        )
        store_js = (BASE_DIR / "frontend" / "jss" / "store.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("Animal Emoji Shop", store_html)
        self.assertIn('id="store-items"', store_html)
        self.assertIn("/api/store/purchase", store_js)
        self.assertIn("item.emoji", store_js)

    def test_tutor_page_has_assignment_selector(self):
        tutor_html = (BASE_DIR / "frontend" / "tutor.html").read_text(encoding="utf-8")

        self.assertIn('id="assignment-picker"', tutor_html)
        self.assertIn('id="assignmentSelect"', tutor_html)
        self.assertIn('id="assignment-summary"', tutor_html)

    def test_session_start_payload_includes_assignment(self):
        gemini_client = (BASE_DIR / "frontend" / "jss" / "gemini-client.js").read_text(
            encoding="utf-8"
        )
        main_js = (BASE_DIR / "frontend" / "jss" / "main.js").read_text(encoding="utf-8")

        self.assertIn("assignment = null", gemini_client)
        self.assertIn("assignment: assignment", gemini_client)
        self.assertIn("pendingAssignment", main_js)
        self.assertIn("getSelectedAssignment()", main_js)
        self.assertIn("/assignments", main_js)


if __name__ == "__main__":
    unittest.main()
