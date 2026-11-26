import os
import re
import tempfile
import unittest
from unittest.mock import patch

# Configure isolated test environment before importing app
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only"
os.environ["GEMINI_API_KEY"] = ""
os.environ["RATELIMIT_ENABLED"] = "0"

import app as sb  # noqa: E402


class StudyBuddyTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        with sb.app.app_context():
            sb.db.session.remove()
            sb.db.engine.dispose()
        if os.path.exists(_tmp_db.name):
            os.remove(_tmp_db.name)

    def setUp(self):
        sb.app.config["TESTING"] = True
        sb.app.config["CSRF_ENABLED"] = True
        with sb.app.app_context():
            sb.db.drop_all()
            sb.db.create_all()
        self.client = sb.app.test_client()

    def _get_csrf(self, html: str) -> str:
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        self.assertIsNotNone(match, "CSRF meta tag not found in response")
        return match.group(1)

    def _signup(self, name="Alice", email="alice@example.com", password="password123"):
        page = self.client.get("/signup")
        token = self._get_csrf(page.get_data(as_text=True))
        return self.client.post(
            "/signup",
            data={"name": name, "email": email, "password": password, "csrf_token": token},
            follow_redirects=True,
        )

    def test_health_and_security_headers(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "ok")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_database_url_normalization(self):
        self.assertEqual(
            sb.normalize_database_url("postgres://user:pass@db.supabase.co:5432/postgres"),
            "postgresql+psycopg://user:pass@db.supabase.co:5432/postgres",
        )
        self.assertEqual(
            sb.normalize_database_url("postgresql://user:pass@aws-0.pooler.supabase.com:6543/postgres"),
            "postgresql+psycopg://user:pass@aws-0.pooler.supabase.com:6543/postgres",
        )
        self.assertEqual(
            sb.normalize_database_url("mysql://user:pass@localhost:3306/studybuddy"),
            "mysql+pymysql://user:pass@localhost:3306/studybuddy",
        )

    def test_csrf_blocks_missing_token(self):
        resp = self.client.post("/login", data={"email": "a@b.com", "password": "secret"})
        self.assertEqual(resp.status_code, 400)

    def test_auth_notes_chat_and_quiz_flow(self):
        res = self._signup()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Alice", res.data)

        # Save a note using CSRF token
        notes_page = self.client.get("/notes")
        token = self._get_csrf(notes_page.get_data(as_text=True))
        save_res = self.client.post(
            "/notes/save",
            data={
                "title": "Cells",
                "subject": "Biology",
                "content": "Mitochondria make ATP.",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertEqual(save_res.status_code, 200)
        self.assertIn(b"Cells", save_res.data)

        # Chat API (demo mode when GEMINI_API_KEY is empty)
        chat_res = self.client.post(
            "/api/chat",
            json={"message": "What is ATP?"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(chat_res.status_code, 200)
        self.assertIn("Demo tutor mode", chat_res.get_json()["answer"])

        # Quiz API
        quiz_res = self.client.get("/api/quiz/Python")
        self.assertEqual(quiz_res.status_code, 200)
        submit_res = self.client.post(
            "/api/quiz/submit",
            json={"topic": "Python", "answers": [1, 2, 1, 0, 2]},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(submit_res.status_code, 200)
        self.assertEqual(submit_res.get_json()["score"], 5)

    def test_custom_quiz_generation_and_chat_topic_detection(self):
        res = self._signup(name="Bob", email="bob@example.com")
        self.assertEqual(res.status_code, 200)
        quiz_page = self.client.get("/quiz")
        token = self._get_csrf(quiz_page.get_data(as_text=True))

        # Chat detects quiz request and returns quiz_topic
        chat_res = self.client.post(
            "/api/chat",
            json={"message": "Quiz me on Photosynthesis"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(chat_res.status_code, 200)
        self.assertEqual(chat_res.get_json().get("quiz_topic"), "Photosynthesis")

        # Without GEMINI_API_KEY, custom non-preset topic returns 503
        missing_key_res = self.client.post(
            "/api/quiz/generate",
            json={"topic": "Photosynthesis"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(missing_key_res.status_code, 503)

        # With generated questions (mocked Gemini output), generate + submit works end-to-end
        mock_questions = [
            {
                "q": "Where does photosynthesis occur?",
                "options": ["Nucleus", "Chloroplast", "Mitochondria", "Ribosome"],
                "answer": 1,
                "why": "Chloroplasts contain chlorophyll for photosynthesis.",
            },
            {
                "q": "Which gas is absorbed by plants during photosynthesis?",
                "options": ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"],
                "answer": 2,
                "why": "Plants take in carbon dioxide to produce glucose.",
            },
            {
                "q": "What is the main sugar produced?",
                "options": ["Glucose", "Lactose", "Sucrose", "Maltose"],
                "answer": 0,
                "why": "Photosynthesis produces glucose.",
            },
        ]
        with patch.object(sb, "generate_custom_quiz", return_value=mock_questions):
            gen_res = self.client.post(
                "/api/quiz/generate",
                json={"topic": "Photosynthesis", "difficulty": "easy", "num_questions": 3},
                headers={"X-CSRFToken": token},
            )
            self.assertEqual(gen_res.status_code, 200)
            gen_data = gen_res.get_json()
            self.assertEqual(gen_data["topic"], "Photosynthesis")
            self.assertEqual(len(gen_data["questions"]), 3)
            self.assertNotIn("answer", gen_data["questions"][0])
            saved_id = gen_data["id"]

            # Chat request also auto-saves a custom quiz
            chat_saved_res = self.client.post(
                "/api/chat",
                json={"message": "Quiz me on Cell Respiration"},
                headers={"X-CSRFToken": token},
            )
            self.assertEqual(chat_saved_res.status_code, 200)
            self.assertIsNotNone(chat_saved_res.get_json().get("saved_quiz_id"))

        # Saved quizzes appear in the Practice Quiz tab
        quiz_tab = self.client.get("/quiz")
        self.assertIn(b"Photosynthesis", quiz_tab.data)
        self.assertIn(b"Cell Respiration", quiz_tab.data)

        # Load saved quiz later and submit it
        load_res = self.client.get(f"/api/quiz/saved/{saved_id}")
        self.assertEqual(load_res.status_code, 200)
        self.assertEqual(load_res.get_json()["topic"], "Photosynthesis")

        submit_res = self.client.post(
            "/api/quiz/submit",
            json={"topic": "Photosynthesis", "answers": [1, 2, 0], "saved_quiz_id": saved_id},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(submit_res.status_code, 200)
        self.assertEqual(submit_res.get_json()["score"], 3)
        self.assertEqual(submit_res.get_json()["percent"], 100)

        # Delete saved quiz
        del_res = self.client.post(
            f"/api/quiz/saved/{saved_id}/delete",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(self.client.get(f"/api/quiz/saved/{saved_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()

