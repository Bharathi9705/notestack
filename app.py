"""
NoteStack – app.py  (v4 — persistent Postgres storage)
─────────────────────────────────────────────────────────────────────────────
WHY THIS CHANGED FROM SQLITE:
Render's free web service plan uses an EPHEMERAL filesystem. Every time the
app goes idle (~15 min of no traffic) it spins down, and the next request
spins up a brand-new container with a clean disk. The old SQLite file
(notestack.db) lived on that disk, so all notes were wiped on every cold
restart — this is a hosting limitation, not a code bug.

FIX: notes are now stored in Postgres (e.g. a free Supabase project), which
lives outside the web service entirely and survives restarts/redeploys.

Set the DATABASE_URL environment variable (on Render: Settings → Environment)
to your Postgres connection string, e.g.:
  postgresql://postgres:[PASSWORD]@db.xxxxx.supabase.co:5432/postgres
"""

import os
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, Blueprint, g, request, jsonify, current_app, send_from_directory
from flask_cors import CORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("notestack")


class Config:
    DATABASE_URL = os.environ.get("DATABASE_URL")
    SSLMODE      = os.environ.get("DB_SSLMODE", "require")  # "disable" for local Postgres
    PAGE_SIZE    = 20
    MAX_TITLE    = 120
    MAX_BODY     = 10_000
    DEBUG        = os.getenv("FLASK_DEBUG", "false").lower() == "true"


# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        if not current_app.config["DATABASE_URL"]:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it as an environment variable "
                "pointing to your Postgres connection string."
            )
        g.db = psycopg2.connect(
            current_app.config["DATABASE_URL"],
            sslmode=current_app.config["SSLMODE"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return g.db

def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db(app):
    with app.app_context():
        if not app.config["DATABASE_URL"]:
            log.warning("DATABASE_URL not set — skipping DB init. Set it before using the app.")
            return
        db  = get_db()
        cur = db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id         SERIAL PRIMARY KEY,
                title      TEXT    NOT NULL CHECK (length(title)   <= 120),
                content    TEXT    NOT NULL CHECK (length(content) <= 10000),
                pinned     BOOLEAN NOT NULL DEFAULT FALSE,
                color      TEXT    NOT NULL DEFAULT '#8B5CF6',
                created_at TEXT    NOT NULL,
                updated_at TEXT    NOT NULL
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_pinned_id ON notes (pinned DESC, id DESC);")
        db.commit()
        cur.close()
        close_db()
        log.info("Postgres schema ready.")


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

COLORS = {"#8B5CF6","#F43F5E","#10B981","#F59E0B","#38BDF8","#EC4899"}

def validate(data):
    errors = {}
    title   = str(data.get("title",   "") or "").strip()
    content = str(data.get("content", "") or "").strip()
    color   = str(data.get("color",   "#8B5CF6")).strip()
    pinned  = bool(data.get("pinned", False))
    if not title:               errors["title"]   = "Title is required."
    elif len(title) > 120:      errors["title"]   = "Title must be ≤ 120 characters."
    if not content:             errors["content"] = "Content is required."
    elif len(content) > 10000:  errors["content"] = "Content must be ≤ 10 000 characters."
    if color not in COLORS: color = "#8B5CF6"
    if errors: raise ValueError(errors)
    return {"title": title, "content": content, "color": color, "pinned": pinned}


# ── Blueprint ─────────────────────────────────────────────────────────────────
bp = Blueprint("notes", __name__, url_prefix="/notes")

@bp.get("/")
def list_notes():
    db  = get_db()
    cur = db.cursor()
    q           = (request.args.get("q") or "").strip()
    page        = max(1, request.args.get("page", 1, type=int) or 1)
    per_page    = min(100, max(1, request.args.get("per_page", Config.PAGE_SIZE, type=int) or Config.PAGE_SIZE))
    offset      = (page - 1) * per_page
    pinned_only = request.args.get("pinned","").lower() in ("1","true","yes")

    conds  = []
    params = {"q": f"%{q}%", "limit": per_page, "offset": offset}
    if q:           conds.append("(title ILIKE %(q)s OR content ILIKE %(q)s)")
    if pinned_only: conds.append("pinned = TRUE")
    where = f"WHERE {' AND '.join(conds)}" if conds else ""

    cur.execute(f"SELECT COUNT(*) AS c FROM notes {where}", params)
    total = cur.fetchone()["c"]

    cur.execute(
        f"SELECT * FROM notes {where} ORDER BY pinned DESC, id DESC LIMIT %(limit)s OFFSET %(offset)s",
        params,
    )
    rows = cur.fetchall()
    cur.close()
    return ok([note_dict(r) for r in rows], total=total, page=page, per_page=per_page,
              pages=max(1, (total + per_page - 1) // per_page))

@bp.get("/counts")
def counts():
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM notes")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM notes WHERE pinned = TRUE")
    pinned = cur.fetchone()["c"]
    cur.close()
    return ok({"all": total, "pinned": pinned})

@bp.get("/<int:nid>")
def get_note(nid):
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM notes WHERE id = %s", (nid,))
    row = cur.fetchone()
    cur.close()
    return ok(note_dict(row)) if row else err(f"Note #{nid} not found.", 404)

@bp.post("/")
def create_note():
    data = request.get_json(silent=True)
    if not data: return err("Request body must be JSON.", 415)
    try:    payload = validate(data)
    except ValueError as e: return err("Validation failed.", 422, fields=e.args[0])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db  = get_db()
    cur = db.cursor()
    cur.execute(
        """INSERT INTO notes (title, content, color, pinned, created_at, updated_at)
           VALUES (%(title)s, %(content)s, %(color)s, %(pinned)s, %(now)s, %(now)s)
           RETURNING *""",
        {**payload, "now": now},
    )
    row = cur.fetchone()
    db.commit()
    cur.close()
    log.info("Created note #%s '%s'", row["id"], row["title"])
    return ok(note_dict(row), 201)

@bp.put("/<int:nid>")
def update_note(nid):
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM notes WHERE id = %s", (nid,))
    if not cur.fetchone():
        cur.close()
        return err(f"Note #{nid} not found.", 404)

    data = request.get_json(silent=True)
    if not data: return err("Request body must be JSON.", 415)
    try:    payload = validate(data)
    except ValueError as e: return err("Validation failed.", 422, fields=e.args[0])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute(
        """UPDATE notes SET title=%(title)s, content=%(content)s, color=%(color)s,
           pinned=%(pinned)s, updated_at=%(now)s WHERE id=%(id)s RETURNING *""",
        {**payload, "now": now, "id": nid},
    )
    row = cur.fetchone()
    db.commit()
    cur.close()
    return ok(note_dict(row))

@bp.patch("/<int:nid>/pin")
def toggle_pin(nid):
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT pinned FROM notes WHERE id = %s", (nid,))
    row = cur.fetchone()
    if not row:
        cur.close()
        return err(f"Note #{nid} not found.", 404)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute(
        "UPDATE notes SET pinned = %s, updated_at = %s WHERE id = %s RETURNING *",
        (not row["pinned"], now, nid),
    )
    updated = cur.fetchone()
    db.commit()
    cur.close()
    return ok(note_dict(updated))

@bp.delete("/<int:nid>")
def delete_note(nid):
    db  = get_db()
    cur = db.cursor()
    cur.execute("SELECT id FROM notes WHERE id = %s", (nid,))
    if not cur.fetchone():
        cur.close()
        return err(f"Note #{nid} not found.", 404)
    cur.execute("DELETE FROM notes WHERE id = %s", (nid,))
    db.commit()
    cur.close()
    log.info("Deleted note #%s", nid)
    return ok({"id": nid, "deleted": True})


# ── App factory ───────────────────────────────────────────────────────────────
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/notes*": {"origins": "*"}})
    app.teardown_appcontext(close_db)
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(_): return err("Route not found.", 404)
    @app.errorhandler(405)
    def not_allowed(_): return err("Method not allowed.", 405)
    @app.errorhandler(500)
    def internal(_): return err("Internal server error.", 500)

    @app.get("/")
    def index():
        return send_from_directory(app.root_path, "index.html")

    @app.get("/health")
    def health():
        return ok({"status": "ok", "version": "4.0.0", "db_configured": bool(app.config["DATABASE_URL"])})

    init_db(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=Config.DEBUG, port=int(os.environ.get("PORT", 5000)), use_reloader=False)