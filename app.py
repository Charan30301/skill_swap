import os
import sqlite3
import psycopg
from flask_wtf.csrf import CSRFProtect
from psycopg.rows import dict_row

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

import sqlite3
import os
import uuid


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

DATABASE = os.path.join(
    BASE_DIR,
    "skill_swap.db"
)

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "uploads",
    "videos"
)

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


import os
from datetime import timedelta

app = Flask(__name__)

secret_key = os.environ.get("FLASK_SECRET_KEY")
if not secret_key:
    raise RuntimeError("Set FLASK_SECRET_KEY before starting the app.")

app.config["SECRET_KEY"] = secret_key

app.config.update(
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)

csrf = CSRFProtect(app)

from authlib.integrations.flask_client import OAuth

oauth = OAuth(app)

oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid email profile"
    },
)

app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024

ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "webm",
    "ogg",
    "mov"
}


# ============================================================
# DATABASE
# ============================================================

def get_db():
    if DATABASE_URL:
        return psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=10
        )

    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    return db

def init_database():

    db = get_db()
    
    db.executescript("""

    CREATE TABLE IF NOT EXISTS users (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT NOT NULL,

        email TEXT UNIQUE NOT NULL,

        password TEXT NOT NULL,

        role TEXT NOT NULL DEFAULT 'user',
        credits INTEGER NOT NULL DEFAULT 0 CHECK (credits >= 0),
        bio TEXT DEFAULT '',

        skills TEXT DEFAULT '',

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

    );


    CREATE TABLE IF NOT EXISTS videos (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        user_id INTEGER NOT NULL,

        title TEXT NOT NULL,

        description TEXT DEFAULT '',

        filename TEXT NOT NULL,

        skill TEXT DEFAULT '',

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE

    );


    CREATE TABLE IF NOT EXISTS comments (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        video_id INTEGER NOT NULL,

        user_id INTEGER NOT NULL,

        comment TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(video_id)
        REFERENCES videos(id)
        ON DELETE CASCADE,

        FOREIGN KEY(user_id)
        REFERENCES users(id)
        ON DELETE CASCADE

    );


    CREATE TABLE IF NOT EXISTS messages (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sender_id INTEGER NOT NULL,

        receiver_id INTEGER NOT NULL,

        message TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(sender_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

        FOREIGN KEY(receiver_id)
        REFERENCES users(id)
        ON DELETE CASCADE

    );


    CREATE TABLE IF NOT EXISTS meetings (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        host_id INTEGER NOT NULL,

        guest_id INTEGER,

        title TEXT NOT NULL,

        meeting_url TEXT NOT NULL,

        scheduled_at TEXT NOT NULL,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY(host_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

        FOREIGN KEY(guest_id)
        REFERENCES users(id)
        ON DELETE SET NULL

    );
    CREATE TABLE IF NOT EXISTS credit_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
    CREATE TABLE IF NOT EXISTS learning_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    learner_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested'
        CHECK (status IN ('requested', 'accepted', 'completed', 'cancelled')),
    teacher_confirmed INTEGER NOT NULL DEFAULT 0,
    learner_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (teacher_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (learner_id) REFERENCES users(id) ON DELETE CASCADE,
    CHECK (teacher_id != learner_id)
); 
    """)

    user_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(users)").fetchall()
    }

    if "credits" not in user_columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN credits INTEGER NOT NULL DEFAULT 0"
        )
    # Create default admin account

    admin = db.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        ("admin@skillswap.com",)
    ).fetchone()


    if admin is None:

        db.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password,
                role,
                bio,
                skills
            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,

            (
                "Admin",
                "admin@skillswap.com",
                generate_password_hash("admin123"),
                "admin",
                "Skill Swap Administrator",
                "Administration"
            )
        )


    db.commit()

    db.close()


# ============================================================
# CURRENT USER
# ============================================================

@app.context_processor
def inject_current_user():

    if "user_id" in session:

        return {
            "current_user": {
                "user_id": session.get("user_id"),
                "name": session.get("name"),
                "role": session.get("role")
            }
        }

    return {
        "current_user": {}
    }


# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required():

    return "user_id" in session


def admin_required():

    return session.get("role") == "admin"


# ============================================================
# CSS FILE
# ============================================================

@app.route("/css/<path:filename>")
def css(filename):

    return send_from_directory(
        os.path.join(BASE_DIR, "templates"),
        filename
    )


# ============================================================
# JAVASCRIPT FILE
# ============================================================

@app.route("/js/<path:filename>")
def javascript(filename):

    return send_from_directory(
        os.path.join(BASE_DIR, "templates"),
        filename
    )


# ============================================================
# UPLOADED VIDEOS
# ============================================================

@app.route("/uploads/videos/<path:filename>")
def uploaded_video(filename):

    return send_from_directory(
        UPLOAD_FOLDER,
        filename
    )


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def index():

    db = get_db()

    videos = db.execute(
        """
        SELECT
            videos.*,
            users.name

        FROM videos

        JOIN users
        ON users.id = videos.user_id

        ORDER BY videos.id DESC

        LIMIT 6
        """
    ).fetchall()

    db.close()

    return render_template(
        "index.html",
        videos=videos
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        skills = request.form.get(
            "skills",
            ""
        ).strip()

        bio = request.form.get(
            "bio",
            ""
        ).strip()


        if not name or not email or not password:

            flash(
                "Please fill in all required fields.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        db = get_db()


        existing_user = db.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        if existing_user:

            db.close()

            flash(
                "An account with this email already exists.",
                "error"
            )

            return redirect(
                url_for("register")
            )


        new_user = db.execute(
            """
            INSERT INTO users
                (name, email, password, role, credits, bio, skills)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                email,
                generate_password_hash(password),
                "user",
                3,
                bio,
                skills
            )
        )

        db.execute(
            """
            INSERT INTO credit_transactions (user_id, amount, reason)
            VALUES (?, ?, ?)
            """,
            (new_user.lastrowid, 3, "Welcome bonus")
        )
        

        db.commit()

        db.close()


        flash(
            "Account created successfully. Please login.",
            "success"
        )

        return redirect(
            url_for("login")
        )


    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )


        db = get_db()


        user = db.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()


        db.close()


        if user and check_password_hash(
            user["password"],
            password
        ):

            session.clear()
            session.permanent = True

            session["user_id"] = user["id"]

            session["name"] = user["name"]

            session["role"] = user["role"]

            session["credits"] = user["credits"]

            flash(
                "Login successful!",
                "success"
            )


            if user["role"] == "admin":

                return redirect(
                    url_for("admin")
                )


            return redirect(
                url_for("index")
            )


        flash(
            "Invalid email or password.",
            "error"
        )


    return render_template(
        "login.html"
    )



# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route("/auth/google")
def google_login():
    if not os.environ.get("GOOGLE_CLIENT_ID") or not os.environ.get(
        "GOOGLE_CLIENT_SECRET"
    ):
        return "Google OAuth credentials are missing from .env", 500

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        google_user = token.get("userinfo")

        if not google_user:
            return "Google did not return user information.", 400

        email = (google_user.get("email") or "").strip().lower()
        name = (google_user.get("name") or "").strip()

        if (
            not email
            or google_user.get("email_verified") is not True
        ):
            return "A verified Google email address is required.", 403

        if not name:
            name = email.split("@")[0]

        db = get_db()

        try:
            user = db.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if user is None:
                result = db.execute(
                    """
                    INSERT INTO users
                        (name, email, password, role, bio, skills)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        generate_password_hash(uuid.uuid4().hex),
                        "user",
                        "",
                        ""
                    )
                )

                db.commit()

                user = db.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,)
                ).fetchone()

            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

        finally:
            db.close()

        if user["role"] == "admin":
            return redirect(url_for("admin"))

        return redirect(url_for("index"))

    except Exception:
        app.logger.exception("Google sign-in failed")
        return (
            "Google sign-in failed. Check the server terminal "
            "for details and verify your OAuth configuration.",
            500
        )




# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ============================================================
# EXPLORE / HOME
# ============================================================

