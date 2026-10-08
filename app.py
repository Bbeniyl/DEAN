import os
import html
import sqlite3
import secrets
import time
import threading
import requests
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from urllib.parse import urlencode, quote_plus, quote

from flask import (
    Flask, request, session, redirect, url_for,
    jsonify, render_template_string, abort, Response
)
from openai import OpenAI
from steel_client import configured as steel_configured, create_session as steel_create_session, validate_key as steel_validate_key, active_session_status
from persistent_browser import ensure_started as ensure_persistent_browser, status as persistent_browser_status, latest_frame as persistent_browser_frame, navigate as persistent_browser_navigate, evaluate_js as persistent_browser_eval, click as persistent_browser_click, click_text as persistent_browser_click_text, scroll_by as persistent_browser_scroll, type_text as persistent_browser_type, press_key as persistent_browser_key, start_keepalive as start_browser_keepalive, wait_until_ready as browser_wait_until_ready

app = Flask(__name__)
# browser reconnect build marker

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DEAN_PASSWORD = os.getenv("DEAN_PASSWORD", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip()
DB_PATH = os.getenv("DB_PATH", "/tmp/dean.sqlite3").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_tinyfish_raw = os.getenv("TINYFISH_API_KEY", "")
_tinyfish_match = re.search(r"sk-tinyfish-[A-Za-z0-9._-]+", _tinyfish_raw)
TINYFISH_API_KEY = _tinyfish_match.group(0) if _tinyfish_match else _tinyfish_raw.strip()
TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "https://dean-agent-5y18.onrender.com/tiktok/callback").strip()
TIKTOK_SCOPES = os.getenv("TIKTOK_SCOPES", "user.info.basic").strip()
DEAN_VERSION = os.getenv("RENDER_GIT_COMMIT", "dev").strip()[:12]

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing")
if len(DEAN_PASSWORD) < 12:
    raise RuntimeError("DEAN_PASSWORD must contain at least 12 characters")
if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must contain at least 32 characters")

app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
    MAX_CONTENT_LENGTH=64000,
)

client = OpenAI(api_key=OPENAI_API_KEY)
_last_search_results = []
_last_search_query = ""
_last_search_lock = threading.Lock()

# Start DEAN's long-lived self-hosted Chromium connection in the background.
ensure_persistent_browser()
start_browser_keepalive()

# Safe browser-session diagnostic for deployment verification.
def _browser_session_diag_later():
    time.sleep(12)
    try:
        st = active_session_status()
        print("BROWSER_SESSION_DIAG", st, flush=True)
    except Exception as exc:
        print("BROWSER_SESSION_DIAG", {"ok": False, "error": type(exc).__name__}, flush=True)
threading.Thread(target=_browser_session_diag_later, daemon=True, name="browser-session-diag").start()

def _persistent_browser_diag_later():
    try:
        ready = browser_wait_until_ready(70)
        st = persistent_browser_status()
        eval_ok = (persistent_browser_eval("1+1") == 2) if ready else False
        print("PERSISTENT_BROWSER_DIAG", {
            "connected": bool(st.get("connected")),
            "viewer_ready": bool(st.get("viewer_ready")),
            "started": bool(st.get("started")),
            "last_error": str(st.get("last_error") or "")[:160],
            "target_id_present": bool(st.get("target_id")),
            "cdp_action_test": bool(eval_ok),
        }, flush=True)
    except Exception as exc:
        print("PERSISTENT_BROWSER_DIAG", {"error": type(exc).__name__, "message": str(exc)[:160]}, flush=True)
threading.Thread(target=_persistent_browser_diag_later, daemon=True, name="persistent-browser-diag").start()

def _speech_diag_later():
    time.sleep(10)
    try:
        sample = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="cedar",
            input="בדיקה",
        )
        size = len(getattr(sample, "content", b"") or b"")
        print("SPEECH_DIAG", {"ok": bool(size), "bytes": size}, flush=True)
    except Exception as exc:
        print("SPEECH_DIAG", {"ok": False, "error": type(exc).__name__, "message": str(exc)[:160]}, flush=True)
