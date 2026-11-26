import os, re, json, random
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-before-deploying")
db_url = os.getenv("DATABASE_URL", "sqlite:///studybuddy.db")
if db_url.startswith("mysql://"):
    db_url = db_url.replace("mysql://", "mysql+pymysql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
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
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/signup", methods=["GET","POST"])
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

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json(silent=True) or {}
    question = str(data.get("message","")).strip()
    if not question: return jsonify({"error":"Please enter a question."}), 400
    if len(question) > 5000: return jsonify({"error":"Question is too long (maximum 5,000 characters)."}), 400
    uid = session["user_id"]
    answer = ai_answer(question)
    db.session.add(ChatMessage(user_id=uid, role="user", content=question))
    db.session.add(ChatMessage(user_id=uid, role="assistant", content=answer))
    db.session.commit()
    return jsonify({"answer":answer})

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
@app.route("/quiz")
@login_required
def quiz():
    return render_template("quiz.html", user=current_user(), topics=list(QUIZZES.keys()))

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
    topic = data.get("topic")
    answers = data.get("answers",[])
    if topic not in QUIZZES or not isinstance(answers,list): return jsonify({"error":"Invalid quiz submission."}), 400
    qs = QUIZZES[topic]
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
    return jsonify({"status":"ok","app":"Study Buddy"})

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG","0") == "1", port=int(os.getenv("PORT","5000")))
