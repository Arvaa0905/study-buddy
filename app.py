import os, re, json, random, hmac, secrets, logging, time, threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

_WEAK_SECRETS = {
    "",
    "change-this-secret-before-deploying",
    "replace-with-a-long-random-secret",
}
_app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
_secret_key = os.getenv("SECRET_KEY", "change-this-secret-before-deploying")
if _app_env == "production" and _secret_key in _WEAK_SECRETS:
    raise RuntimeError("SECRET_KEY must be set to a strong random value when APP_ENV=production.")

app = Flask(__name__)
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
if _secret_key in _WEAK_SECRETS:
    app.logger.warning("Using default SECRET_KEY; set a strong random SECRET_KEY before deploying.")

app.config["SECRET_KEY"] = _secret_key
def normalize_database_url(raw_url):
    """Normalize MySQL and PostgreSQL/Supabase URLs for SQLAlchemy drivers."""
    url = (raw_url or "").strip() or "sqlite:///studybuddy.db"
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+pymysql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

db_url = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///studybuddy.db"))
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if not db_url.startswith("sqlite"):
    engine_options = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "280")),
    }
    if db_url.startswith("postgresql+psycopg://"):
        connect_args = {}
        ssl_mode = os.getenv("DB_SSL_MODE")
        if ssl_mode:
            connect_args["sslmode"] = ssl_mode
        elif ("supabase.co" in db_url or "supabase.com" in db_url) and "sslmode=" not in db_url:
            connect_args["sslmode"] = "require"
        if ":6543" in db_url or os.getenv("DB_DISABLE_PREPARED_STATEMENTS") == "1":
            connect_args["prepare_threshold"] = None
        if connect_args:
            engine_options["connect_args"] = connect_args
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=int(os.getenv("SESSION_LIFETIME_DAYS", "7")))
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(1024 * 1024)))
app.config["CSRF_ENABLED"] = os.getenv("CSRF_ENABLED", "1") == "1"
app.config["RATELIMIT_ENABLED"] = os.getenv("RATELIMIT_ENABLED", "1") == "1"

if os.getenv("TRUST_PROXY", "1") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    subject = db.Column(db.String(100), default="General")
    content = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic = db.Column(db.String(120), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SavedQuiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    topic = db.Column(db.String(120), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False, default="medium")
    questions_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def questions(self):
        return json.loads(self.questions_json)

_rate_lock = threading.Lock()
_rate_buckets = defaultdict(list)

def get_csrf_token():
    """Return the per-session CSRF token, creating one if needed."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

@app.context_processor
def inject_security_context():
    return {"csrf_token": get_csrf_token}

@app.before_request
def verify_csrf():
    if not app.config.get("CSRF_ENABLED", True):
        return
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        expected = session.get("_csrf_token")
        provided = request.headers.get("X-CSRFToken") or request.form.get("csrf_token") or ""
        if not expected or not hmac.compare_digest(str(expected), str(provided)):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Invalid or missing CSRF token."}), 400
            abort(400, description="Invalid or missing CSRF token.")

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

def rate_limit(max_requests, window_seconds, methods=("POST",)):
    """Simple sliding-window per-IP rate limiter for sensitive endpoints."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if app.config.get("RATELIMIT_ENABLED", True) and request.method in methods:
                now = time.monotonic()
                client_ip = (request.remote_addr or "unknown").split(",")[0].strip()
                key = (request.endpoint or fn.__name__, client_ip)
                with _rate_lock:
                    recent = [t for t in _rate_buckets[key] if now - t < window_seconds]
                    if len(recent) >= max_requests:
                        _rate_buckets[key] = recent
                        if request.path.startswith("/api/"):
                            return jsonify({"error": "Too many requests. Please wait a moment and try again."}), 429
                        flash("Too many attempts. Please wait a moment and try again.", "error")
                        return render_template("auth.html", mode="signup" if request.endpoint == "signup" else "login"), 429
                    recent.append(now)
                    _rate_buckets[key] = recent
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error":"Please log in first."}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def current_user():
    return db.session.get(User, session.get("user_id"))

@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/signup", methods=["GET","POST"])
@rate_limit(10, 60)
def signup():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password of at least 8 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(name=name, email=email, password_hash=generate_password_hash(password))
            db.session.add(user); db.session.commit()
            session.clear(); session["user_id"] = user.id
            flash("Welcome to Study Buddy!", "success")
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="signup")