@app.route("/home")
def home():

    if not login_required():

        return redirect(
            url_for("login")
        )


    search = request.args.get(
        "q",
        ""
    ).strip()


    db = get_db()


    if search:

        search_value = f"%{search}%"


        videos = db.execute(
            """
            SELECT
                videos.*,
                users.name

            FROM videos

            JOIN users
            ON users.id = videos.user_id

            WHERE
                videos.title LIKE ?
                OR videos.skill LIKE ?
                OR videos.description LIKE ?

            ORDER BY videos.id DESC
            """,

            (
                search_value,
                search_value,
                search_value
            )
        ).fetchall()

    else:

        videos = db.execute(
            """
            SELECT
                videos.*,
                users.name

            FROM videos

            JOIN users
            ON users.id = videos.user_id

            ORDER BY videos.id DESC
            """
        ).fetchall()


    users = db.execute(
        """
        SELECT
            id,
            name,
            skills,
            bio

        FROM users

        WHERE
            role = 'user'

        ORDER BY id DESC
        """
    ).fetchall()


    db.close()


    return render_template(
        "home.html",
        videos=videos,
        users=users,
        q=search
    )


# ============================================================
# UPLOAD VIDEO
# ============================================================

@app.route(
    "/upload",
    methods=["GET", "POST"]
)
def upload():

    if not login_required():

        return redirect(
            url_for("login")
        )


    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        skill = request.form.get(
            "skill",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        video = request.files.get(
            "video"
        )


        if not title:

            flash(
                "Video title is required.",
                "error"
            )

            return redirect(
                url_for("upload")
            )


        if video is None or video.filename == "":

            flash(
                "Please select a video.",
                "error"
            )

            return redirect(
                url_for("upload")
            )


        if "." not in video.filename:

            flash(
                "Invalid video file.",
                "error"
            )

            return redirect(
                url_for("upload")
            )


        extension = video.filename.rsplit(
            ".",
            1
        )[1].lower()


        if extension not in ALLOWED_VIDEO_EXTENSIONS:

            flash(
                "Allowed formats: MP4, WebM, OGG and MOV.",
                "error"
            )

            return redirect(
                url_for("upload")
            )


        filename = (
            uuid.uuid4().hex
            + "."
            + extension
        )


        safe_filename = secure_filename(
            filename
        )


        video_path = os.path.join(
            UPLOAD_FOLDER,
            safe_filename
        )


        video.save(video_path)


        db = get_db()


        db.execute(
            """
            INSERT INTO videos
            (
                user_id,
                title,
                description,
                filename,
                skill
            )

            VALUES (?, ?, ?, ?, ?)
            """,

            (
                session["user_id"],
                title,
                description,
                safe_filename,
                skill
            )
        )


        db.commit()

        db.close()


        flash(
            "Skill video uploaded successfully!",
            "success"
        )


        return redirect(
            url_for("home")
        )


    return render_template(
        "upload.html"
    )


# ============================================================
# VIDEO + COMMENTS
# ============================================================

@app.route(
    "/video/<int:video_id>",
    methods=["GET", "POST"]
)
def video(video_id):

    if not login_required():

        return redirect(
            url_for("login")
        )


    db = get_db()


    video_data = db.execute(
        """
        SELECT
            videos.*,
            users.name,
            users.id AS owner_id

        FROM videos

        JOIN users
        ON users.id = videos.user_id

        WHERE videos.id = ?
        """,

        (video_id,)
    ).fetchone()


    if video_data is None:

        db.close()

        return "Video not found.", 404


    if request.method == "POST":

        comment = request.form.get(
            "comment",
            ""
        ).strip()


        if comment:

            db.execute(
                """
                INSERT INTO comments
                (
                    video_id,
                    user_id,
                    comment
                )

                VALUES (?, ?, ?)
                """,

                (
                    video_id,
                    session["user_id"],
                    comment
                )
            )


            db.commit()


        return redirect(
            url_for(
                "video",
                video_id=video_id
            )
        )


    comments = db.execute(
        """
        SELECT
            comments.*,
            users.name

        FROM comments

        JOIN users
        ON users.id = comments.user_id

        WHERE comments.video_id = ?

        ORDER BY comments.id DESC
        """,

        (video_id,)
    ).fetchall()


    db.close()


    return render_template(
        "video.html",
        video=video_data,
        comments=comments
    )


# ============================================================
# PROFILE
# ============================================================

@app.route(
    "/profile/<int:user_id>"
)
def profile(user_id):

    if not login_required():

        return redirect(
            url_for("login")
        )


    db = get_db()


    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,

        (user_id,)
    ).fetchone()


    if user is None:

        db.close()

        return "User not found.", 404


    videos = db.execute(
        """
        SELECT *
        FROM videos

        WHERE user_id = ?

        ORDER BY id DESC
        """,

        (user_id,)
    ).fetchall()


    db.close()


    return render_template(
        "profile.html",
        user=user,
        videos=videos
    )

