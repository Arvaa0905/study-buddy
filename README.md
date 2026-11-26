# Study Buddy — AI web app for smarter studying

A full-stack student study portal based on the supplied synopsis: secure accounts, AI doubt-solving, notes management, quizzes, dashboard, chat history and quiz scores.

## Stack
- Frontend: HTML5, CSS3, JavaScript
- Backend: Python + Flask
- Database: MySQL (PyMySQL); SQLite is the zero-configuration local demo default
- Authentication: Flask sessions + Werkzeug password hashing
- AI: Google Gemini API via the official `google-genai` SDK (optional API key)
- Tools: Git/GitHub, VS Code, Postman

## Run locally (Windows PowerShell)
1. Install Python 3.10+ and MySQL if you want MySQL storage.
2. Extract the ZIP and open a terminal in the project folder.
3. Create an environment and install packages:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env`. Change `SECRET_KEY`. For SQLite demo, leave `DATABASE_URL` unset.
5. Optional MySQL setup:
   ```sql
   CREATE DATABASE studybuddy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'studybuddy'@'localhost' IDENTIFIED BY 'your_password';
   GRANT ALL PRIVILEGES ON studybuddy.* TO 'studybuddy'@'localhost';
   FLUSH PRIVILEGES;
   ```
   Then set `DATABASE_URL=mysql+pymysql://studybuddy:your_password@localhost:3306/studybuddy` in `.env`.
6. Optional AI: get a Gemini API key from Google AI Studio and set `GEMINI_API_KEY` in `.env`. The default model is `gemini-3.8-flash`; change `GEMINI_MODEL` if needed. Without a key, chat runs in clearly labelled demo tutor mode.
7. Start:
   ```powershell
   python -m flask --app app run
   ```
8. Open http://127.0.0.1:5000 and create an account.

## Features
- Signup/login/logout; per-user private notes and history
- Dashboard with notes, chats and quiz stats
- Create, edit, search and delete notes
- Tutor chat with persisted history
- Topic quizzes for Python, Computer Science and Biology, with answer explanations
- Quiz result history
- JSON APIs under `/api`; health check at `/health`

## Run with Docker (recommended for production)
1. Copy `.env.example` to `.env` and set strong values for `SECRET_KEY`, `MYSQL_PASSWORD`, and `MYSQL_ROOT_PASSWORD`:
   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Build and start the MySQL database and Gunicorn web service:
   ```powershell
   docker compose up -d --build
   ```
3. Optional: include the Nginx reverse proxy (`http://localhost`):
   ```powershell
   docker compose --profile proxy up -d --build
   ```
4. Check status and health:
   ```powershell
   docker compose ps
   ```
   Open `http://127.0.0.1:5000` (or `http://localhost` with the `proxy` profile).

## Security and production notes
- Passwords are hashed; database queries are ORM parameterized; notes/results are scoped to the logged-in user.
- CSRF protection (`X-CSRFToken` / form `csrf_token`), security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security` over HTTPS), `ProxyFix`, and per-IP rate limiting on `/login`, `/signup`, and `/api/chat` are built in.
- In production (`APP_ENV=production`), `SECRET_KEY` must be set to a non-default random value.
- Set `SESSION_COOKIE_SECURE=1` when serving behind HTTPS.
- AI calls may incur provider charges. Never put API keys in frontend JavaScript.


## AI tutor response formatting and interface
Gemini is instructed to give concise Markdown answers with a direct answer, clear explanation steps, examples and key takeaways when appropriate. The chat view safely renders Markdown with DOMPurify, formats code blocks with highlight.js, and provides copy-code actions. Chat transitions, typing indicators, subtle gradient surfaces and hover feedback are inspired by React Bits interaction patterns. The app remains Flask + HTML/CSS/JavaScript; React Bits publishes React components, so this version uses compatible design patterns rather than adding a separate React runtime.