@app.route("/login", methods=["GET","POST"])
@rate_limit(15, 60)
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, request.form.get("password","")):
            session.clear(); session["user_id"] = user.id
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    notes = Note.query.filter_by(user_id=uid).order_by(Note.updated_at.desc()).limit(4).all()
    results = QuizResult.query.filter_by(user_id=uid).order_by(QuizResult.created_at.desc()).limit(5).all()
    total_notes = Note.query.filter_by(user_id=uid).count()
    chats = ChatMessage.query.filter_by(user_id=uid, role="user").count()
    avg = round(sum(r.score/r.total*100 for r in results)/len(results)) if results else 0
    return render_template("dashboard.html", user=current_user(), notes=notes, results=results,
                           total_notes=total_notes, chats=chats, avg=avg)

@app.route("/notes")
@login_required
def notes():
    q = request.args.get("q","").strip()
    query = Note.query.filter_by(user_id=session["user_id"])
    if q: query = query.filter(db.or_(Note.title.ilike(f"%{q}%"), Note.subject.ilike(f"%{q}%"), Note.content.ilike(f"%{q}%")))
    all_notes = query.order_by(Note.updated_at.desc()).all()
    return render_template("notes.html", user=current_user(), notes=all_notes, q=q)

@app.route("/notes/save", methods=["POST"])
@login_required
def save_note():
    uid = session["user_id"]
    note_id = request.form.get("id","").strip()
    title = request.form.get("title","").strip()
    content = request.form.get("content","").strip()
    subject = request.form.get("subject","General").strip()[:100] or "General"
    if not title or not content:
        flash("A title and note content are required.", "error")
        return redirect(url_for("notes"))
    note = Note.query.filter_by(id=int(note_id), user_id=uid).first() if note_id.isdigit() else None
    if note_id and not note:
        flash("Note not found.", "error"); return redirect(url_for("notes"))
    if not note:
        note = Note(user_id=uid, title=title, subject=subject, content=content); db.session.add(note)
    else:
        note.title=title; note.subject=subject; note.content=content
    db.session.commit(); flash("Note saved.", "success")
    return redirect(url_for("notes"))