@app.route("/lesson/request/<int:teacher_id>", methods=["POST"])
def request_lesson(teacher_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    learner_id = session["user_id"]
    skill = request.form.get("skill", "").strip()

    if teacher_id == learner_id:
        flash("You cannot request a lesson from yourself.", "error")
        return redirect(url_for("home"))

    if not skill:
        flash("Please choose a skill to learn.", "error")
        return redirect(url_for("profile", user_id=teacher_id))

    db = get_db()

    try:
        # Lock the SQLite write transaction so two requests can't spend
        # the same last credit at the same time.
        db.execute("BEGIN IMMEDIATE")

        teacher = db.execute(
            "SELECT id, skills FROM users WHERE id = ? AND role = 'user'",
            (teacher_id,)
        ).fetchone()

        if teacher is None:
            db.rollback()
            flash("Teacher not found.", "error")
            return redirect(url_for("home"))

        offered_skills = {
            item.strip().casefold()
            for item in (teacher["skills"] or "").split(",")
            if item.strip()
        }

        if skill.casefold() not in offered_skills:
            db.rollback()
            flash("That user has not listed this skill.", "error")
            return redirect(url_for("profile", user_id=teacher_id))

        debit = db.execute(
            """
            UPDATE users
            SET credits = credits - 1
            WHERE id = ? AND credits >= 1
            """,
            (learner_id,)
        )

        if debit.rowcount != 1:
            db.rollback()
            flash("You need at least 1 credit to request a lesson.", "error")
            return redirect(url_for("profile", user_id=teacher_id))

        lesson = db.execute(
            """
            INSERT INTO learning_sessions (teacher_id, learner_id, skill)
            VALUES (?, ?, ?)
            """,
            (teacher_id, learner_id, skill)
        )

        db.execute(
            """
            INSERT INTO credit_transactions (user_id, amount, reason)
            VALUES (?, ?, ?)
            """,
            (learner_id, -1, f"Lesson request: {skill}")
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    flash("Lesson requested. 1 credit was reserved.", "success")
    return redirect(url_for("profile", user_id=teacher_id))
# ============================================================
# CHAT
# ============================================================

@app.route(
    "/chat/<int:user_id>",
    methods=["GET", "POST"]
)
def chat(user_id):

    if not login_required():

        return redirect(
            url_for("login")
        )


    if user_id == session["user_id"]:

        flash(
            "You cannot chat with yourself.",
            "error"
        )

        return redirect(
            url_for("home")
        )


    db = get_db()


    other = db.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,

        (user_id,)
    ).fetchone()


    if other is None:

        db.close()

        return "User not found.", 404


    if request.method == "POST":

        message = request.form.get(
            "message",
            ""
        ).strip()


        if message:

            db.execute(
                """
                INSERT INTO messages
                (
                    sender_id,
                    receiver_id,
                    message
                )

                VALUES (?, ?, ?)
                """,

                (
                    session["user_id"],
                    user_id,
                    message
                )
            )


            db.commit()


        return redirect(
            url_for(
                "chat",
                user_id=user_id
            )
        )


    messages = db.execute(
        """
        SELECT
            messages.*,
            users.name

        FROM messages

        JOIN users
        ON users.id = messages.sender_id

        WHERE
        (
            messages.sender_id = ?
            AND messages.receiver_id = ?
        )

        OR

        (
            messages.sender_id = ?
            AND messages.receiver_id = ?
        )

        ORDER BY messages.id ASC
        """,

        (
            session["user_id"],
            user_id,
            user_id,
            session["user_id"]
        )
    ).fetchall()


    db.close()


    return render_template(
        "chat.html",
        other=other,
        messages=messages
    )


# ============================================================
# MEETINGS
# ============================================================

@app.route(
    "/meetings",
    methods=["GET", "POST"]
)
def meetings():

    if not login_required():

        return redirect(
            url_for("login")
        )


    db = get_db()


    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        meeting_url = request.form.get(
            "meeting_url",
            ""
        ).strip()

        scheduled_at = request.form.get(
            "scheduled_at",
            ""
        ).strip()

        guest_id = request.form.get(
            "guest_id",
            ""
        ).strip()


        if not title or not meeting_url or not scheduled_at:

            db.close()

            flash(
                "Please fill in all meeting fields.",
                "error"
            )

            return redirect(
                url_for("meetings")
            )


        if guest_id == "":

            guest_id = None

        else:

            try:

                guest_id = int(guest_id)

            except ValueError:

                guest_id = None


        db.execute(
            """
            INSERT INTO meetings
            (
                host_id,
                guest_id,
                title,
                meeting_url,
                scheduled_at
            )

            VALUES (?, ?, ?, ?, ?)
            """,

            (
                session["user_id"],
                guest_id,
                title,
                meeting_url,
                scheduled_at
            )
        )


        db.commit()


        flash(
            "Meeting created successfully.",
            "success"
        )


        return redirect(
            url_for("meetings")
        )


    meetings_list = db.execute(
        """
        SELECT
            meetings.*,
            host.name AS host_name,
            guest.name AS guest_name

        FROM meetings

        JOIN users AS host
        ON host.id = meetings.host_id

        LEFT JOIN users AS guest
        ON guest.id = meetings.guest_id

        WHERE
            meetings.host_id = ?
            OR meetings.guest_id = ?

        ORDER BY meetings.scheduled_at ASC
        """,

        (
            session["user_id"],
            session["user_id"]
        )
    ).fetchall()


    users = db.execute(
        """
        SELECT
            id,
            name

        FROM users

        WHERE
            id != ?
            AND role = 'user'

        ORDER BY name ASC
        """,

        (session["user_id"],)
    ).fetchall()


    db.close()


    return render_template(
        "meetings.html",
        meetings=meetings_list,
        users=users
    )


# ============================================================
# ADMIN PANEL
# ============================================================

@app.route("/admin")
def admin():

    if not admin_required():

        return "Access denied.", 403


    db = get_db()


    users = db.execute(
        """
        SELECT
            id,
            name,
            email,
            role,
            skills,
            created_at

        FROM users

        ORDER BY id DESC
        """
    ).fetchall()


    videos = db.execute(
        """
        SELECT
            videos.*,
            users.name

        FROM videos

        JOIN users
        ON users.id = videos.user_id

        ORDER BY videos.id DESC
        """
    ).fetchall()


    comments = db.execute(
        """
        SELECT
            comments.*,
            users.name AS user_name,
            videos.title

        FROM comments

        JOIN users
        ON users.id = comments.user_id

        JOIN videos
        ON videos.id = comments.video_id

        ORDER BY comments.id DESC

        LIMIT 100
        """
    ).fetchall()


    stats = {}


    stats["users"] = db.execute(
        """
        SELECT COUNT(*)
        FROM users

        WHERE role = 'user'
        """
    ).fetchone()[0]


    stats["videos"] = db.execute(
        """
        SELECT COUNT(*)
        FROM videos
        """
    ).fetchone()[0]


    stats["comments"] = db.execute(
        """
        SELECT COUNT(*)
        FROM comments
        """
    ).fetchone()[0]


    stats["messages"] = db.execute(
        """
        SELECT COUNT(*)
        FROM messages
        """
    ).fetchone()[0]


    db.close()


    return render_template(
        "admin.html",
        users=users,
        videos=videos,
        comments=comments,
        stats=stats
    )


# ============================================================
# ADMIN DELETE USER
# ============================================================

@app.route(
    "/admin/user/<int:user_id>/delete",
    methods=["POST"]
)
def admin_delete_user(user_id):

    if not admin_required():

        return "Access denied.", 403


    if user_id == session["user_id"]:

        flash(
            "You cannot delete your own admin account.",
            "error"
        )

        return redirect(
            url_for("admin")
        )


    db = get_db()


    user = db.execute(
        """
        SELECT role
        FROM users
        WHERE id = ?
        """,

        (user_id,)
    ).fetchone()


    if user is None:

        db.close()

        flash(
            "User not found.",
            "error"
        )

        return redirect(
            url_for("admin")
        )


    if user["role"] == "admin":

        db.close()

        flash(
            "Admin accounts cannot be deleted here.",
            "error"
        )

        return redirect(
            url_for("admin")
        )


    # Get user's video files before deleting records

    videos = db.execute(
        """
        SELECT filename
        FROM videos
        WHERE user_id = ?
        """,

        (user_id,)
    ).fetchall()


    for video in videos:

        filename = video["filename"]

        filepath = os.path.join(
            UPLOAD_FOLDER,
            filename
        )


        if os.path.exists(filepath):

            try:

                os.remove(filepath)

            except OSError:

                pass


    # Delete user.
    # Foreign key CASCADE handles related records.

    db.execute(
        """
        DELETE FROM users
        WHERE id = ?
        """,

        (user_id,)
    )


    db.commit()

    db.close()


    flash(
        "User deleted successfully.",
        "success"
    )


    return redirect(
        url_for("admin")
    )


# ============================================================
# ADMIN DELETE VIDEO
# ============================================================

@app.route(
    "/admin/video/<int:video_id>/delete",
    methods=["POST"]
)
def admin_delete_video(video_id):

    if not admin_required():

        return "Access denied.", 403


    db = get_db()


    video = db.execute(
        """
        SELECT filename
        FROM videos
        WHERE id = ?
        """,

        (video_id,)
    ).fetchone()


    if video is None:

        db.close()

        flash(
            "Video not found.",
            "error"
        )

        return redirect(
            url_for("admin")
        )


    filepath = os.path.join(
        UPLOAD_FOLDER,
        video["filename"]
    )


    if os.path.exists(filepath):

        try:

            os.remove(filepath)

        except OSError:

            pass


    db.execute(
        """
        DELETE FROM videos
        WHERE id = ?
        """,

        (video_id,)
    )


    db.commit()

    db.close()


    flash(
        "Video deleted successfully.",
        "success"
    )


    return redirect(
        url_for("admin")
    )


# ============================================================
# ADMIN DELETE COMMENT
# ============================================================

@app.route(
    "/admin/comment/<int:comment_id>/delete",
    methods=["POST"]
)
def admin_delete_comment(comment_id):

    if not admin_required():

        return "Access denied.", 403


    db = get_db()


    db.execute(
        """
        DELETE FROM comments
        WHERE id = ?
        """,

        (comment_id,)
    )


    db.commit()

    db.close()


    flash(
        "Comment deleted successfully.",
        "success"
    )


    return redirect(
        url_for("admin")
    )


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def file_too_large(error):

    flash(
        "The video is too large. Maximum size is 300 MB.",
        "error"
    )

    return redirect(
        url_for("upload")
    )


@app.errorhandler(404)
def page_not_found(error):

    return """
    <h1>404 - Page Not Found</h1>
    <p>The page you requested does not exist.</p>
    <a href="/">Go Home</a>
    """, 404


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    init_database()

    print("")
    print("======================================")
    print("       SKILL SWAP WEBSITE")
    print("======================================")
    print("Website: http://127.0.0.1:5000")
    print("Admin:   admin@skillswap.com")
    print("Password: admin123")
    print("======================================")
    print("")


    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )