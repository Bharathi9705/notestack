"""
NoteStack — app.py (v3.3 — Complete Routing Resolution)
All CSS and JS are inline inside index.html, so Flask only needs
to serve one file. No more missing style.css / script.js 404 errors.
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from flask import Flask, Blueprint, g, request, jsonify, current_app, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("notestack")


class Config:
    BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
    DB_PATH   = os.path.join(BASE_DIR, "notestack.db")
    PAGE_SIZE = 20
    MAX_TITLE = 120
    MAX_BODY  = 10_000
    DEBUG     = os.getenv("FLASK_DEBUG", "false").lower() == "true"


# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL;")
        g.db.execute("PRAGMA foreign_keys=ON;")
    return g.db

def close_db(exc=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL CHECK(length(title)   <= 120),
                content    TEXT    NOT NULL CHECK(length(content) <= 10000),
                pinned     INTEGER NOT NULL DEFAULT 0,
                color      TEXT    NOT NULL DEFAULT '#7C5CFC',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_pinned_id ON notes (pinned DESC, id DESC);
        """)
        db.commit()
        log.info("DB ready → %s", app.config["DB_PATH"])


# ── Helpers ───────────────────────────────────────────────────────────────────
def ok(data, status=200, **meta):
    body = {"ok": True, "data": data}
    if meta: body["meta"] = meta
    return jsonify(body), status

def err(msg, status=400, **extra):
    body = {"ok": False, "error": msg}
    body.update(extra)
    return jsonify(body), status

def note_dict(row):
    d = dict(row)
    d["pinned"] = bool(d["pinned"])
    return d

COLORS = {"#7C5CFC", "#F04438", "#12B76A", "#F79009", "#0EA5E9", "#EC4899", "#8B5CF6", "#F43F5E", "#10B981", "#F59E0B", "#38BDF8"}

def validate(data):
    errors = {}
    title   = str(data.get("title",   "") or "").strip()
    content = str(data.get("content", "") or "").strip()
    color   = str(data.get("color",   "#7C5CFC")).strip()
    pinned  = bool(data.get("pinned", False))
    if not title:               errors["title"]   = "Title is required."
    elif len(title) > 120:      errors["title"]   = "Title must be ≤ 120 characters."
    if not content:             errors["content"] = "Content is required."
    elif len(content) > 10000:  errors["content"] = "Content must be ≤ 10 000 characters."
    if color not in COLORS: color = "#7C5CFC"
    if errors: raise ValueError(errors)
    return {"title": title, "content": content, "color": color, "pinned": int(pinned)}


# ── Notes Blueprint ───────────────────────────────────────────────────────────
bp = Blueprint("notes", __name__, url_prefix="/notes")