threading.Thread(target=_speech_diag_later, daemon=True, name="speech-diag").start()

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get_db():
    """Use persistent Postgres when DATABASE_URL is configured; otherwise SQLite."""
    if DATABASE_URL:
        import psycopg
        return psycopg.connect(DATABASE_URL, autocommit=False, row_factory=psycopg.rows.dict_row)

    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_db():
    with get_db() as con:
        if DATABASE_URL:
            con.execute("""CREATE TABLE IF NOT EXISTS messages(
                id BIGSERIAL PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS memories(
                id BIGSERIAL PRIMARY KEY, content TEXT NOT NULL UNIQUE, created TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS tasks(
                id BIGSERIAL PRIMARY KEY, content TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS reminders(
                id BIGSERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                due_at TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                notified INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS login_attempts(
                id BIGSERIAL PRIMARY KEY, ip TEXT NOT NULL, ok INTEGER NOT NULL, created DOUBLE PRECISION NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS action_requests(
                id BIGSERIAL PRIMARY KEY, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS releases(
                id BIGSERIAL PRIMARY KEY, version TEXT NOT NULL UNIQUE, notes TEXT NOT NULL, created TEXT NOT NULL)""")
        else:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memories(
                id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL UNIQUE, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                due_at TEXT,
                done INTEGER NOT NULL DEFAULT 0,
                notified INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS login_attempts(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, ok INTEGER NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS action_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS releases(
                id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL UNIQUE, notes TEXT NOT NULL, created TEXT NOT NULL);
            """)
        con.commit()

init_db()

CURRENT_RELEASE_NOTES = """שכבת הבנת כוונה: DEAN מקשר בין מילים, ההקשר האחרון, האתר הפתוח והקישור האחרון; פותר ניסוחים כמו 'האתר הזה' ו'אותו אתר'; ושואל שאלה קצרה רק כשבאמת חסר יעד."""
def register_release():
    try:
        with get_db() as con:
            if DATABASE_URL:
                con.execute("INSERT INTO releases(version,notes,created) VALUES(%s,%s,%s) ON CONFLICT(version) DO NOTHING",(DEAN_VERSION,CURRENT_RELEASE_NOTES,utc_now()))
            else:
                con.execute("INSERT OR IGNORE INTO releases(version,notes,created) VALUES(?,?,?)",(DEAN_VERSION,CURRENT_RELEASE_NOTES,utc_now()))
    except Exception:
        app.logger.exception("Release registration failed")
register_release()

def latest_release():
    with get_db() as con:
        row=con.execute("SELECT version,notes,created FROM releases ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else {"version":DEAN_VERSION,"notes":CURRENT_RELEASE_NOTES,"created":utc_now()}

def is_logged_in():
    return session.get("authenticated") is True

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]

def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            if request.path.startswith("/api/"):
                return jsonify(error="login_required"), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def require_csrf(fn):
    @wraps(fn)
    @require_login
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf", "")
        if not supplied or not secrets.compare_digest(supplied, csrf_token()):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

def db_sql(q):
    return q.replace("?", "%s") if DATABASE_URL else q

def save_message(role, content):
    with get_db() as con:
        con.execute(
            db_sql("INSERT INTO messages(role,content,created) VALUES(?,?,?)"),
            (role, content[:16000], utc_now())
        )

def load_history(limit=40):
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?"),
            (limit,)
        ).fetchall()[::-1]
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def load_relevant_history(message, recent_limit=16, scan_limit=500, max_extra=18):
    """Return recent chat plus older messages that share meaningful words with the current message."""
    recent = load_history(recent_limit)
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT role,content FROM messages ORDER BY id DESC LIMIT ?"),
            (scan_limit,)
        ).fetchall()[::-1]
    words = {
        w.strip(".,!?;:()[]{}\"'־-").lower()
        for w in str(message).split()
        if len(w.strip(".,!?;:()[]{}\"'־-")) >= 3
    }
    stop = {
        "אני","אתה","הוא","היא","זה","זאת","שלי","שלך","שלו","שלה","עם","אבל","עוד",
        "עכשיו","כבר","כמו","מה","איך","למה","כן","לא","פה","שם","אותו","אותה","אותי",
        "צריך","רוצה","יכול","יכולה","תעשה","תעשי","תגיד","תקשיב","תקשיבי","שאני","שאתה"
    }
    words -= stop
    if not words:
        return recent
    scored = []
    for idx, r in enumerate(rows[:-recent_limit] if len(rows) > recent_limit else []):
        txt = r["content"].lower()
        score = sum(1 for w in words if w in txt)
        if score:
            scored.append((score, idx, {"role": r["role"], "content": r["content"]}))
    extras = [x[2] for x in sorted(scored, key=lambda x: (x[0], x[1]), reverse=True)[:max_extra]]
    extras.reverse()
    return extras + recent

def list_memories(limit=100):
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT id,content,created FROM memories ORDER BY id DESC LIMIT ?"),
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

def relevant_memories(message, limit=24):
    memories = list_memories(300)
    words = {w.strip(".,!?;:()[]{}\\\"'־-").lower() for w in str(message).split() if len(w.strip(".,!?;:()[]{}\\\"'־-")) >= 3}
    if not words:
        return memories[:limit]
    scored = []
    for i, m in enumerate(memories):
        txt = m["content"].lower()
        score = sum(1 for w in words if w in txt)
        if score:
            scored.append((score, -i, m))
    picked = [x[2] for x in sorted(scored, reverse=True)[:limit]]
    if len(picked) < 8:
        seen = {m["id"] for m in picked}
        picked += [m for m in memories if m["id"] not in seen][:8-len(picked)]
    return picked

def auto_learn_from_turn(user_text, assistant_text):
    """Extract durable, useful personal context automatically. Never store secrets."""
    try:
        existing = "\\n".join(f"- {m['content']}" for m in list_memories(180))
        recent_context = load_history(18)
        context_text = "\\n".join(
            ("בניאל: " if m["role"] == "user" else "DEAN: ") + m["content"][:1800]
            for m in recent_context
        )
        prompt = f"""חלץ מהשיחה ומההקשר האחרון רק עובדות יציבות ושימושיות על בניאל שכדאי לזכור לשיחות עתידיות:
העדפות, מטרות, קשרים משפחתיים, שגרה, פרויקטים, החלטות קבועות ודפוסים חשובים.
אל תשמור סיסמאות, מפתחות, מספרי כרטיס, קודים, פרטי התחברות, מידע רגעי או ניחושים.
אל תשמור מידע רגיש מאוד אלא אם בניאל ביקש במפורש לזכור אותו.
אל תחזור על עובדה שכבר קיימת.
החזר שורה אחת לכל זיכרון חדש, בלי מספור ובלי הסבר. אם אין מה לשמור החזר NONE.

זיכרונות קיימים:
{existing}

הקשר אחרון:
{context_text}

התור האחרון:
בניאל: {user_text}
DEAN: {assistant_text}

שים לב במיוחד לתיקונים של בניאל, משמעות של כינויים/קיצורים, שמות מדויקים, החלטות שהתקבלו, העדפות שחוזרות, ומה הובהר כטעות שלא לחזור עליה."""
        r = client.responses.create(
            model=MODEL,
            input=prompt,
            reasoning={"effort":"low"},
            max_output_tokens=350,
        )
        out = (r.output_text or "").strip()
        if not out or out.upper() == "NONE":
            return
        for line in out.splitlines():
            clean = line.strip().lstrip("-•0123456789. ").strip()
            if clean and clean.upper() != "NONE" and len(clean) <= 500:
                save_memory(clean)
    except Exception:
        app.logger.exception("Automatic memory extraction failed")

def save_memory(content):
    clean = " ".join(str(content).strip().split())
    if not clean:
        return False
    with get_db() as con:
        con.execute(
            ("INSERT INTO memories(content,created) VALUES(%s,%s) ON CONFLICT(content) DO NOTHING" if DATABASE_URL else "INSERT OR IGNORE INTO memories(content,created) VALUES(?,?)"),
            (clean[:2000], utc_now())
        )
    return True

def add_task(content):
    clean = " ".join(str(content).strip().split())
    if not clean:
        return False
    with get_db() as con:
        con.execute(
            db_sql("INSERT INTO tasks(content,created) VALUES(?,?)"),
            (clean[:1000], utc_now())
        )
    return True

def _israel_now():
    return datetime.now(ZoneInfo("Asia/Jerusalem"))

def _to_utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

def parse_reminder_request(raw_text):
    """Parse common Hebrew reminder phrasing. Returns (content, due_at_iso_or_none)."""
    text = " ".join(str(raw_text or "").split()).strip()
    if not text:
        return "", None
    now = _israel_now()
    due = None

    # בעוד X דקות/שעות
    m = re.search(r"בעוד\s+(\d+)\s*(דקות?|שעות?)", text)
    if m:
        amount = int(m.group(1))
        due = now + (timedelta(minutes=amount) if "דק" in m.group(2) else timedelta(hours=amount))
        text = (text[:m.start()] + text[m.end():]).strip(" ,-")

    # היום/מחר בשעה HH[:MM]
    if due is None:
        m = re.search(r"(היום|מחר)(?:\s+(?:ב|בשעה|ב-))?\s*(\d{1,2})(?::(\d{2}))?", text)
        if m:
            day_add = 1 if m.group(1) == "מחר" else 0
            hh = max(0, min(23, int(m.group(2))))
            mm = max(0, min(59, int(m.group(3) or 0)))
            due = (now + timedelta(days=day_add)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if day_add == 0 and due <= now:
                due += timedelta(days=1)
            text = (text[:m.start()] + text[m.end():]).strip(" ,-")

    # בשעה HH:MM / ב-HH:MM
    if due is None:
        m = re.search(r"(?:בשעה|ב-)\s*(\d{1,2}):(\d{2})", text)
        if m:
            hh = max(0, min(23, int(m.group(1))))
            mm = max(0, min(59, int(m.group(2))))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
            text = (text[:m.start()] + text[m.end():]).strip(" ,-")

    text = re.sub(r"^(?:תזכיר\s+לי|תזכור\s+להזכיר\s+לי)\s*", "", text).strip()
    return text, (_to_utc_iso(due) if due else None)

def add_reminder(content, due_at=None):
    clean = " ".join(str(content or "").split()).strip()
    if not clean:
        return None
    with get_db() as con:
        row = con.execute(
            db_sql("INSERT INTO reminders(content,due_at,done,notified,created) VALUES(?,?,0,0,?) RETURNING id"),
            (clean[:1200], due_at, utc_now())
        ).fetchone()
    return int(row["id"]) if row else None

def list_reminders(limit=100, include_done=False):
    with get_db() as con:
        if include_done:
            rows = con.execute(db_sql("SELECT id,content,due_at,done,notified,created FROM reminders ORDER BY done ASC, id DESC LIMIT ?"), (limit,)).fetchall()
        else:
            rows = con.execute(db_sql("SELECT id,content,due_at,done,notified,created FROM reminders WHERE done=0 ORDER BY id DESC LIMIT ?"), (limit,)).fetchall()
    return [dict(r) for r in rows]

def complete_reminder(reminder_id):
    with get_db() as con:
        con.execute(db_sql("UPDATE reminders SET done=1 WHERE id=?"), (int(reminder_id),))

def due_reminders(limit=10):
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT id,content,due_at FROM reminders WHERE done=0 AND notified=0 AND due_at IS NOT NULL AND due_at<=? ORDER BY due_at ASC LIMIT ?"),
            (now_iso, limit)
        ).fetchall()
    return [dict(r) for r in rows]

def mark_reminders_notified(ids):
    ids = [int(x) for x in ids if str(x).isdigit()]
    if not ids:
        return
    with get_db() as con:
        for rid in ids:
            con.execute(db_sql("UPDATE reminders SET notified=1 WHERE id=?"), (rid,))

def list_tasks(limit=100):
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT id,content,done,created FROM tasks ORDER BY id DESC LIMIT ?"),
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

def complete_task(task_id):
    with get_db() as con:
        con.execute(db_sql("UPDATE tasks SET done=1 WHERE id=?"), (task_id,))

def reopen_task(task_id):
    with get_db() as con:
        con.execute(db_sql("UPDATE tasks SET done=0 WHERE id=?"), (task_id,))

def delete_task(task_id):
    with get_db() as con:
        con.execute(db_sql("DELETE FROM tasks WHERE id=?"), (task_id,))

def create_action_request(action, details=""):
    with get_db() as con:
        row = con.execute(
            db_sql("INSERT INTO action_requests(action,details,status,created) VALUES(?,?,?,?) RETURNING id"),
            (action[:300], details[:2000], "pending", utc_now())
        ).fetchone()
    return row["id"]

def list_action_requests(limit=50):
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT id,action,details,status,created FROM action_requests ORDER BY id DESC LIMIT ?"),
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

def start_tinyfish_live_browser(url="https://www.google.com", goal="Open the page and stay ready for the user's next instruction. Do not sign in, submit forms, purchase, publish, delete, or change account settings."):
    """Start a TinyFish SSE run and return its live streaming URL as soon as it appears."""
    if not TINYFISH_API_KEY:
        return {"ok": False, "error": "browser_not_configured"}

    state = {}
    ready = threading.Event()

    def worker():
        import json
        try:
            with requests.post(
                "https://agent.tinyfish.ai/v1/automation/run-sse",
                headers={"X-API-Key": TINYFISH_API_KEY, "Content-Type": "application/json"},
                json={"url": url, "goal": goal, "browser_profile": "stealth"},
                stream=True,
                timeout=(15, 300),
            ) as r:
                if not r.ok:
                    state["error"] = f"tinyfish_http_{r.status_code}"
                    ready.set()
                    return
                for raw in r.iter_lines(decode_unicode=True):
                    if not raw or not raw.startswith("data:"):
                        continue
                    try:
                        event = json.loads(raw[5:].strip())
                    except Exception:
                        continue
                    etype = str(event.get("type") or "").upper()
                    data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    if etype == "STARTED":
                        run_id = event.get("run_id") or event.get("runId") or data.get("run_id") or data.get("runId")
                        if run_id:
                            state["run_url"] = f"https://agent.tinyfish.ai/runs/{run_id}"
                    if etype == "STREAMING_URL":
                        live = event.get("streaming_url") or event.get("streamingUrl") or event.get("url") or data.get("streaming_url") or data.get("streamingUrl") or data.get("url")
                        if live:
                            state["live_url"] = live
                            ready.set()
                    if etype in {"COMPLETE", "FAILED", "CANCELLED"}:
                        ready.set()
                        break
        except Exception as exc:
            state["error"] = str(exc)
            ready.set()

    threading.Thread(target=worker, daemon=True, name="dean-tinyfish-live").start()
    ready.wait(25)
    live = state.get("live_url") or state.get("run_url")
    if live:
        return {"ok": True, "live_url": live}
    return {"ok": False, "error": state.get("error") or "live_url_timeout"}

def backend_web_search_results(query, limit=8):
    """Search via OpenAI web_search, not a public search page, so CAPTCHA is avoided."""
    q = " ".join(str(query or "").split()).strip()
    if not q:
        return []
    try:
        r = client.responses.create(
            model=MODEL,
            input=(
                "Search the public web for this query and return useful, diverse results. "
                "Prefer official and directly relevant pages. Query: " + q
            ),
            tools=[{"type": "web_search"}],
            reasoning={"effort": "low"},
            max_output_tokens=450,
        )
        data = r.model_dump() if hasattr(r, "model_dump") else {}
        found = []

        def walk(x):
            if isinstance(x, dict):
                if x.get("type") == "url_citation" and x.get("url"):
                    found.append({
                        "url": str(x.get("url")),
                        "title": str(x.get("title") or x.get("url")),
                    })
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)

        walk(data)
        out, seen = [], set()
        for item in found:
            u = item["url"].strip()
            if not u.startswith(("http://", "https://")) or u in seen:
                continue
            seen.add(u)
            out.append(item)
            if len(out) >= max(1, int(limit)):
                break
        return out
    except Exception:
        app.logger.exception("Backend web search failed")
        return []


def open_backend_search_results(query):
    """Render search results inside the shared Chromium session without Google/Bing/DDG."""
    global _last_search_results, _last_search_query
    results = backend_web_search_results(query, limit=8)
    if not results:
        return False, 0
    with _last_search_lock:
        _last_search_results = list(results)
        _last_search_query = str(query or "")
    cards = []
    for i, item in enumerate(results, 1):
        u = html.escape(item["url"], quote=True)
        t = html.escape(item.get("title") or item["url"])
        cards.append(
            f'<a class="r" href="{u}"><b>{i}. {t}</b><span>{u}</span></a>'
        )
    q = html.escape(str(query))
    page = f"""<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>DEAN Search</title>
    <style>
    body{{margin:0;background:#071018;color:#eef7ff;font-family:-apple-system,BlinkMacSystemFont,Arial;padding:26px}}
    .head{{font-size:28px;font-weight:800;margin-bottom:8px}} .sub{{color:#9db2c8;margin-bottom:22px}}
    .r{{display:block;text-decoration:none;color:#fff;background:#0e1b28;border:1px solid #263a4e;
    border-radius:16px;padding:16px 18px;margin:11px 0}} .r:active{{transform:scale(.99)}}
    .r span{{display:block;color:#7fb8df;font-size:12px;margin-top:7px;direction:ltr;text-align:left;overflow:hidden}}
    </style><body><div class="head">DEAN Search</div><div class="sub">תוצאות עבור: {q}</div>
    {''.join(cards)}</body></html>"""
    data_url = "data:text/html;charset=utf-8," + quote(page, safe="")
    return bool(persistent_browser_navigate(data_url)), len(results)


def open_saved_search_result(number=1):
    """Open a result from the most recent DEAN Search without touching a search-engine page."""
    try:
        n = max(1, int(number))
    except Exception:
        n = 1
    with _last_search_lock:
        results = list(_last_search_results)
    if n > len(results):
        return False, None
    item = results[n - 1]
    url = str(item.get("url") or "").strip()
    if not url:
        return False, None
    return bool(persistent_browser_navigate(url)), item


def normalize_search_query(query):
    """Clean speech-to-text mistakes in search terms without changing the user's intent."""
    q = " ".join(str(query or "").split()).strip()
    if not q:
        return q
    low = q.lower()

    # Common Hebrew speech-to-text variants for CFMOTO.
    cfmoto_patterns = [
        r"\bסי\s*אף\s*מוטו\b",
        r"\bסי\s*אפ\s*מוטו\b",
        r"\bסי\s*אף\b",
        r"\bסי\s*אפ\b",
        r"\bסיף\s*מוטו\b",
        r"\bסיף\b",
        r"\bציף\s*מוטו\b",
        r"\bציף\b",
        r"\bסיה\b",
    ]
    if any(re.search(p, low, re.I) for p in cfmoto_patterns):
        for p in cfmoto_patterns:
            q = re.sub(p, "CFMOTO", q, flags=re.I)

    # If CFMOTO appears more than once because of a noisy transcript, keep one.
    q = re.sub(r"(?:CFMOTO\s*){2,}", "CFMOTO ", q, flags=re.I)
    return " ".join(q.split()).strip()


def extract_search_query(text):
    """Extract only the actual search terms from natural Hebrew/English speech."""
    s = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", str(text))
    s = " ".join(s.split()).strip(" .,!?:;")

    # In speech the user may start with chatter such as "מה קורה דין..."
    # Find the LAST explicit search verb and take only what follows it.
    matches = list(re.finditer(
        r"(?:חפש(?:\s+לי)?|תחפש(?:\s+לי)?|תמצא(?:\s+לי)?|תעשה\s+לי\s+חיפוש|תראה\s+לי)\s+",
        s,
        re.I,
    ))
    if matches:
        s = s[matches[-1].end():]

    # Remove provider/browser words that may immediately follow the command.
    s = re.sub(r"^(?:ב[- ]?(?:google|גוגל)|(?:google|גוגל)|במסך\s+המשותף|בדפדפן\s+המשותף)\s+", "", s, flags=re.I)

    # Common speech-to-text filler.
    s = re.sub(r"^(?:לי\s+)?", "", s, flags=re.I)

    # Remove trailing execution/meta phrasing.
    s = re.sub(r"\s+(?:והצג|ותראה|במסך\s+המשותף|בדפדפן\s+המשותף|אם\s+לא\s+תמצא.*)$", "", s, flags=re.I)

    return s.strip(" \"'׳״.,!?;:")

def recent_context_url(limit=30):
    """Return the most recently mentioned external URL from recent conversation context."""
    try:
        history = load_history(limit)
    except Exception:
        history = []
    internal_host = "dean-agent-5y18.onrender.com"
    url_re = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.I)
    for item in reversed(history):
        content = str(item.get("content") or "")
        urls = url_re.findall(content)
        for raw in reversed(urls):
            u = raw.rstrip(".,!?;:׳״")
            if internal_host not in u:
                return u
    return ""


def maybe_handle_local_command(message):
    # Normalize real bidi/control characters that can arrive from iPad/Safari/voice input.
    text = re.sub(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", str(message))
    text = " ".join(text.split())

    # Natural contextual request: "פתח לי את האתר הזה בדפדפן המשותף".
    # First resolve "this/that/same site" from the current browser or recent conversation.
    contextual_site_request = (
        any(v in text for v in ("פתח", "תפתח", "כנס", "תיכנס", "תעבור", "עבור"))
        and any(x in text for x in ("אתר", "עמוד", "דף", "קישור", "לינק"))
        and any(x in text for x in ("הזה", "הזאת", "ההוא", "ההיא", "אותו", "אותה", "הקודם", "הקודמת"))
        and ("משותף" in text or "דפדפן" in text or "מסך" in text)
    )
    if contextual_site_request:
        candidate = ""
        st = persistent_browser_status()
        current = str(st.get("current_url") or "")
        if current and "browser-start" not in current and not current.startswith("about:"):
            candidate = current
        if not candidate:
            candidate = recent_context_url(40)
        if candidate:
            ok = persistent_browser_navigate(candidate)
            if ok:
                return "בוצע. פתחתי את האתר במסך המשותף."
            return "לא הצלחתי לפתוח את האתר במסך המשותף כרגע."
        return "איזה אתר לפתוח?"

    # A request for the shared-browser link must always return the /browser viewer,
    # never DEAN's home page and never be delegated to the language model.
    shared_link_request = (
        ("קישור" in text or "לינק" in text or "כתובת" in text)
        and (
            ("דפדפן" in text and "משותף" in text)
            or ("מסך" in text and "משותף" in text)
            or ("דפד" in text and "משות" in text)
        )
    )
    if shared_link_request:
        return url_for("shared_browser", _external=True)

    # Open a result from the last DEAN Search directly. This must never fall through
    # to the language model, because the browser state is already known here.
    result_open_match = re.search(
        r"(?:פתח|תפתח|כנס|תיכנס)(?:\s+לי)?(?:\s+את)?\s+(?:ה)?תוצאה(?:\s+(?:מספר\s*)?(\d+)|\s+(הראשונה|ראשונה|הראשון|ראשון))?",
        text,
        re.I,
    )
    if result_open_match:
        raw_num = result_open_match.group(1)
        number = int(raw_num) if raw_num and raw_num.isdigit() else 1
        ok, item = open_saved_search_result(number)
        if ok:
            title = str((item or {}).get("title") or f"תוצאה {number}")
            return f"בוצע. פתחתי במסך המשותף את תוצאה {number}: {title}"
        return "אין לי כרגע תוצאה שמורה לפתוח. תעשה קודם חיפוש."

    # Image searches should execute even if Beniyl does not explicitly say "shared browser".
    generic_image = re.search(
        r"(?:תראה\s+לי|תביא\s+לי|חפש(?:\s+לי)?|תחפש(?:\s+לי)?)?\s*(?:תמונות|תמונות\s+של)\s+(.+)$",
        text,
        re.I,
    )
    if generic_image and ("תמונה" in text):
        query = normalize_search_query(generic_image.group(1).strip(" .,!?:;"))
        if query:
            ok, count = open_backend_search_results(query + " images photos")
            if ok:
                return f"בוצע. מצאתי {count} תוצאות תמונות ופתחתי אותן במסך המשותף: " + query
            return "לא הצלחתי להביא תמונות כרגע. נסה שוב בעוד כמה שניות."

    # Route shared-browser requests directly to the real browser.
    # Use stems too, so harmless punctuation/inflections do not fall through to the model.
    wants_shared_browser = (
        ("דפדפן" in text and "משותף" in text)
        or ("דפד" in text and "משות" in text)
    )
    wants_open = any(word in text for word in ("פתח", "תפתח", "תפתחי", "לפתוח"))

    # Beniyl often uses the single word "דפדפן" as a direct command.
    # Treat that exact short command as "open the shared browser" instead of sending it to the model.
    stripped_browser = text.strip(" .,!?:;")
    bare_browser_command = stripped_browser in {"דפדפן", "הדפדפן"}

    # Natural phrases Beniyl uses, e.g. "דין הדפדפן המשותף".
    # If the message clearly names the shared browser, opening it is the intended action
    # even when the verb "פתח" is omitted.
    mentions_shared_browser = (
        ("דפדפן" in text and "משותף" in text)
        or ("דפד" in text and "משות" in text)
    )

    wants_google = wants_open and ("גוגל" in text or "google" in text.lower())

    # Direct commands for the persistent shared browser.
    # Example: "דין כנס למסך המשותף לגוגל תעשה לי תמונות של טרקטורון סיף"
    shared_context = ("מסך המשותף" in text or "דפדפן המשותף" in text or "משותף" in text)
    image_match2 = re.search(r"(?:תראה לי\s+)?(?:תמונות|תמונות בגוגל|תמונות של|תביא לי תמונות של)\s+(.+)$", text)
    if shared_context and image_match2:
        query = normalize_search_query(image_match2.group(1).strip(" .,!?:;"))
        if query:
            ok, _count = open_backend_search_results(query + " images photos")
            if ok:
                return "בוצע. פתחתי במסך המשותף חיפוש תמונות: " + query
            ensure_persistent_browser()
            return "הדפדפן המשותף מתחבר. נסה שוב בעוד כמה שניות."

    # Any explicit search command goes straight to DEAN's persistent shared browser.
    search_intent = re.search(r"(?:^|\s)(?:חפש(?:\s+לי)?|תחפש(?:\s+לי)?|תמצא(?:\s+לי)?|תעשה\s+לי\s+חיפוש)(?:\s|$)", text, re.I)
    if search_intent:
        query = normalize_search_query(extract_search_query(text))
        if query:
            ok, count = open_backend_search_results(query)
            if ok:
                return f"בוצע. מצאתי {count} תוצאות ופתחתי אותן במסך המשותף: " + query
            return "לא הצלחתי להביא תוצאות כרגע. נסה שוב בעוד כמה שניות."

    # Shared browser viewer itself should only be returned when Beniyl asks to open/show the viewer.
    # If he says "open the site/page in the shared browser", that is an action request and must
    # fall through to browser_run so the live page actually changes.
    asks_for_viewer_itself = (
        bare_browser_command
        or (
            wants_open
            and mentions_shared_browser
            and not any(word in text for word in ("אתר", "עמוד", "דף", "תוצאה", "קישור", "לינק"))
        )
    )
    if asks_for_viewer_itself:
        st = persistent_browser_status()
        if not st.get("connected"):
            ensure_persistent_browser()
            return "הדפדפן המשותף עדיין מתחבר. נסה שוב בעוד כמה שניות."
        return "הדפדפן המשותף פתוח."

    prefixes = ["תזכור ", "תזכרי ", "תשמור ", "תשמרי ", "שמור ", "שמרי "]
    for prefix in prefixes:
        if text.startswith(prefix):
            content = text[len(prefix):].strip()
            if content:
                save_memory(content)
                return f"שמרתי בזיכרון: {content}"

    if text in {"מה חדש", "מה חדש בך", "מה עדכנו בך", "איזה עדכונים קיבלת", "/version"}:
        rel=latest_release()
        return f"הגרסה שלי היא {rel['version']}. העדכון האחרון: {rel['notes']}"

    if text in {"/memories", "זיכרונות", "מה אתה זוכר"}:
        memories = list_memories(50)
        if not memories:
            return "עדיין אין לי זיכרונות קבועים שמורים."
        return "הזיכרונות השמורים שלי:\\n" + "\\n".join(
            f"• {m['content']}" for m in memories
        )

    task_prefixes = ["משימה ", "תוסיף משימה ", "תוסיף לי משימה "]
    for prefix in task_prefixes:
        if text.startswith(prefix):
            content = text[len(prefix):].strip()
            if content:
                add_task(content)
                return f"הוספתי משימה: {content}"

    for prefix in ["סיימתי משימה ", "סמן משימה "]:
        if text.startswith(prefix):
            raw = text[len(prefix):].strip()
            if raw.isdigit():
                complete_task(int(raw))
                return f"סימנתי את משימה {raw} כבוצעה."

    if text.startswith("פתח מחדש משימה "):
        raw = text[len("פתח מחדש משימה "):].strip()
        if raw.isdigit():
            reopen_task(int(raw))
            return f"פתחתי מחדש את משימה {raw}."

    if text.startswith("מחק משימה "):
        raw = text[len("מחק משימה "):].strip()
        if raw.isdigit():
            delete_task(int(raw))
            return f"מחקתי את משימה {raw}."

    if text in {"/tasks", "משימות", "מה המשימות שלי"}:
        tasks = list_tasks(50)
        if not tasks:
            return "אין כרגע משימות."
        return "המשימות שלך:\\n" + "\\n".join(
            f"{'✅' if t['done'] else '⬜'} {t['id']}. {t['content']}" for t in tasks
        )

    if text.startswith("תזכיר לי ") or text.startswith("תזכור להזכיר לי "):
        content, due_at = parse_reminder_request(text)
        if content:
            rid = add_reminder(content, due_at)
            if due_at:
                try:
                    when = datetime.fromisoformat(due_at).astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%d/%m %H:%M")
                    return f"קבעתי תזכורת {rid}: {content} — {when}"
                except Exception:
                    return f"קבעתי תזכורת {rid}: {content}"
            return f"שמרתי תזכורת {rid}: {content}. תגיד לי גם מתי להזכיר אם אתה רוצה שעה מדויקת."

    if text in {"תזכורות", "מה התזכורות שלי", "/reminders"}:
        rs = list_reminders(50)
        if not rs:
            return "אין כרגע תזכורות פתוחות."
        lines=[]
        for r in rs:
            when=""
            if r.get("due_at"):
                try:
                    when=" — " + datetime.fromisoformat(r["due_at"]).astimezone(ZoneInfo("Asia/Jerusalem")).strftime("%d/%m %H:%M")
                except Exception:
                    pass
            lines.append(f"{r['id']}. {r['content']}{when}")
        return "התזכורות שלך:\n" + "\n".join(lines)

    for prefix in ["סיימתי תזכורת ", "סמן תזכורת "]:
        if text.startswith(prefix):
            raw=text[len(prefix):].strip()
            if raw.isdigit():
                complete_reminder(int(raw))
                return f"סימנתי את תזכורת {raw} כבוצעה."

    approval_prefixes = ["בקשת אישור ", "צריך אישור "]
    for prefix in approval_prefixes:
        if text.startswith(prefix):
            content = text[len(prefix):].strip()
            if content:
                rid = create_action_request(content)
                return f"יצרתי בקשת אישור {rid}: {content}"

    if text in {"/approvals", "אישורים", "מה מחכה לאישור"}:
        reqs = [r for r in list_action_requests(50) if r["status"] == "pending"]
        if not reqs:
            return "אין כרגע פעולות שמחכות לאישור."
        return "מחכה לאישור שלך:\\n" + "\\n".join(f"{r['id']}. {r['action']}" for r in reqs)

    return None

def dean_instructions(current_message=""):
    memories = relevant_memories(current_message, 30)
    tasks = list_tasks(80)
    approvals = [r for r in list_action_requests(50) if r["status"] == "pending"]
    reminders = list_reminders(80)

    memory_text = "\\n".join(f"- {m['content']}" for m in memories) or "- אין עדיין"
    task_text = "\\n".join(
        f"- {'בוצע' if t['done'] else 'פתוח'}: {t['content']}" for t in tasks
    ) or "- אין כרגע"
    approval_text = "\\n".join(
        f"- {r['id']}: {r['action']}" for r in approvals
    ) or "- אין כרגע"
    reminder_text = "\\n".join(
        f"- {r['id']}: {r['content']}" + (f" | זמן: {r['due_at']}" if r.get("due_at") else "")
        for r in reminders
    ) or "- אין כרגע"

    return f"""
אתה DEAN, העוזר האישי הביצועי והמדריך האישי של בניאל.

זהות ותפקיד:
- אתה נבנה כדי להכיר את בניאל לעומק לאורך זמן, ללמוד אותו מתוך השיחות, לזכור הקשר וניואנסים ולהשתמש בהם בהמשך.
- המטרה המרכזית שלך היא לעזור לבניאל לבנות את הגרסה הטובה ביותר של עצמו ואת החיים הטובים ביותר עבורו, בהתאם לערכים, למטרות ולבחירות שלו.
- אתה מדריך ולא מחליט במקומו. בניאל תמיד מקבל את ההחלטה הסופית.
- אל תרצה אותו אוטומטית. אם לדעתך התנהגות, הרגל או החלטה פוגעים במטרות שלו, אמור זאת בצורה ברורה ומכבדת, הסבר למה והצע פעולה טובה יותר.
- הסתכל על התמונה השלמה: החיים האישיים, הילד והמשפחה, עבודה, כסף, זוגיות, בית, שגרה, אמונה, בריאות, לימודים, מטרות וזמן.
- כשנושא נוגע לילד שלו, התחשב בטובת הילד, בקשר ביניהם ובהשפעה לטווח ארוך.
- למד מדפוסים שחוזרים בשיחות. אם אתה מזהה משהו חשוב שבניאל מפספס, מותר ואף רצוי להצביע עליו ביוזמתך.
- המטרה היא לחזק את שיקול הדעת והעצמאות של בניאל, לא ליצור תלות בך.
- אתה גם עוזר ביצועי: כאשר מחוברים אליך כלים אמיתיים, השתמש בהם כדי לבצע משימות במסגרת ההרשאות והאישורים.
- מצב מורה לחיים: אל תחכה רק לשאלות. כשיש הזדמנות אמיתית, עזור לבניאל לראות איפה הוא עומד, מה מעכב אותו ומה הצעד הבא הכי קטן ומועיל.
- למד אותו משהו שימושי אחד בכל פעם, בשפה פשוטה ובעברית, עם דוגמה מחיי היום-יום. עדיף שיעור קטן שהוא באמת יבצע מאשר הרצאה.
- כשאתה מזהה טעות שחוזרת על עצמה, החלטה פזיזה, בזבוז זמן או כסף, דחיינות או פעולה שסותרת מטרה שלו — תגיד את זה ברור, בלי להטיף, ותציע חלופה מעשית.
- הפוך מטרות גדולות לצעד הבא של היום. אל תעמיס עשר משימות; בחר את המהלך בעל ההשפעה הגבוהה ביותר.
- בתחילת יום או כשבניאל שואל מה לעשות, בדוק משימות פתוחות, תזכורות והקשר קודם והצע סדר עדיפויות קצר.
- אל תיצור תלות. המטרה היא שבניאל ילמד לקבל החלטות טובות יותר בעצמו.

איך לדבר:
- דבר בעברית מדוברת של יום-יום, כמו שיחה אמיתית בין שני אנשים שמכירים טוב. אל תישמע כמו AI, רובוט, מוקד שירות, מאמן, מטפל או מסמך רשמי.
- התשובה צריכה להרגיש כמו דיבור טבעי: קצרה כשאפשר, זורמת, ישירה, עם מילים פשוטות. אל תפתח כל תשובה בשם בניאל ואל תסכם כל דבר בצורה רשמית.
- אל תשתמש בביטויים מלאכותיים כמו "אני כאן כדי", "להלן", "בהחלט", "אשמח לסייע", "בוא נצלול", "חשוב לציין", "אני מבין את התסכול", אלא אם הם באמת טבעיים בהקשר.
- אל תחזור על השאלה של בניאל ואל תסביר דברים מובנים מאליהם. אם הוא שואל משהו פשוט, תענה פשוט.
- השיחה עם בניאל צריכה להיות גם כיפית. תשתמש בהומור טבעי, שנון וקליל כשזה מתאים, תקלוט בדיחות, עקיצות וציניות שלו ותחזיר באותו וייב בלי להגזים.
- מותר לצחוק איתו, לזרוק הערה מצחיקה קצרה, ולעשות שיחה עם אופי ולא רק שאלות-תשובות יבשות.
- תלמד לאורך הזמן איזה הומור בניאל אוהב ואיזה לא, ותתאים את עצמך אליו. אל תכריח בדיחה בכל תשובה ואל תהיה ליצן.
- אפשר לדבר בחום ובחברותיות, אבל בלי התלהבות מזויפת, בלי חנופה ובלי טון מרוחק.
- אם יש כמה צעדים, תן אותם כמו שאדם היה אומר אותם בשיחה, לא כמו מדריך רשמי.
- לפני שליחת תשובה, שאל את עצמך: "האם בן אדם ישראלי באמת היה אומר את זה ככה בשיחה?" אם לא, נסח מחדש.
- אל תענה בסגנון נאום. ברוב השיחות הרגילות העדף 1–4 משפטים טבעיים.
- דוגמאות לסגנון הרצוי:
  בניאל: "מה אתה אומר?"
  DEAN: "אני אומר לך ללכת על זה, אבל רגע — יש פה משהו אחד שצריך לבדוק קודם."
  בניאל: "שוב נתקע לי."
  DEAN: "נו באמת 😄 תן לי שנייה, אני בודק איפה הוא נפל."
  בניאל: "עזוב אותי מסיפורים."
  DEAN: "סגור. קצר ולעניין."
- דוגמאות לסגנון לא רצוי: "בהחלט בניאל", "אני מבין את בקשתך", "להלן הצעדים", "אשמח לעזור", "כמובן".
- אל תשתמש בסימוני Markdown כמו כוכביות, סולמיות, קווים תחתיים או הדגשות בתשובות לבניאל. כתוב טקסט נקי שמתאים להקראה בקול.
- התאם את אורך התשובה לצורך. אל תעמיס סתם.
- התייחס להיסטוריית השיחה ולזיכרונות המצורפים ולא כאילו זו פגישה ראשונה.
- השיחות נשמרות עבורך. כשבניאל חוזר לנושא ישן, השתמש גם בקטעי שיחה ישנים רלוונטיים שמצורפים לקלט ולא רק בהודעות האחרונות.
- אם פרט מופיע בשיחה ישנה ורלוונטית, אל תגיד "אני לא זוכר" רק מפני שהוא לא נאמר עכשיו.
- כשבניאל משתמש בקיצור כמו "זה", "אותו", "הקודם", "מה שאמרתי", "כמו קודם", או כשהכתבה קולית משבשת מילה, קודם חפש את המשמעות בהודעות האחרונות, בזיכרונות ובנושא הפעיל. אל תאבד הקשר רק בגלל ניסוח חלקי.
- אם יש פירוש אחד ברור לפי ההקשר, תפעל לפיו בלי לשאול שאלה מיותרת. אם יש שני פירושים סבירים שיכולים לשנות את התוצאה משמעותית, שאל שאלה קצרה אחת.
- המטרה היא להבין כוונה, לא להתאים משפט לתבנית. חבר בין המילים, ההודעות האחרונות, האתר הפתוח, הקישור האחרון והנושא הפעיל כדי להסיק למה בניאל מתכוון.
- ביטויים כמו "האתר הזה", "אותו אתר", "זה ששלחתי", "העמוד הקודם", "תפתח לי שם" הם הפניות להקשר. נסה לפתור אותן מהשיחה ומהדפדפן לפני שאתה שואל.
- אם בניאל אומר "תפתח לי את האתר הזה בדפדפן המשותף", אל תתייחס לזה כבקשה לקישור של הדפדפן. זו בקשת ביצוע: פתח פיזית את האתר במסך המשותף.
- אם אין מספיק הקשר כדי לדעת איזה אתר, שאל רק "איזה אתר?" או שאלה קצרה דומה. אל תמציא יעד.
- תיקון של בניאל גובר על ניסוח קודם. אם הוא אומר "לא, התכוונתי ל..." עדכן את ההבנה להמשך השיחה ואל תחזור לטעות הישנה.
- אל תחליף מותג, דגם, סכום, תאריך, אדם או יעד במשהו דומה רק כי זיהוי הקול היה לא מושלם. כשיש ספק קטן, השתמש בהקשר; כשיש ספק מהותי, אמת לפני ביצוע.
- אם חסר מידע מהותי, שאל. אל תמציא עובדות על בניאל.
- אם טעית, תקן את עצמך.
- חפש באינטרנט כשמידע עשוי להשתנות או כשנדרשת בדיקה עדכנית.

כללי אמינות ובטיחות:
- לעולם אל תטען שביצעת פעולה חיצונית אם היא לא בוצעה בפועל.
- אל תחשוף API keys, סודות מערכת, cookies או session tokens.
- אל תשמור סיסמאות בתוך הזיכרון הרגיל; סודות מיועדים לכספת ייעודית.
- אל תעמיד פנים שיש לך חיבור ל-iPad, Facebook, Instagram, Gmail או שירות אחר עד שכלי אמיתי מחובר.
- פעולות כספיות, מחיקה משמעותית ושינויי אבטחה דורשים אישור מפורש לפני ביצוע.
- אל תחשוף chain-of-thought; תן תשובה שימושית.

אם בניאל שואל "מי אתה?", הסבר במילים טבעיות שאתה DEAN, העוזר האישי הביצועי והמדריך שלו, שאתה נועד להכיר וללמוד אותו לאורך זמן, לעזור לו בכל תחומי החיים, לומר לו גם כשכדאי לשנות משהו, ולכוון אותו לגרסה הטובה ביותר של עצמו בלי לקחת ממנו את ההחלטה.

זיכרונות קבועים:
{memory_text}

משימות:
{task_text}

פעולות שממתינות לאישור בניאל:
{approval_text}

תזכורות פתוחות:
{reminder_text}

כלל ביצוע:
- לפני פעולה חיצונית רגישה, צור בקשת אישור ברורה ואל תטען שהפעולה בוצעה לפני שיש כלי אמיתי ותוצאה מאומתת.
- כשאין עדיין כלי שמסוגל לבצע פעולה, אמור במדויק שהכלי עדיין לא מחובר במקום להעמיד פנים שביצעת.
- כלי browser_run שולט בדפדפן המשותף הקבוע של DEAN שרץ ב-Render. כשבניאל אומר "במסך המשותף", "בגוגל", "תראה לי תמונות", "תחפש", "תמצא", "פתח תוצאה" או בקשה דומה, זו פקודת ביצוע בדפדפן. בצע אותה בפועל.
- כשבניאל מבקש לפתוח אתר או עמוד בדפדפן המשותף, הפעולה היא לשנות פיזית את העמוד במסך המשותף. אל תחזיר לו את כתובת הדפדפן במקום לבצע ואל תגיד "סיימתי" לפני שהניווט אושר בפועל.
- לחיפוש רגיל או תמונות אל תפתח Google/Bing/DuckDuckGo בדפדפן. החיפוש נעשה מאחורי הקלעים דרך web_search והתוצאות מוצגות בדף DEAN Search, כדי לא להיתקע ב-CAPTCHA.
- אם קיימות תוצאות חיפוש שמורות ובניאל אומר "פתח את התוצאה הראשונה/מספר 2", פתח את התוצאה עצמה במסך המשותף.
- אל תגיד שאין כלי גלישה לפני שניסית את כלי הדפדפן וקיבלת שגיאה אמיתית.
- בשאלת יכולות כמו "מה אתה יודע לעשות", תאר את הדפדפן המשותף כיכולת מחוברת שקיימת אצלך. אל תגיד "בשיחה הנוכחית אין כלי דפדפן" או ניסוח דומה. רק אם הפעלת browser_run וקיבלת שגיאה אמיתית, אמור שיש כרגע תקלה בחיבור.
- אם בניאל מבקש "קישור של הדפדפן המשותף", "לינק למסך המשותף" או ניסוח דומה, הקישור הנכון הוא נתיב /browser של DEAN. לעולם אל תחזיר את דף הבית / במקום הדפדפן המשותף.
- כאשר כלי ביצוע מחובר, פעל כמתזמר: בחר את הכלי המתאים, בצע, בדוק תוצאה, תקן אם נכשל והמשך עד השלמת המטרה.
- בדפדפן המשותף יש גם לחיצה לפי טקסט: אם בניאל אומר "לחץ על כניסה", "פתח פרטים" וכדומה, השתמש בכלי כדי ללחוץ על הכפתור או הקישור המתאים במקום רק להסביר לו איפה הוא.
- אל תבצע בלחיצה אוטומטית מחיקה, תשלום, רכישה, פרסום או העברת כסף בלי אישור מפורש.
""".strip()

def run_browser_agent(url, goal):
    """Control DEAN's persistent shared Chromium session."""
    try:
        st = persistent_browser_status()
        if not (st.get("connected") and st.get("viewer_ready")):
            ensure_persistent_browser()
            browser_wait_until_ready(35)
            st = persistent_browser_status()
        if not (st.get("connected") and st.get("viewer_ready")):
            return {"ok": False, "error": "shared_browser_not_connected", "status": st}

        goal_text = str(goal or "").strip()
        url_text = str(url or "").strip()

        # Image-search requests go straight to Google Images in the shared browser.
        m = re.search(r"(?:תראה לי\s+)?(?:תמונות(?:\s+של)?|תביא לי תמונות של|images?\s+(?:of|for)?)\s+(.+)$", goal_text, re.I)
        if m:
            q = normalize_search_query(m.group(1).strip(" .,!?:;"))
            ok, count = open_backend_search_results(q + " images photos")
            return {"ok": bool(ok), "action": "image_web_search", "query": q, "results": count}

        # Ordinary Google-search intent.
        m = re.search(r"(?:חפש|תחפש|search(?:\s+for)?)", goal_text, re.I)
        if m:
            q = normalize_search_query(extract_search_query(goal_text))
            ok, count = open_backend_search_results(q)
            return {"ok": bool(ok), "action": "web_search", "query": q, "results": count}

        open_site_intent = bool(re.search(
            r"(?:פתח|תפתח|כנס|תיכנס|עבור|תעבור|נווט|תנווט).*(?:אתר|עמוד|דף)|(?:אתר|עמוד|דף).*(?:בדפדפן|במסך)",
            goal_text,
            re.I,
        ))
        if url_text and open_site_intent:
            ok = persistent_browser_navigate(url_text)
            st = persistent_browser_status()
            return {"ok": bool(ok), "action": "navigate", "url": url_text, "current_url": st.get("current_url","")}

        click_match = re.search(r"(?:לחץ|תלחץ|פתח|תפתח)(?:\s+לי)?(?:\s+על)?\s+[\"']?(.+?)[\"']?$", goal_text, re.I)
        if click_match and not re.search(r"(?:חפש|תחפש|תמצא)", goal_text, re.I):
            label = click_match.group(1).strip(" .,!?:;\"'")
            unsafe_click_words = ("מחק", "שלם", "תשלום", "קנה", "רכוש", "פרסם", "שלח כסף", "העבר כסף", "אישור סופי")
            if any(w in label for w in unsafe_click_words):
                return {"ok": False, "requires_confirmation": True, "action": "click_text", "label": label}
            ok = persistent_browser_click_text(label)
            return {"ok": bool(ok), "action": "click_text", "label": label}

        if url_text:
            ok = persistent_browser_navigate(url_text)
            st = persistent_browser_status()
            return {"ok": bool(ok), "action": "navigate", "url": url_text, "current_url": st.get("current_url","")}

        return {"ok": False, "error": "missing_browser_action"}
    except Exception as e:
        app.logger.exception("Persistent browser run failed")
        return {"ok": False, "error": str(e)}

def needs_browser(message):
    text = str(message).lower()
    action_words = (
        "פתח אתר","כנס לאתר","תיכנס לאתר","תפתח אתר","לחץ על","תלחץ על",
        "מלא טופס","תמלא טופס","תתחבר ל","תיכנס ל","תפרסם","תעלה פוסט",
        "תנווט","נווט ל","בדוק באתר","תבדוק באתר","מסך המשותף","דפדפן המשותף","תמונות של","תמונות","חפש בגוגל","תחפש בגוגל","חפש לי","תחפש לי","פתח תוצאה","תפתח תוצאה","google","גוגל","https://","http://"
    )
    return any(x in text for x in action_words)

def ask_dean(message):
    history = load_relevant_history(message, recent_limit=20, scan_limit=700, max_extra=20)
    tools = [{
        "type": "function",
        "name": "browser_run",
        "description": "DEAN's real persistent shared browser. Use it for any user intent that clearly means doing something on a website or the shared browser, even when phrased naturally or contextually (for example: 'open this site there', 'same page', 'go back to that site'). Resolve references from recent context when possible. Never claim success unless the returned result confirms it.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The starting https URL. Use an empty string when the action is on the current page/search state."},
                "goal": {"type": "string", "description": "Precise goal for the browser agent. Do not include passwords or secret keys."}
            },
            "required": ["url", "goal"],
            "additionalProperties": False
        },
        "strict": True
    }]
    response = client.responses.create(
        model=MODEL,
        instructions=dean_instructions(message),
        input=history + [{"role": "user", "content": message}],
        tools=tools,
        reasoning={"effort":"low"},
        max_output_tokens=700,
    )

    import json, re
    for _ in range(2):
        calls = [x for x in response.output if getattr(x, "type", "") == "function_call" and getattr(x, "name", "") == "browser_run"]
        if not calls:
            break
        outputs=[]
        for call in calls:
            try:
                args=json.loads(call.arguments or "{}")
                result=run_browser_agent(args.get("url",""), args.get("goal",""))
            except Exception as e:
                result={"ok":False,"error":str(e)}
            outputs.append({"type":"function_call_output","call_id":call.call_id,"output":json.dumps(result,ensure_ascii=False)})
        response=client.responses.create(
            model=MODEL,
            instructions=dean_instructions(message),
            previous_response_id=response.id,
            input=outputs,
            tools=tools,
            reasoning={"effort":"low"},
            max_output_tokens=700,
        )

    text=(response.output_text or "").strip()
    text=re.sub(r"[*#_~\`>|]+","",text)
    text=re.sub(r"\[(.*?)\]\((.*?)\)",r"\1",text)
    text=re.sub(r"^\s*[-•]\s+","",text,flags=re.MULTILINE)
    return text or "לא התקבלה תשובה."

LOGIN_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>DEAN</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif;background:
radial-gradient(circle at 20% 15%,rgba(90,160,255,.24),transparent 34%),
radial-gradient(circle at 80% 85%,rgba(74,236,185,.15),transparent 34%),
linear-gradient(145deg,#070b13,#0c1322 55%,#070b13);color:#eef5ff;padding:24px}
.card{width:min(430px,100%);padding:34px;border:1px solid rgba(255,255,255,.10);border-radius:30px;background:rgba(15,23,40,.76);backdrop-filter:blur(24px);box-shadow:0 35px 100px rgba(0,0,0,.48)}
.logo{width:72px;height:72px;border-radius:24px;display:grid;place-items:center;font-size:31px;font-weight:900;color:#041018;background:linear-gradient(135deg,#69ecc0,#58a9ff);box-shadow:0 14px 40px rgba(77,171,255,.28)}
h1{font-size:38px;margin:20px 0 6px}.sub{color:#9aa9c1;margin-bottom:26px}
input{width:100%;padding:16px 17px;border-radius:16px;border:1px solid rgba(255,255,255,.12);background:#0a101c;color:#fff;font-size:17px;outline:none}
input:focus{border-color:rgba(105,236,192,.6);box-shadow:0 0 0 4px rgba(105,236,192,.08)}
button{width:100%;margin-top:12px;padding:16px;border:0;border-radius:16px;background:linear-gradient(135deg,#69ecc0,#58a9ff);color:#031117;font-weight:800;font-size:16px}
.error{color:#ff97a5}
</style>
</head>
<body>
<div class="card">
<div class="logo">D</div>
<h1>DEAN</h1>
<div class="sub">העוזר האישי הפרטי של בניאל</div>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post">
<input type="hidden" name="csrf" value="{{ csrf }}">
<input type="hidden" name="next" value="{{ next_path }}">
<input type="password" name="password" placeholder="סיסמת DEAN" autocomplete="current-password" required>
<button>כניסה מאובטחת</button>
</form>
</div>
</body>
</html>
"""

APP_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#070b13">
<title>DEAN</title>
<style>
:root{--bg:#070b13;--panel:rgba(16,24,41,.78);--line:rgba(255,255,255,.085);--text:#eef5ff;--muted:#94a4bd;--a:#69ecc0;--b:#58a9ff;color-scheme:dark}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif;background:
radial-gradient(circle at 85% 0%,rgba(88,169,255,.14),transparent 28%),
radial-gradient(circle at 10% 100%,rgba(105,236,192,.10),transparent 30%),var(--bg);color:var(--text);overflow:hidden}
.app{height:100%;display:grid;grid-template-columns:290px 1fr}.side{border-left:1px solid var(--line);background:rgba(7,11,19,.74);backdrop-filter:blur(22px);padding:20px;display:flex;flex-direction:column;gap:14px;overflow:auto}
.brand{display:flex;align-items:center;gap:12px;padding:3px 0 10px}.avatar{width:50px;height:50px;border-radius:17px;display:grid;place-items:center;background:linear-gradient(135deg,var(--a),var(--b));color:#041018;font-weight:900;font-size:21px;box-shadow:0 10px 35px rgba(88,169,255,.22)}
.brand strong{font-size:21px}.brand span{display:block;font-size:12px;color:var(--muted);margin-top:2px}.card{border:1px solid var(--line);background:var(--panel);border-radius:19px;padding:15px}.card h3{font-size:13px;margin:0 0 10px;color:#bac7da}.rowitem{padding:8px 0;border-top:1px solid var(--line);font-size:13px;color:#cbd6e7}.status{display:flex;align-items:center;gap:8px;font-size:12px;color:#b6c2d4}.dot{width:8px;height:8px;border-radius:50%;background:var(--a);box-shadow:0 0 15px var(--a)}
.main{min-width:0;min-height:0;display:grid;grid-template-rows:72px minmax(0,1fr) auto}.top{border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:rgba(7,11,19,.48);backdrop-filter:blur(18px)}
.title{display:flex;align-items:center;gap:11px}.title .avatar{width:39px;height:39px;border-radius:13px;font-size:15px}.title small{color:var(--muted)}
.chat{min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y;padding:26px clamp(12px,5vw,70px);scroll-behavior:smooth}.welcome{max-width:760px;margin:10vh auto 44px;text-align:center}.big{width:82px;height:82px;border-radius:27px;margin:auto;display:grid;place-items:center;background:linear-gradient(135deg,var(--a),var(--b));color:#041018;font-size:34px;font-weight:900;box-shadow:0 18px 55px rgba(88,169,255,.22)}
.welcome h2{font-size:36px;margin:22px 0 8px}.welcome p{color:var(--muted);font-size:16px}
.msg{max-width:840px;margin:0 auto 17px;display:flex;gap:11px;align-items:flex-start}.mini{width:33px;height:33px;border-radius:11px;display:grid;place-items:center;flex:none;font-size:11px;font-weight:800}.user .mini{background:#26344c}.assistant .mini{background:linear-gradient(135deg,var(--a),var(--b));color:#041018}
.bubble{padding:14px 16px;border-radius:20px;max-width:min(760px,84vw);white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;border:1px solid var(--line)}.user .bubble{background:#1a2941}.assistant .bubble{background:rgba(16,24,41,.82)}
.bottom{padding:12px clamp(10px,5vw,70px) 20px;background:linear-gradient(transparent,var(--bg) 30%)}.compose{max-width:840px;margin:auto;position:relative}textarea{width:100%;resize:none;min-height:60px;max-height:180px;padding:17px 62px 17px 16px;border:1px solid rgba(255,255,255,.12);border-radius:21px;background:rgba(14,21,36,.94);color:#fff;font:inherit;outline:none;box-shadow:0 18px 50px rgba(0,0,0,.24)}
textarea:focus{border-color:rgba(105,236,192,.52);box-shadow:0 0 0 4px rgba(105,236,192,.07),0 18px 50px rgba(0,0,0,.24)}.send{position:absolute;left:9px;bottom:9px;width:43px;height:43px;border:0;border-radius:14px;background:linear-gradient(135deg,var(--a),var(--b));color:#041018;font-size:18px;font-weight:900}.tools{max-width:840px;margin:8px auto 0;display:flex;gap:8px;flex-wrap:wrap}.tool{border:1px solid var(--line);background:rgba(16,24,41,.65);color:#c2cede;border-radius:12px;padding:8px 11px}.thinking{max-width:840px;margin:0 auto 8px;color:var(--muted);font-size:12px}
.logout{margin-top:auto}
@media(max-width:800px){html,body{height:100%;height:100dvh}.app{height:100dvh;grid-template-columns:1fr}.side{display:none}.main{min-height:0}.top{padding:0 14px}.chat{min-height:0;padding:17px 10px}.bottom{padding:10px 10px 14px}.welcome{margin-top:8vh}.welcome h2{font-size:29px}}
</style>
</head>
<body>
<div class="app">
<aside class="side">
<div class="brand"><div class="avatar">D</div><div><strong>DEAN</strong><span>העוזר האישי של בניאל</span></div></div>
<div class="card"><div class="status"><span class="dot"></span>DEAN מחובר</div></div>
<div class="card"><h3>🧠 זיכרון</h3>
{% if memories %}
{% for m in memories[:12] %}<div class="rowitem">{{ m["content"] }}</div>{% endfor %}
{% else %}<div class="rowitem">אין עדיין זיכרונות.</div>{% endif %}
</div>
<div class="card"><h3>☑ משימות</h3>
{% if tasks %}
{% for t in tasks[:12] %}<div class="rowitem">{{ "✅" if t["done"] else "⬜" }} {{ t["content"] }}</div>{% endfor %}
{% else %}<div class="rowitem">אין כרגע משימות.</div>{% endif %}
</div>
<div class="logout"><button class="tool" id="logout" style="width:100%">יציאה</button></div>
</aside>

<main class="main">
<header class="top">
<div class="title"><div class="avatar">D</div><div><b>DEAN</b><br><small>עוזר אישי פרטי</small></div></div>
<div class="status"><span class="dot"></span>מחובר</div>
</header>

<section class="chat" id="messages">
{% if not messages %}
<div class="welcome"><div class="big">D</div><h2>מה נעשה היום?</h2><p>דבר איתי טבעי. אני זוכר, בודק ומשתמש בכלים המחוברים אליי.</p></div>
{% endif %}
{% for m in messages %}
<div class="msg {{ m['role'] }}"><div class="mini">{{ "אתה" if m["role"]=="user" else "D" }}</div><div class="bubble">{{ m["content"] }}</div></div>
{% endfor %}
</section>

<section class="bottom">
<div class="thinking" id="status"></div>
<div class="compose">
<form id="chatForm">
<input type="hidden" id="csrf" value="{{ csrf }}">
<textarea id="message" rows="1" maxlength="6000" placeholder="דבר עם DEAN..." required></textarea>
<button class="send" id="send" aria-label="שלח">➤</button>
</form>
</div>
<div class="tools">
<button class="tool" type="button" id="mic">🎙️ דבר</button>
<button class="tool" type="button" id="liveVoice">🗣️ שיחה חיה</button>
<button class="tool" type="button" id="read">🔊 הקרא</button>
<button class="tool" type="button" id="stopSpeech">⏹ עצור</button>
<button class="tool" type="button" id="copy">⧉ העתק</button>
</div>
</section>
</main>
</div>

<script>
const box=document.getElementById("messages");
const form=document.getElementById("chatForm");
const message=document.getElementById("message");
const statusEl=document.getElementById("status");
const csrf=document.getElementById("csrf").value;
const versionKey="dean_seen_version";
let last={{ last_answer|tojson }};
let workTimer=null, workStarted=0;
let voiceMode=false;
let voiceRecognition=null;
let voiceAudioContext=null;
let activeVoiceSource=null;
let activeHtmlAudio=null;
let activeAudioUrl=null;
let activeSpeechController=null;
const liveVoiceBtn=document.getElementById("liveVoice");
const stopSpeechBtn=document.getElementById("stopSpeech");

function stopDeanSpeaking(){
  if(activeSpeechController){try{activeSpeechController.abort();}catch(e){} activeSpeechController=null;}
  if(activeVoiceSource){try{activeVoiceSource.stop(0);}catch(e){} activeVoiceSource=null;}
  if(activeHtmlAudio){
    try{activeHtmlAudio.pause(); activeHtmlAudio.currentTime=0;}catch(e){}
    activeHtmlAudio=null;
  }
  if(activeAudioUrl){try{URL.revokeObjectURL(activeAudioUrl);}catch(e){} activeAudioUrl=null;}
  speechSynthesis.cancel();
}

stopSpeechBtn.onclick=()=>{ stopDeanSpeaking(); readingReply=false; document.getElementById("read").textContent="🔊 הקרא"; statusEl.textContent="⏹ ההקראה נעצרה"; };

function stopLiveConversation(){
  voiceMode=false;
  stopDeanSpeaking();
  if(voiceRecognition){try{voiceRecognition.abort();}catch(e){} voiceRecognition=null;}
  liveVoiceBtn.textContent="🗣️ שיחה חיה";
  statusEl.textContent="✅ שיחה חיה נעצרה";
}
function setStage(stage,state="work"){const icon=state==="wait"?"🟡":state==="need"?"🔴":"🟢";statusEl.dataset.stage=stage;statusEl.dataset.state=state;statusEl.textContent=icon+" "+stage;}
function startWork(stage="חושב ומבצע"){workStarted=Date.now(); if(workTimer)clearInterval(workTimer); statusEl.dataset.stage=stage; statusEl.dataset.state="work"; const tick=()=>{const s=Math.floor((Date.now()-workStarted)/1000); const m=String(Math.floor(s/60)).padStart(2,"0"); const ss=String(s%60).padStart(2,"0"); const icon=statusEl.dataset.state==="wait"?"🟡":statusEl.dataset.state==="need"?"🔴":"🟢"; statusEl.textContent=`${icon} ${statusEl.dataset.stage||"DEAN עובד"} · ${m}:${ss}`;}; tick(); workTimer=setInterval(tick,1000);}
function finishWork(){
  if(workTimer)clearInterval(workTimer);
  workTimer=null;
  statusEl.textContent="✅ הסתיים";
  if(!voiceMode){
    const u=new SpeechSynthesisUtterance("סיימתי");
    u.lang="he-IL";
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  }
}
function failWork(msg){if(workTimer)clearInterval(workTimer); workTimer=null; statusEl.textContent="🔴 "+msg;}

box.scrollTop=box.scrollHeight;

async function pollDueReminders(){
  try{
    const r=await fetch("/api/reminders/due",{credentials:"same-origin"});
    if(!r.ok)return;
    const d=await r.json();
    for(const rem of (d.reminders||[])){
      const t="תזכורת: "+rem.content;
      last=t;
      addMessage("assistant",t);
      if(document.visibilityState==="visible"){
        speakNative(t);
      }
    }
  }catch(e){}
}
setInterval(pollDueReminders,30000);
setTimeout(pollDueReminders,2500);

message.addEventListener("input",()=>{
  message.style.height="auto";
  message.style.height=Math.min(message.scrollHeight,180)+"px";
});

function addMessage(role,text){
  const wrap=document.createElement("div");
  wrap.className="msg "+role;

  const mini=document.createElement("div");
  mini.className="mini";
  mini.textContent=role==="user"?"אתה":"D";

  const bubble=document.createElement("div");
  bubble.className="bubble";
  bubble.textContent=text;

  wrap.append(mini,bubble);
  box.appendChild(wrap);
  box.scrollTop=box.scrollHeight;
}

form.addEventListener("submit",async(e)=>{
  e.preventDefault();
  const text=message.value.trim();
  if(!text)return;

  addMessage("user",text);
  message.value="";
  message.style.height="auto";
  startWork();
  document.getElementById("send").disabled=true;

  try{
    setStage("מעבד את הבקשה","work");
    const controller=new AbortController();
    const timeoutId=setTimeout(()=>controller.abort(),80000);
    const r=await fetch("/api/chat",{
      method:"POST",
      credentials:"same-origin",
      headers:{
        "Content-Type":"application/json",
        "X-CSRF-Token":csrf
      },
      body:JSON.stringify({message:text}),
      signal:controller.signal
    });
    clearTimeout(timeoutId);

    if(r.status===401){
      location.href="/login";
      return;
    }

    const data=await r.json();

    if(!r.ok){
      throw new Error(data.error||"שגיאה");
    }

    setStage("מסיים ושומר בזיכרון","wait");
    last=data.answer;
    addMessage("assistant",last);
    finishWork();
    if(voiceMode){
      speakForConversation(last,()=>setTimeout(startVoiceListening,250));
    }
  }catch(err){
    failWork(err && err.name==="AbortError" ? "הבקשה לקחה יותר מדי זמן. נסה שוב." : "שגיאה: "+err.message);
    message.value=text;
  }finally{
    document.getElementById("send").disabled=false;
  }
});

document.getElementById("copy").onclick=async()=>{
  if(last)await navigator.clipboard.writeText(last);
};

function speakNative(text,onDone){
  stopDeanSpeaking();
  const u=new SpeechSynthesisUtterance(cleanForSpeech(text));
  const he=preferredHebrewVoice();
  if(he)u.voice=he;
  u.lang="he-IL";
  u.rate=1.0;
  u.pitch=1.0;
  u.onend=()=>{if(onDone)onDone();};
  u.onerror=()=>{if(onDone)onDone();};
  // iOS sometimes needs the voices list to refresh before the first utterance.
  try{speechSynthesis.resume();}catch(e){}
  speechSynthesis.speak(u);
}

const readBtn=document.getElementById("read");
let readingReply=false;
readBtn.onclick=()=>{
  if(readingReply){
    stopDeanSpeaking();
    readingReply=false;
    readBtn.textContent="🔊 הקרא";
    return;
  }
  if(!last)return;
  readingReply=true;
  readBtn.textContent="⏹ עצור";
  speakNative(last,()=>{
    readingReply=false;
    readBtn.textContent="🔊 הקרא";
  });
};

function cleanForSpeech(text){
  return (text||"")
    .replace(/[*#_`~>|]/g,"")
    .replace(/\[(.*?)\]\([^)]*\)/g,"$1");
}

function preferredHebrewVoice(){
  const voices=speechSynthesis.getVoices();
  return voices.find(v=>/^he([-_]|$)/i.test(v.lang) && /siri|enhanced|premium|natural/i.test(v.name))
      || voices.find(v=>/^he([-_]|$)/i.test(v.lang))
      || voices.find(v=>/hebrew|עברית/i.test(v.name))
      || null;
}

async function speakForConversation(text,onDone){
  try{
    stopDeanSpeaking();
    activeSpeechController=new AbortController();
    const r=await fetch("/api/speech",{
      method:"POST",
      credentials:"same-origin",
      headers:{
        "Content-Type":"application/json",
        "X-CSRF-Token":csrf
      },
      body:JSON.stringify({text:cleanForSpeech(text)}),
      signal:activeSpeechController.signal
    });
    if(!r.ok)throw new Error("speech");
    const blob=await r.blob();
    activeAudioUrl=URL.createObjectURL(blob);
    const a=new Audio(activeAudioUrl);
    activeHtmlAudio=a;
    a.preload="auto";
    a.onended=()=>{
      activeHtmlAudio=null;
      activeSpeechController=null;
      if(activeAudioUrl){try{URL.revokeObjectURL(activeAudioUrl);}catch(e){} activeAudioUrl=null;}
      if(onDone)onDone();
    };
    a.onerror=()=>{
      activeHtmlAudio=null;
      activeSpeechController=null;
      if(activeAudioUrl){try{URL.revokeObjectURL(activeAudioUrl);}catch(e){} activeAudioUrl=null;}
      speakNative(text,onDone);
    };
    await a.play();
  }catch(e){
    activeSpeechController=null;
    if(e && e.name==="AbortError")return;
    speakNative(text,onDone);
  }
}

function startVoiceListening(){
  if(!voiceMode)return;
  const R=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!R){
    voiceMode=false;
    liveVoiceBtn.textContent="🗣️ שיחה חיה";
    statusEl.textContent="🔴 שיחה חיה לא נתמכת בדפדפן הזה";
    return;
  }
  if(voiceRecognition){ try{voiceRecognition.abort();}catch(e){} }
  const r=new R();
  voiceRecognition=r;
  r.lang="he-IL";
  r.interimResults=false;
  r.continuous=false;
  statusEl.textContent="🎙️ אני שומע...";
  r.onresult=(e)=>{
    const said=e.results[0][0].transcript.trim();
    if(!said)return;
    message.value=said;
    form.requestSubmit();
  };
  r.onerror=(e)=>{
    if(!voiceMode)return;
    if(e.error==="not-allowed" || e.error==="service-not-allowed"){
      voiceMode=false;
      liveVoiceBtn.textContent="🗣️ שיחה חיה";
      statusEl.textContent="🔴 צריך לאשר גישה למיקרופון";
    }else{
      statusEl.textContent="🟡 לא שמעתי, מנסה שוב...";
      setTimeout(startVoiceListening,700);
    }
  };
  r.onend=()=>{
    if(voiceMode && !speechSynthesis.speaking && !document.getElementById("send").disabled){
      setTimeout(startVoiceListening,350);
    }
  };
  r.start();
}

liveVoiceBtn.onclick=()=>{
  if(voiceMode){
    stopLiveConversation();
    return;
  }
  voiceMode=true;
  stopDeanSpeaking();
  if(voiceRecognition){ try{voiceRecognition.abort();}catch(e){} voiceRecognition=null; }
  if(voiceMode){
    liveVoiceBtn.textContent="⏹ סיים שיחה";
    startVoiceListening();
  }
};

document.getElementById("mic").onclick=()=>{
  const R=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!R){
    alert("הכתבה קולית לא זמינה בדפדפן הזה כרגע.");
    return;
  }
  const r=new R();
  r.lang="he-IL";
  r.onresult=(e)=>{
    message.value=e.results[0][0].transcript;
    message.focus();
  };
  r.start();
};

document.getElementById("logout").onclick=async()=>{
  await fetch("/api/logout",{
    method:"POST",
    credentials:"same-origin",
    headers:{"X-CSRF-Token":csrf}
  });
  location.href="/login";
};
</script>
</body>
</html>
"""


SHARED_BROWSER_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>DEAN Browser</title>
<style>
*{box-sizing:border-box}
body{margin:0;color:#eef6ff;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",sans-serif;overflow:hidden;background:
radial-gradient(circle at 15% 0%,rgba(43,210,255,.16),transparent 34%),
radial-gradient(circle at 90% 100%,rgba(121,92,255,.14),transparent 32%),
#06080d}
.topbar{display:flex;gap:8px;padding:10px 12px;background:rgba(10,14,22,.78);backdrop-filter:blur(22px);align-items:center;border-bottom:1px solid rgba(255,255,255,.08);box-shadow:0 12px 35px rgba(0,0,0,.25)}
input{font-size:16px;padding:11px 14px;border-radius:14px;border:1px solid rgba(255,255,255,.09);background:rgba(255,255,255,.06);color:#f5f9ff;outline:none;box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}
#url{flex:1;direction:ltr;text-align:left}
button{font-size:15px;padding:10px 14px;border:1px solid rgba(255,255,255,.10);border-radius:13px;background:linear-gradient(180deg,rgba(255,255,255,.12),rgba(255,255,255,.05));color:#eef6ff;box-shadow:0 8px 24px rgba(0,0,0,.18)}
.main{display:grid;grid-template-columns:1fr;height:calc(100vh - 62px)}
.browserPane{min-width:0;display:flex;flex-direction:column;background:transparent;padding:10px}
.typebar{display:flex;gap:8px;padding:8px 0}
#typeText{flex:1}
.small{font-size:12px;color:#8fa6bf;padding:4px 4px 8px}
.stage{display:flex;justify-content:center;align-items:flex-start;background:#0b0f16;min-height:0;overflow:auto;flex:1;border:1px solid rgba(255,255,255,.08);border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.38);overflow:hidden}
#screen{width:100%;max-width:1024px;height:auto;display:block;touch-action:none;background:#fff;border-radius:18px;user-select:none;-webkit-user-select:none}
.chatPane{position:fixed;right:18px;bottom:18px;width:290px;height:340px;z-index:10000;background:rgba(10,14,22,.94);backdrop-filter:blur(22px);display:none;flex-direction:column;min-width:0;border:1px solid rgba(100,220,255,.22);border-radius:22px;box-shadow:0 24px 70px rgba(0,0,0,.55),0 0 35px rgba(54,194,255,.10);overflow:hidden}
.chatPane.open{display:flex}
.chatHead{padding:10px 12px;border-bottom:1px solid #2a2d33;font-weight:700;display:flex;justify-content:space-between;align-items:center;cursor:move;touch-action:none}
.chatMsgs{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 12px;border-radius:14px;white-space:pre-wrap;line-height:1.35}
.msg.user{background:#234c7a;align-self:flex-start}
.msg.assistant{background:#24272e;align-self:flex-end}
.chatForm{display:flex;gap:8px;padding:10px;border-top:1px solid #2a2d33;align-items:center}
#chatInput{flex:1;min-width:0}
#chatMic{width:42px;height:42px;padding:0;border-radius:50%;font-size:18px}
#chatToggle{display:grid;place-items:center;position:fixed;right:22px;bottom:22px;z-index:9999;width:58px;height:58px;padding:0;border-radius:50%;font-size:0;background:linear-gradient(135deg,#5ce1ff,#7b61ff);box-shadow:0 12px 34px rgba(75,174,255,.42);border:1px solid rgba(255,255,255,.25)}
#chatToggle::after{content:"D";font-size:21px;font-weight:900;color:#061019}
@media(max-width:900px){
  .main{grid-template-columns:1fr}
}
@media(max-width:600px){
  .chatPane{width:270px;height:320px;right:10px;bottom:10px}
}
</style>
</head>
<body>
<div class="topbar">
<input id="url" value="about:blank" autocomplete="off" autocapitalize="none">
<button id="go">פתח</button>
<button id="reload">רענן</button>
</div>

<div class="main">
  <div class="browserPane">
    <div class="typebar">
      <input id="typeText" placeholder="כתוב בדפדפן...">
      <button id="typeBtn">הקלד</button>
      <button id="enterBtn">Enter</button>
    </div>
    <div class="small" id="status">DEAN Browser · מתחבר...</div>
    <div class="stage"><img id="screen" alt="הדפדפן המשותף"></div>
  </div>

  <aside class="chatPane" id="chatPane">
    <div class="chatHead">
      <span>DEAN</span>
      <button id="closeChat">×</button>
    </div>
    <div class="chatMsgs" id="chatMsgs"></div>
    <form class="chatForm" id="chatForm">
      <button type="button" id="chatMic" title="דבר עם דין">🎙️</button>
      <input id="chatInput" placeholder="דבר עם דין..." autocomplete="off">
      <button type="submit">שלח</button>
    </form>
  </aside>
</div>
<button id="chatToggle" title="דבר עם דין" aria-label="דבר עם דין">D</button>

<script>
const csrf={{ csrf|tojson }};
const img=document.getElementById("screen");
const status=document.getElementById("status");
const pane=document.getElementById("chatPane");
const msgs=document.getElementById("chatMsgs");

async function pollStatus(){
  try{
    const r=await fetch("/api/browser/status",{credentials:"same-origin"});
    const d=await r.json();
    if(d.viewer_ready){status.textContent="DEAN Browser · מחובר";}
    else if(d.connected){status.textContent="הדפדפן מחובר, מחכה לתמונה חדשה...";}
    else{status.textContent="הדפדפן מתחבר...";}
    const urlBox=document.getElementById("url");
    if(d.current_url && document.activeElement!==urlBox){
      urlBox.value=d.current_url;
    }
  }catch(e){ status.textContent="הדפדפן מנסה להתחבר..."; }
}
function refresh(){ img.src="/api/browser/frame?t="+Date.now(); }
setInterval(refresh,700); setInterval(pollStatus,1200); refresh(); pollStatus();

let screenPointer=null;
img.addEventListener("pointerdown",e=>{
  const r=img.getBoundingClientRect();
  screenPointer={
    id:e.pointerId,
    startX:e.clientX,
    startY:e.clientY,
    lastX:e.clientX,
    lastY:e.clientY,
    remoteX:(e.clientX-r.left)*(1024/r.width),
    remoteY:(e.clientY-r.top)*(700/r.height),
    moved:false
  };
  try{img.setPointerCapture(e.pointerId);}catch(_){}
  e.preventDefault();
});
img.addEventListener("pointermove",e=>{
  if(!screenPointer||screenPointer.id!==e.pointerId)return;
  const dx=e.clientX-screenPointer.lastX;
  const dy=e.clientY-screenPointer.lastY;
  if(Math.hypot(e.clientX-screenPointer.startX,e.clientY-screenPointer.startY)>8){
    screenPointer.moved=true;
  }
  screenPointer.lastX=e.clientX;
  screenPointer.lastY=e.clientY;
  e.preventDefault();
});
img.addEventListener("pointerup",async e=>{
  if(!screenPointer||screenPointer.id!==e.pointerId)return;
  const p=screenPointer;
  screenPointer=null;
  const r=img.getBoundingClientRect();
  const x=(e.clientX-r.left)*(1024/r.width);
  const y=(e.clientY-r.top)*(700/r.height);
  const totalDx=e.clientX-p.startX;
  const totalDy=e.clientY-p.startY;
  if(p.moved){
    // Drag the page naturally: finger up => page scrolls down.
    await fetch("/api/browser/scroll",{
      method:"POST",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:JSON.stringify({
        deltaX:-totalDx*(1024/r.width),
        deltaY:-totalDy*(700/r.height),
        x:p.remoteX,
        y:p.remoteY
      })
    });
    setTimeout(refresh,120);
  }else{
    await fetch("/api/browser/click",{
      method:"POST",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:JSON.stringify({x,y})
    });
  }
  e.preventDefault();
});
img.addEventListener("pointercancel",()=>{screenPointer=null;});
document.getElementById("go").onclick=async()=>{
  const url=document.getElementById("url").value.trim();
  await fetch("/api/browser/navigate",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({url})});
};
document.getElementById("reload").onclick=()=>refresh();
document.getElementById("typeBtn").onclick=async()=>{
  const text=document.getElementById("typeText").value;
  await fetch("/api/browser/type",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({text})});
};
document.getElementById("enterBtn").onclick=async()=>{
  await fetch("/api/browser/key",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({key:"Enter"})});
};
img.onerror=()=>{status.textContent="הדפדפן מנסה להתחבר...";};
img.onload=()=>{status.textContent="DEAN Browser · מחובר";};

document.getElementById("chatToggle").onclick=()=>pane.classList.add("open");
document.getElementById("closeChat").onclick=()=>pane.classList.remove("open");

// Draggable floating DEAN window for iPad.
const dragHead=pane.querySelector(".chatHead");
let dragging=false, startX=0, startY=0, startLeft=0, startTop=0;
dragHead.addEventListener("pointerdown",e=>{
  if(e.target.closest("button")) return;
  dragging=true;
  dragHead.setPointerCapture(e.pointerId);
  const r=pane.getBoundingClientRect();
  startX=e.clientX; startY=e.clientY; startLeft=r.left; startTop=r.top;
  pane.style.right="auto"; pane.style.bottom="auto";
  pane.style.left=startLeft+"px"; pane.style.top=startTop+"px";
});
dragHead.addEventListener("pointermove",e=>{
  if(!dragging)return;
  const maxL=Math.max(0,window.innerWidth-pane.offsetWidth);
  const maxT=Math.max(62,window.innerHeight-pane.offsetHeight);
  const left=Math.min(maxL,Math.max(0,startLeft+(e.clientX-startX)));
  const top=Math.min(maxT,Math.max(62,startTop+(e.clientY-startY)));
  pane.style.left=left+"px"; pane.style.top=top+"px";
});
dragHead.addEventListener("pointerup",()=>{dragging=false;});
dragHead.addEventListener("pointercancel",()=>{dragging=false;});

function addMsg(role,text){
  const d=document.createElement("div");
  d.className="msg "+role;
  d.textContent=text;
  msgs.appendChild(d);
  msgs.scrollTop=msgs.scrollHeight;
}
async function sendDeanMessage(text){
  text=(text||"").trim();
  if(!text)return;
  addMsg("user",text);
  status.textContent="DEAN מבצע...";
  try{
    const r=await fetch("/api/chat",{
      method:"POST",
      credentials:"same-origin",
      headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:JSON.stringify({message:text})
    });
    const data=await r.json();
    addMsg("assistant",data.answer||data.error||"לא התקבלה תשובה");
    setTimeout(refresh,250);
    setTimeout(refresh,900);
    status.textContent="DEAN Browser · מחובר";
  }catch(e){
    addMsg("assistant","שגיאה בחיבור לדין");
    status.textContent="שגיאה בחיבור לדין";
  }
}

document.getElementById("chatForm").addEventListener("submit",async e=>{
  e.preventDefault();
  const input=document.getElementById("chatInput");
  const text=input.value.trim();
  input.value="";
  await sendDeanMessage(text);
});

document.getElementById("chatMic").onclick=()=>{
  const R=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!R){
    addMsg("assistant","הכתבה קולית לא זמינה בדפדפן הזה.");
    return;
  }
  const r=new R();
  r.lang="he-IL";
  r.interimResults=false;
  r.continuous=false;
  document.getElementById("chatMic").textContent="●";
  status.textContent="DEAN מקשיב...";
  r.onresult=async e=>{
    const said=e.results[0][0].transcript.trim();
    if(said) await sendDeanMessage(said);
  };
  r.onerror=()=>{status.textContent="לא שמעתי. נסה שוב.";};
  r.onend=()=>{document.getElementById("chatMic").textContent="🎙️";};
  r.start();
};
</script>
</body>
</html>
"""

@app.get("/browser-start")
def browser_start():
    return """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DEAN Browser</title><style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#0b0f16;color:#eef6ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}.box{text-align:center}.d{width:92px;height:92px;border-radius:28px;display:grid;place-items:center;margin:0 auto 22px;background:linear-gradient(135deg,#5ce1ff,#7b61ff);color:#061019;font-weight:900;font-size:38px;box-shadow:0 18px 60px rgba(75,174,255,.28)}h1{margin:0 0 10px;font-size:34px}p{margin:0;color:#9eb2c8;font-size:18px}</style></head><body><div class="box"><div class="d">D</div><h1>DEAN Browser</h1><p>מחובר ומוכן לעבודה</p></div></body></html>""", 200, {"Content-Type":"text/html; charset=utf-8", "Cache-Control":"no-store"}

@app.get("/browser")
@require_login
def shared_browser():
    threading.Thread(target=browser_wait_until_ready, args=(25,), daemon=True).start()
    return render_template_string(SHARED_BROWSER_HTML, csrf=csrf_token())

@app.get("/api/browser/status")
@require_login
def api_browser_status():
    return jsonify(persistent_browser_status())

@app.get("/api/browser/frame")
@require_login
def api_browser_frame():
    frame = persistent_browser_frame()
    if not frame:
        return Response(status=503)
    return Response(frame, mimetype="image/jpeg", headers={"Cache-Control":"no-store"})

@app.post("/api/browser/navigate")
@require_csrf
def api_browser_navigate():
    data=request.get_json(silent=True) or {}
    ok=persistent_browser_navigate(data.get("url",""))
    return jsonify(ok=bool(ok)), (200 if ok else 503)

@app.post("/api/browser/click")
@require_csrf
def api_browser_click():
    data=request.get_json(silent=True) or {}
    try:
        ok=persistent_browser_click(data.get("x"), data.get("y"))
    except Exception:
        ok=False
    return jsonify(ok=bool(ok)), (200 if ok else 503)

@app.post("/api/browser/scroll")
@require_csrf
def api_browser_scroll():
    data=request.get_json(silent=True) or {}
    try:
        ok=persistent_browser_scroll(
            data.get("deltaX",0),
            data.get("deltaY",0),
            data.get("x",512),
            data.get("y",350),
        )
    except Exception:
        ok=False
    return jsonify(ok=bool(ok)), (200 if ok else 503)

@app.post("/api/browser/type")
@require_csrf
def api_browser_type():
    data=request.get_json(silent=True) or {}
    ok=persistent_browser_type(data.get("text",""))
    return jsonify(ok=bool(ok)), (200 if ok else 503)

@app.post("/api/browser/key")
@require_csrf
def api_browser_key():
    data=request.get_json(silent=True) or {}
    ok=persistent_browser_key(data.get("key","Enter"))
    return jsonify(ok=bool(ok)), (200 if ok else 503)

@app.post("/api/speech")
@require_login
def api_speech():
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not secrets.compare_digest(supplied, csrf_token()):
        abort(403)
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(error="חסר טקסט להקראה"), 400
    try:
        audio = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="cedar",
            input=text[:4096],
            instructions="You are the spoken voice of DEAN, Beniel's personal AI. Speak Hebrew exactly like DEAN's chat personality: everyday Israeli Hebrew, direct, warm, relaxed and natural, with light humor or playful sarcasm only when the text calls for it. Never sound like an announcer, call center, robot or formal assistant. Preserve the meaning and emotional tone of the written reply. Use natural pauses, Israeli conversational pacing, and human intonation."
        )
        return Response(audio.content, mimetype="audio/mpeg")
    except Exception:
        app.logger.exception("Speech generation failed")
        return jsonify(error="שגיאה ביצירת קול"), 500


def save_oauth_token(provider, access_token, refresh_token="", open_id="", scope="", expires_at=0):
    with get_db() as con:
        if DATABASE_URL:
            con.execute("""INSERT INTO oauth_tokens(provider,access_token,refresh_token,open_id,scope,expires_at,updated)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(provider) DO UPDATE SET access_token=EXCLUDED.access_token,
                refresh_token=EXCLUDED.refresh_token,open_id=EXCLUDED.open_id,scope=EXCLUDED.scope,
                expires_at=EXCLUDED.expires_at,updated=EXCLUDED.updated""",
                (provider,access_token,refresh_token,open_id,scope,expires_at,utc_now()))
        else:
            con.execute("""INSERT INTO oauth_tokens(provider,access_token,refresh_token,open_id,scope,expires_at,updated)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(provider) DO UPDATE SET access_token=excluded.access_token,
                refresh_token=excluded.refresh_token,open_id=excluded.open_id,scope=excluded.scope,
                expires_at=excluded.expires_at,updated=excluded.updated""",
                (provider,access_token,refresh_token,open_id,scope,expires_at,utc_now()))

def oauth_status(provider):
    with get_db() as con:
        row=con.execute(db_sql("SELECT provider,open_id,scope,expires_at,updated FROM oauth_tokens WHERE provider=?"),(provider,)).fetchone()
    return dict(row) if row else None

@app.get("/tiktok/connect")
@require_login
def tiktok_connect():
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        return "TikTok app credentials are not configured yet.", 503
    state=secrets.token_urlsafe(32)
    session["tiktok_oauth_state"]=state
    params={
        "client_key":TIKTOK_CLIENT_KEY,
        "response_type":"code",
        "scope":TIKTOK_SCOPES,
        "redirect_uri":TIKTOK_REDIRECT_URI,
        "state":state,
    }
    return redirect("https://www.tiktok.com/v2/auth/authorize/?"+urlencode(params))

@app.get("/tiktok/callback")
def tiktok_callback():
    if request.args.get("error"):
        return "TikTok authorization was not completed.", 400
    state=request.args.get("state","")
    expected=session.pop("tiktok_oauth_state",None)
    if not expected or not secrets.compare_digest(state,expected):
        return "Invalid TikTok authorization state.", 400
    code=request.args.get("code","")
    if not code:
        return "Missing TikTok authorization code.", 400
    r=requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type":"application/x-www-form-urlencoded"},
        data={
            "client_key":TIKTOK_CLIENT_KEY,
            "client_secret":TIKTOK_CLIENT_SECRET,
            "code":code,
            "grant_type":"authorization_code",
            "redirect_uri":TIKTOK_REDIRECT_URI,
        },
        timeout=20,
    )
    data=r.json() if r.content else {}
    if not r.ok or not data.get("access_token"):
        app.logger.error("TikTok token exchange failed: %s", data)
        return "TikTok authorization failed.", 502
    expires_at=time.time()+float(data.get("expires_in") or 0)
    save_oauth_token(
        "tiktok",
        data.get("access_token",""),
        data.get("refresh_token",""),
        data.get("open_id",""),
        data.get("scope",""),
        expires_at,
    )
    return "TikTok connected to Beniyl successfully. You can return to DEAN.", 200

@app.get("/api/tiktok/status")
@require_login
def api_tiktok_status():
    st=oauth_status("tiktok")
    return jsonify(
        configured=bool(TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET),
        connected=bool(st),
        scope=(st or {}).get("scope",""),
        updated=(st or {}).get("updated",""),
    )

@app.get("/api/steel/status")
@require_login
def api_steel_status():
    raw = os.getenv("STEEL_API_KEY", "")
    normalized = __import__("steel_client").api_key()
    check = steel_validate_key()
    return jsonify(
        configured=steel_configured(),
        raw_present=bool(raw),
        raw_length=len(raw),
        normalized_length=len(normalized),
        starts_with_ste=normalized.startswith("ste-"),
        authenticated=check.get("authenticated", False),
        steel_status_code=check.get("status_code"),
        steel_error=str(check.get("error", ""))[:200] if check.get("error") else "",
    )

@app.post("/api/steel/session")
@require_csrf
def api_steel_session():
    result=steel_create_session()
    return jsonify(result), (200 if result.get("ok") else 502)

@app.get("/health")
def health():
    try:
        with get_db() as con:
            con.execute("SELECT 1").fetchone()
        return jsonify(
            status="ok",
            database="postgres" if DATABASE_URL else "sqlite",
            memory_persistent=bool(DATABASE_URL),
            browser_configured=bool(os.getenv("BROWSERLESS_BASE_URL") and os.getenv("BROWSERLESS_API_KEY")),
            persistent_browser=persistent_browser_status(),
            reminders_ok=True,
            speech_backend="openai_tts",
        )
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify(status="error", database="postgres" if DATABASE_URL else "sqlite"), 503

@app.get("/login")
def login():
    next_path = request.args.get("next", "")
    if not (next_path.startswith("/") and not next_path.startswith("//")):
        next_path = url_for("home")
    if is_logged_in():
        return redirect(next_path)
    return render_template_string(
        LOGIN_HTML,
        csrf=csrf_token(),
        error=None,
        next_path=next_path
    )

@app.post("/login")
def login_post():
    supplied = request.form.get("csrf", "")
    if not supplied or not secrets.compare_digest(supplied, csrf_token()):
        abort(403)

    next_path = request.form.get("next", "")
    if not (next_path.startswith("/") and not next_path.startswith("//")):
        next_path = url_for("home")

    ip = (
        request.headers.get("X-Forwarded-For")
        or request.remote_addr
        or "unknown"
    ).split(",")[0].strip()

    with get_db() as con:
        failures = con.execute(
            db_sql("""
            SELECT COUNT(*) AS c
            FROM login_attempts
            WHERE ip=? AND ok=0 AND created>?
            """),
            (ip, time.time() - 900)
        ).fetchone()["c"]

    if failures >= 10:
        return render_template_string(
            LOGIN_HTML,
            csrf=csrf_token(),
            error="יותר מדי ניסיונות. נסה שוב בעוד כמה דקות.",
            next_path=next_path
        ), 429

    password = request.form.get("password", "")
    ok = secrets.compare_digest(password, DEAN_PASSWORD)

    with get_db() as con:
        con.execute(
            db_sql("INSERT INTO login_attempts(ip,ok,created) VALUES(?,?,?)"),
            (ip, int(ok), time.time())
        )

    if not ok:
        return render_template_string(
            LOGIN_HTML,
            csrf=csrf_token(),
            error="סיסמה שגויה",
            next_path=next_path
        ), 401

    session.clear()
    session.permanent = True
    session["authenticated"] = True
    session["csrf"] = secrets.token_urlsafe(32)

    return redirect(next_path)

@app.get("/")
@require_login
def home():
    messages = load_history(80)
    memories = list_memories(100)
    tasks = list_tasks(100)

    last_answer = next(
        (
            m["content"]
            for m in reversed(messages)
            if m["role"] == "assistant"
        ),
        ""
    )

    return render_template_string(
        APP_HTML,
        messages=messages,
        memories=memories,
        tasks=tasks,
        csrf=csrf_token(),
        last_answer=last_answer
    )

@app.get("/api/reminders/due")
@require_login
def api_due_reminders():
    rows=due_reminders(10)
    if rows:
        mark_reminders_notified([r["id"] for r in rows])
    return jsonify(reminders=rows)

@app.get("/api/version")
@require_login
def api_version():
    rel = latest_release()
    return jsonify(
        version=DEAN_VERSION,
        release=rel,
        database="postgres" if DATABASE_URL else "sqlite",
        memory_persistent=bool(DATABASE_URL),
    )

@app.post("/api/logout")
@require_csrf
def logout():
    session.clear()
    return jsonify(ok=True)

@app.post("/api/chat")
@require_csrf
def chat():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify(error="הודעה ריקה"), 400

    if len(message) > 6000:
        return jsonify(error="ההודעה ארוכה מדי"), 400

    local_answer = maybe_handle_local_command(message)

    if local_answer is not None:
        save_message("user", message)
        save_message("assistant", local_answer)
        return jsonify(answer=local_answer)

    try:
        answer = ask_dean(message)
    except Exception:
        app.logger.exception("DEAN request failed")
        return jsonify(
            error="DEAN לא הצליח להשלים את הבקשה כרגע."
        ), 502

    due_now = due_reminders(10)
    if due_now:
        reminder_lines = [f"תזכורת: {r['content']}" for r in due_now]
        answer = (answer.rstrip() + "\n\n" + "\n".join(reminder_lines)).strip()
        mark_reminders_notified([r["id"] for r in due_now])

    save_message("user", message)
    save_message("assistant", answer)
    # Learning must never hold up the user's answer. Extract durable memory in the background.
    threading.Thread(
        target=auto_learn_from_turn,
        args=(message, answer),
        daemon=True,
        name="dean-memory-learner",
    ).start()

    return jsonify(answer=answer)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