@app.route("/notes/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_note(note_id):
    note = Note.query.filter_by(id=note_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(note); db.session.commit(); flash("Note deleted.", "success")
    return redirect(url_for("notes"))

@app.route("/chat")
@login_required
def chat():
    history = ChatMessage.query.filter_by(user_id=session["user_id"]).order_by(ChatMessage.created_at.asc()).all()
    return render_template("chat.html", user=current_user(), history=history)

def ai_answer(question):
    """Generate a structured, student-friendly answer with Gemini."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return (
            "## Demo tutor mode\n\n"
            "Gemini is not configured yet. Add `GEMINI_API_KEY` to your `.env` file "
            "and restart Study Buddy to receive AI-generated explanations.\n\n"
            "### While you set it up\n"
            "- Start with the topic's definition.\n"
            "- Break the concept into smaller steps.\n"
            "- Work through one example and check your understanding."
        )
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are Study Buddy, a patient academic tutor. Teach clearly, not by dumping information. "
                    "Return clean, readable Markdown. For normal academic questions, begin with a short direct answer, "
                    "then use ## Explanation with numbered steps or concise bullets, ## Example with a practical example, "
                    "and ## Key takeaways with 2-4 short bullets. Adapt this structure: do not force sections for greetings, "
                    "tiny factual questions, or requests needing another format. Use short paragraphs, descriptive headings, "
                    "and tables only when useful. Put code in fenced blocks with a language tag and explain important lines. "
                    "Use LaTeX for maths when helpful. Define technical terms simply. Avoid giant paragraphs, excessive bold, "
                    "repeated conclusions, unnecessary emojis, and filler. Be accurate and admit uncertainty. "
                    "For multi-step problems, provide concise student-friendly explanations without revealing hidden chain-of-thought."
                ),
                temperature=0.35,
                max_output_tokens=1600,
            ),
        )
        answer=response.text
        if answer and answer.strip(): return answer.strip()
        raise RuntimeError("Gemini returned an empty response.")
    except Exception:
        app.logger.exception("Gemini API request failed")
        return ("## I couldn't reach Gemini just now\n\n"
                "Check `GEMINI_API_KEY`, `GEMINI_MODEL`, your network connection, and API quota, then try again.")

def extract_quiz_topic(message):
    """Detect if a chat message requests a quiz on a specific topic."""
    patterns = (
        r"(?:make|create|generate|build|give\s+me|start)\s+(?:a\s+)?(?:custom\s+)?quiz\s+(?:on|about|for)\s+(.+)",
        r"quiz\s+me\s+(?:on|about)\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, message.strip(), re.IGNORECASE)
        if match:
            topic = re.sub(r"[?.!]+$", "", match.group(1)).strip()
            if topic:
                return topic[:120]
    return None

@app.route("/api/chat", methods=["POST"])
@login_required
@rate_limit(30, 60)
def api_chat():
    data = request.get_json(silent=True) or {}
    question = str(data.get("message","")).strip()
    if not question: return jsonify({"error":"Please enter a question."}), 400
    if len(question) > 5000: return jsonify({"error":"Question is too long (maximum 5,000 characters)."}), 400
    uid = session["user_id"]
    quiz_topic = extract_quiz_topic(question)
    answer = ai_answer(question)
    db.session.add(ChatMessage(user_id=uid, role="user", content=question))
    db.session.add(ChatMessage(user_id=uid, role="assistant", content=answer))
    saved_quiz_id = None
    if quiz_topic:
        try:
            generated_qs = generate_custom_quiz(quiz_topic)
            saved = SavedQuiz(
                user_id=uid,
                topic=quiz_topic,
                difficulty="medium",
                questions_json=json.dumps(generated_qs),
            )
            db.session.add(saved)
            db.session.flush()
            saved_quiz_id = saved.id
        except Exception:
            app.logger.info("Skipping auto-save for chat quiz topic %r", quiz_topic)
    db.session.commit()
    payload = {"answer": answer}
    if quiz_topic:
        payload["quiz_topic"] = quiz_topic
    if saved_quiz_id is not None:
        payload["saved_quiz_id"] = saved_quiz_id
    return jsonify(payload)

QUIZZES = {
 "Python":[
  {"q":"Which keyword defines a function in Python?","options":["func","def","function","method"],"answer":1,"why":"Python uses `def` to define a function."},
  {"q":"Which type stores key-value pairs?","options":["list","tuple","dictionary","set"],"answer":2,"why":"A dictionary maps keys to values."},
  {"q":"What does len([2, 4, 6]) return?","options":["2","3","6","12"],"answer":1,"why":"There are three elements in the list."},
  {"q":"Which value represents absence of a value?","options":["None","void","null","empty"],"answer":0,"why":"Python uses `None`."},
  {"q":"Which loop iterates over a sequence?","options":["repeat","foreach","for","loop"],"answer":2,"why":"A `for` loop iterates over iterable objects."}],
 "Computer Science":[
  {"q":"What does CPU stand for?","options":["Central Processing Unit","Computer Personal Utility","Core Program Unit","Central Power User"],"answer":0,"why":"CPU means Central Processing Unit."},
  {"q":"Which data structure follows FIFO?","options":["Stack","Queue","Tree","Graph"],"answer":1,"why":"A queue processes the first item added first."},
  {"q":"What is an algorithm?","options":["A programming language","A finite step-by-step procedure","A database","A computer part"],"answer":1,"why":"An algorithm is a sequence of steps to solve a problem."},
  {"q":"Which is an output device?","options":["Keyboard","Mouse","Monitor","Scanner"],"answer":2,"why":"A monitor displays information."},
  {"q":"What does RAM primarily provide?","options":["Permanent storage","Temporary working memory","Internet access","Power supply"],"answer":1,"why":"RAM stores data temporarily while programs run."}],
 "Biology":[
  {"q":"Which organelle is known as the powerhouse of the cell?","options":["Nucleus","Mitochondrion","Ribosome","Golgi body"],"answer":1,"why":"Mitochondria produce much of the cell's usable energy."},
  {"q":"What carries genetic information?","options":["DNA","Glucose","Lipid","Water"],"answer":0,"why":"DNA stores hereditary information."},
  {"q":"Which blood cells help fight infection?","options":["Red blood cells","Platelets","White blood cells","Plasma"],"answer":2,"why":"White blood cells are part of the immune system."},
  {"q":"What is the basic unit of life?","options":["Organ","Tissue","Cell","Atom"],"answer":2,"why":"The cell is the basic structural and functional unit of life."},
  {"q":"Plants make food mainly through?","options":["Respiration","Photosynthesis","Fermentation","Digestion"],"answer":1,"why":"Photosynthesis converts light energy into chemical energy."}]
}
def generate_custom_quiz(topic, num_questions=5, difficulty="medium"):
    """Generate a custom multiple-choice quiz on any topic using Gemini."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        for preset_topic, preset_qs in QUIZZES.items():
            if preset_topic.lower() == topic.lower():
                return preset_qs
        raise ValueError(
            "Custom AI quizzes require GEMINI_API_KEY in your .env file "
            "(or choose Python, Computer Science, or Biology in demo mode)."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = (
        f"Create a {difficulty} difficulty multiple-choice quiz with exactly {num_questions} questions "
        f"about: {topic}.\n"
        "Return a JSON array of objects. Each object MUST have:\n"
        '- "q": concise question string\n'
        '- "options": array of exactly 4 distinct answer strings\n'
        '- "answer": integer index (0, 1, 2, or 3) of the correct option\n'
        '- "why": short 1-sentence explanation of why the answer is correct'
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
            max_output_tokens=2000,
        ),
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError("Gemini did not return a valid question list.")

    cleaned = []
    for item in parsed[:num_questions]:
        if not isinstance(item, dict):
            continue
        q_text = str(item.get("q", "")).strip()
        options = item.get("options")
        ans = item.get("answer")
        why = str(item.get("why", "")).strip() or "Review this concept to reinforce your understanding."
        if (
            q_text
            and isinstance(options, list)
            and len(options) == 4
            and isinstance(ans, int)
            and 0 <= ans < 4
        ):
            cleaned.append({
                "q": q_text[:300],
                "options": [str(opt).strip()[:160] for opt in options],
                "answer": ans,
                "why": why[:300],
            })
    if not cleaned:
        raise RuntimeError("Generated quiz questions were invalid.")
    return cleaned

@app.route("/quiz")
@login_required
def quiz():
    saved = (
        SavedQuiz.query.filter_by(user_id=session["user_id"])
        .order_by(SavedQuiz.created_at.desc())
        .all()
    )
    saved_quizzes = [
        {
            "id": sq.id,
            "topic": sq.topic,
            "difficulty": sq.difficulty,
            "count": len(sq.questions()),
            "created_at": sq.created_at,
        }
        for sq in saved
    ]
    return render_template(
        "quiz.html",
        user=current_user(),
        topics=list(QUIZZES.keys()),
        saved_quizzes=saved_quizzes,
    )

@app.route("/api/quiz/generate", methods=["POST"])
@login_required
@rate_limit(20, 60)
def quiz_generate():
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic", "")).strip()[:120]
    if not topic:
        return jsonify({"error": "Please enter a quiz topic."}), 400
    difficulty = str(data.get("difficulty", "medium")).strip().lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    try:
        num_questions = int(data.get("num_questions", 5))
    except (TypeError, ValueError):
        num_questions = 5
    num_questions = max(3, min(num_questions, 10))

    try:
        questions = generate_custom_quiz(topic, num_questions=num_questions, difficulty=difficulty)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception:
        app.logger.exception("Custom quiz generation failed")
        return jsonify({"error": "Could not generate quiz right now. Please try again."}), 502

    saved = SavedQuiz(
        user_id=session["user_id"],
        topic=topic,
        difficulty=difficulty,
        questions_json=json.dumps(questions),
    )
    db.session.add(saved)
    db.session.commit()

    session["active_quiz"] = {"id": saved.id, "topic": topic, "questions": questions}
    public_questions = [{"q": q["q"], "options": q["options"]} for q in questions]
    return jsonify({
        "id": saved.id,
        "topic": topic,
        "difficulty": difficulty,
        "questions": public_questions,
    })

@app.route("/api/quiz/saved/<int:quiz_id>")
@login_required
def get_saved_quiz(quiz_id):
    saved = SavedQuiz.query.filter_by(id=quiz_id, user_id=session["user_id"]).first_or_404()
    questions = saved.questions()
    session["active_quiz"] = {"id": saved.id, "topic": saved.topic, "questions": questions}
    public_questions = [{"q": q["q"], "options": q["options"]} for q in questions]
    return jsonify({"id": saved.id, "topic": saved.topic, "questions": public_questions})

@app.route("/api/quiz/saved/<int:quiz_id>/delete", methods=["POST"])
@login_required
def delete_saved_quiz(quiz_id):
    saved = SavedQuiz.query.filter_by(id=quiz_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(saved)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/quiz/<topic>")
@login_required
def quiz_questions(topic):
    if topic not in QUIZZES: return jsonify({"error":"Unknown quiz topic."}), 404
    questions = [{"q":q["q"],"options":q["options"]} for q in QUIZZES[topic]]
    return jsonify({"topic":topic,"questions":questions})

@app.route("/api/quiz/submit", methods=["POST"])
@login_required
def quiz_submit():
    data = request.get_json(silent=True) or {}
    topic = str(data.get("topic") or "").strip()
    answers = data.get("answers",[])
    saved_quiz_id = data.get("saved_quiz_id")
    active = session.get("active_quiz")
    if isinstance(active, dict) and active.get("topic") == topic and isinstance(active.get("questions"), list):
        qs = active["questions"]
    elif isinstance(saved_quiz_id, int):
        saved = SavedQuiz.query.filter_by(id=saved_quiz_id, user_id=session["user_id"]).first()
        if not saved:
            return jsonify({"error": "Invalid quiz submission."}), 400
        qs = saved.questions()
        topic = saved.topic
    elif topic in QUIZZES:
        qs = QUIZZES[topic]
    else:
        return jsonify({"error":"Invalid quiz submission."}), 400
    if not isinstance(answers, list):
        return jsonify({"error":"Invalid quiz submission."}), 400
    score = sum(1 for i,q in enumerate(qs) if i < len(answers) and answers[i] == q["answer"])
    result = QuizResult(user_id=session["user_id"], topic=topic, score=score, total=len(qs))
    db.session.add(result); db.session.commit()
    return jsonify({"score":score,"total":len(qs),"percent":round(score/len(qs)*100),
                    "review":[{"q":q["q"],"correct":q["options"][q["answer"]],"why":q["why"],
                               "chosen":q["options"][answers[i]] if i<len(answers) and isinstance(answers[i],int) and 0<=answers[i]<len(q["options"]) else "Not answered",
                               "is_correct":i<len(answers) and answers[i]==q["answer"]} for i,q in enumerate(qs)]})

@app.route("/history")
@login_required
def history():
    results = QuizResult.query.filter_by(user_id=session["user_id"]).order_by(QuizResult.created_at.desc()).all()
    return render_template("history.html", user=current_user(), results=results)

@app.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "app": "Study Buddy", "database": "ok"})
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"status": "error", "app": "Study Buddy", "database": "unavailable"}), 503

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(429)
@app.errorhandler(500)
def handle_error(err):
    code = getattr(err, "code", 500)
    if code >= 500:
        app.logger.exception("Unhandled server error")
    if request.path.startswith("/api/"):
        msg = err.description if code < 500 else "Internal server error."
        return jsonify({"error": msg}), code
    return render_template("auth.html", mode="login") if code == 401 else (
        f"<h1>{code}</h1><p>{err.description if code < 500 else 'Something went wrong. Please try again.'}</p>",
        code,
    )

def init_db():
    """Create database tables within an application context."""
    with app.app_context():
        db.create_all()

if os.getenv("AUTO_CREATE_TABLES", "1") == "1":
    init_db()

if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