@bp.get("/")
def list_notes():
    db = get_db()
    q           = (request.args.get("q") or "").strip()
    page        = max(1, request.args.get("page", 1, type=int) or 1)
    per_page    = min(100, max(1, request.args.get("per_page", Config.PAGE_SIZE, type=int) or Config.PAGE_SIZE))
    offset      = (page - 1) * per_page
    pinned_only = request.args.get("pinned","").lower() in ("1","true","yes")

    conds = []
    if q:           conds.append("(title LIKE :q OR content LIKE :q)")
    if pinned_only: conds.append("pinned = 1")
    where  = f"WHERE {' AND '.join(conds)}" if conds else ""
    params = {"q": f"%{q}%", "limit": per_page, "offset": offset}

    total = db.execute(f"SELECT COUNT(*) FROM notes {where}", params).fetchone()[0]
    rows  = db.execute(f"SELECT * FROM notes {where} ORDER BY pinned DESC, id DESC LIMIT :limit OFFSET :offset", params).fetchall()
    return ok([note_dict(r) for r in rows], total=total, page=page, per_page=per_page, pages=max(1,(total+per_page-1)//per_page))

@bp.get("/counts")
def counts():
    db = get_db()
    return ok({"all": db.execute("SELECT COUNT(*) FROM notes").fetchone()[0],
               "pinned": db.execute("SELECT COUNT(*) FROM notes WHERE pinned=1").fetchone()[0]})

@bp.get("/<int:nid>")
def get_note(nid):
    row = get_db().execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()
    return ok(note_dict(row)) if row else err(f"Note #{nid} not found.", 404)

@bp.post("/")
def create_note():
    data = request.get_json(silent=True)
    if not data: return err("Request body must be JSON.", 415)
    try:    payload = validate(data)
    except ValueError as e: return err("Validation failed.", 422, fields=e.args[0])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db  = get_db()
    cur = db.execute("INSERT INTO notes (title,content,color,pinned,created_at,updated_at) VALUES (:title,:content,:color,:pinned,:now,:now)", {**payload,"now":now})
    db.commit()
    row = db.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
    log.info("Created note #%d '%s'", row["id"], row["title"])
    return ok(note_dict(row), 201)

@bp.put("/<int:nid>")
def update_note(nid):
    db  = get_db()
    if not db.execute("SELECT id FROM notes WHERE id=?", (nid,)).fetchone():
        return err(f"Note #{nid} not found.", 404)
    data = request.get_json(silent=True)
    if not data: return err("Request body must be JSON.", 415)
    try:    payload = validate(data)
    except ValueError as e: return err("Validation failed.", 422, fields=e.args[0])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute("UPDATE notes SET title=:title,content=:content,color=:color,pinned=:pinned,updated_at=:now WHERE id=:id", {**payload,"now":now,"id":nid})
    db.commit()
    return ok(note_dict(db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()))

@bp.patch("/<int:nid>/pin")
def toggle_pin(nid):
    db  = get_db()
    row = db.execute("SELECT pinned FROM notes WHERE id=?", (nid,)).fetchone()
    if not row: return err(f"Note #{nid} not found.", 404)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute("UPDATE notes SET pinned=?,updated_at=? WHERE id=?", (0 if row["pinned"] else 1, now, nid))
    db.commit()
    return ok(note_dict(db.execute("SELECT * FROM notes WHERE id=?", (nid,)).fetchone()))

@bp.delete("/<int:nid>")
def delete_note(nid):
    db  = get_db()
    if not db.execute("SELECT id FROM notes WHERE id=?", (nid,)).fetchone():
        return err(f"Note #{nid} not found.", 404)
    db.execute("DELETE FROM notes WHERE id=?", (nid,))
    db.commit()
    log.info("Deleted note #%d", nid)
    return ok({"id": nid, "deleted": True})


# ── Account Blueprint (FIXED) ─────────────────────────────────────────────────
account_state = {
    "name": "Admin User",
    "email": "admin@notestack.io"
}

account_bp = Blueprint("account", __name__, url_prefix="/account")

@account_bp.route("/profile", methods=["GET", "POST"])
@account_bp.route("/profile/", methods=["GET", "POST"])
def manage_profile():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        new_name = data.get("name", "").strip()
        if not new_name:
            return jsonify({"ok": False, "error": "Name cannot be empty."}), 400
        account_state["name"] = new_name
        log.info("Profile name updated to: %s", new_name)
    return jsonify({"ok": True, "data": account_state})

@account_bp.route("/signout", methods=["GET"])
@account_bp.route("/signout/", methods=["GET"])
def handle_signout():
    log.info("Account profile session terminated.")
    return """
    <html>
        <body style="background:#050816; color:#F1F5F9; font-family:sans-serif; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh;">
            <div style="text-align:center; max-width:400px; padding:2rem; background:#080D1A; border:1px solid rgba(255,255,255,0.06); border-radius:12px;">
                <h2 style="margin-bottom:0.5rem; font-weight:800;">Signed Out Securely</h2>
                <p style="color:#94A3B8; margin-bottom:1.5rem; font-size:0.9rem;">You have safely exited the NoteStack workspace session.</p>
                <a href="/" style="display:inline-block; background:linear-gradient(135deg,#6366F1,#8B5CF6); color:#fff; text-decoration:none; padding:0.6rem 1.2rem; font-size:0.85rem; font-weight:600; border-radius:6px;">Return to App Workspace</a>
            </div>
        </body>
    </html>
    """


# ── App Factory ───────────────────────────────────────────────────────────────
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/*": {"origins": "*"}})
    app.teardown_appcontext(close_db)
    app.register_blueprint(bp)
    app.register_blueprint(account_bp)

    @app.errorhandler(404)
    def not_found(_): return err("Route not found.", 404)
    @app.errorhandler(405)
    def not_allowed(_): return err("Method not allowed.", 405)
    @app.errorhandler(500)
    def internal(_): return err("Internal server error.", 500)

    @app.get("/")
    def index():
        return send_from_directory(app.root_path, "index.html")

    init_db(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=5000, use_reloader=False)