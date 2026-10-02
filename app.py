import os
import sqlite3
import secrets
import time
import threading
import requests
import re
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlencode

from flask import (
    Flask, request, session, redirect, url_for,
    jsonify, render_template_string, abort, Response
)
from openai import OpenAI
from steel_client import configured as steel_configured, create_session as steel_create_session

app = Flask(__name__)

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
            CREATE TABLE IF NOT EXISTS login_attempts(
                id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, ok INTEGER NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS action_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS releases(
                id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL UNIQUE, notes TEXT NOT NULL, created TEXT NOT NULL);
            """)
        con.commit()

init_db()

CURRENT_RELEASE_NOTES = """זיכרון קבוע ב-Postgres וחיפוש הקשר; למידה אוטומטית ברקע; משימות ואישורים; קול ושיחה חיה; חיווי עבודה; כלי גלישה אמיתי דרך TinyFish עם בדיקת חיבור ב-health."""
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
            return redirect(url_for("login"))
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
        existing = "\\n".join(f"- {m['content']}" for m in list_memories(120))
        prompt = f"""חלץ מהשיחה רק עובדות יציבות ושימושיות על בניאל שכדאי לזכור לשיחות עתידיות:
העדפות, מטרות, קשרים משפחתיים, שגרה, פרויקטים, החלטות קבועות ודפוסים חשובים.
אל תשמור סיסמאות, מפתחות, מספרי כרטיס, קודים, פרטי התחברות, מידע רגעי או ניחושים.
אל תשמור מידע רגיש מאוד אלא אם בניאל ביקש במפורש לזכור אותו.
אל תחזור על עובדה שכבר קיימת.
החזר שורה אחת לכל זיכרון חדש, בלי מספור ובלי הסבר. אם אין מה לשמור החזר NONE.

זיכרונות קיימים:
{existing}

בניאל: {user_text}
DEAN: {assistant_text}"""
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

def maybe_handle_local_command(message):
    text = message.strip()

    if text in {"פתח לי דפדפן משותף","פתח דפדפן משותף","תפתח לי דפדפן משותף"}:
        result = steel_create_session()
        if not result.get("ok"):
            return "לא הצלחתי לפתוח דפדפן משותף: " + str(result.get("error") or result)
        url = result.get("debug_url")
        if not url:
            return "הדפדפן נפתח אבל לא התקבל קישור Live View."
        return "פתחתי דפדפן משותף. הנה הקישור החי:\n" + url

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

    memory_text = "\\n".join(f"- {m['content']}" for m in memories) or "- אין עדיין"
    task_text = "\\n".join(
        f"- {'בוצע' if t['done'] else 'פתוח'}: {t['content']}" for t in tasks
    ) or "- אין כרגע"
    approval_text = "\\n".join(
        f"- {r['id']}: {r['action']}" for r in approvals
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

כלל ביצוע:
- לפני פעולה חיצונית רגישה, צור בקשת אישור ברורה ואל תטען שהפעולה בוצעה לפני שיש כלי אמיתי ותוצאה מאומתת.
- כשאין עדיין כלי שמסוגל לבצע פעולה, אמור במדויק שהכלי עדיין לא מחובר במקום להעמיד פנים שביצעת.
- כלי browser_run הוא כלי גלישה אמיתי של DEAN דרך TinyFish והוא מחובר כאשר השרת הגדיר TINYFISH_API_KEY. כשבניאל מבקש לפתוח אתר, לנווט, ללחוץ או למלא טופס, השתמש ב-browser_run בפועל; אל תגיד שאין כלי גלישה בלי שניסית את הכלי וקיבלת שגיאה.\n- כאשר כלי ביצוע מחובר, פעל כמתזמר: בחר את הכלי המתאים, בצע, בדוק תוצאה, תקן אם נכשל והמשך עד השלמת המטרה.
""".strip()

def run_browser_agent(url, goal):
    """Run a real TinyFish web agent. Requires a server-side key; never expose it to the model or browser UI."""
    if not TINYFISH_API_KEY:
        return {"ok": False, "error": "browser_not_configured"}
    try:
        r = requests.post(
            "https://agent.tinyfish.ai/v1/automation/run",
            headers={"X-API-Key": TINYFISH_API_KEY, "Content-Type": "application/json"},
            json={"url": url, "goal": goal, "browser_profile": "stealth"},
            timeout=90,
        )
        data = r.json() if r.content else {}
        if not r.ok:
            return {"ok": False, "status_code": r.status_code, "error": data}
        return {"ok": True, "run": data}
    except Exception as e:
        app.logger.exception("TinyFish browser run failed")
        return {"ok": False, "error": str(e)}

def needs_browser(message):
    text = str(message).lower()
    action_words = (
        "פתח אתר","כנס לאתר","תיכנס לאתר","תפתח אתר","לחץ על","תלחץ על",
        "מלא טופס","תמלא טופס","תתחבר ל","תיכנס ל","תפרסם","תעלה פוסט",
        "תנווט","נווט ל","בדוק באתר","תבדוק באתר","https://","http://"
    )
    return any(x in text for x in action_words)

def ask_dean(message):
    history = load_relevant_history(message, recent_limit=10, scan_limit=180, max_extra=6)
    tools = []
    if needs_browser(message):
        tools.append({
            "type": "function",
            "name": "browser_run",
            "description": "Use DEAN's real browser only for an explicit user-requested website action. Never claim success unless the returned result confirms it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The starting https URL."},
                    "goal": {"type": "string", "description": "Precise goal for the browser agent. Do not include passwords or secret keys."}
                },
                "required": ["url", "goal"],
                "additionalProperties": False
            },
            "strict": True
        })
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
let activeSpeechController=null;
const liveVoiceBtn=document.getElementById("liveVoice");
const stopSpeechBtn=document.getElementById("stopSpeech");

function stopDeanSpeaking(){
  if(activeSpeechController){try{activeSpeechController.abort();}catch(e){} activeSpeechController=null;}
  if(activeVoiceSource){try{activeVoiceSource.stop(0);}catch(e){} activeVoiceSource=null;}
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
  speakForConversation(last,()=>{
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
    if(!voiceAudioContext){
      voiceAudioContext=new (window.AudioContext||window.webkitAudioContext)();
    }
    if(voiceAudioContext.state==="suspended")await voiceAudioContext.resume();
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
    const buf=await r.arrayBuffer();
    const decoded=await voiceAudioContext.decodeAudioData(buf.slice(0));
    const src=voiceAudioContext.createBufferSource();
    activeVoiceSource=src;
    src.buffer=decoded;
    src.connect(voiceAudioContext.destination);
    src.onended=()=>{ activeVoiceSource=null; activeSpeechController=null; if(onDone)onDone(); };
    src.start(0);
  }catch(e){
    activeSpeechController=null;
    if(e && e.name==="AbortError")return;
    speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(cleanForSpeech(text));
    const he=preferredHebrewVoice();
    if(he)u.voice=he;
    u.lang="he-IL";
    u.rate=1.02;
    u.onend=()=>{ if(onDone)onDone(); };
    u.onerror=()=>{ if(onDone)onDone(); };
    speechSynthesis.speak(u);
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
    if(!voiceAudioContext){
      voiceAudioContext=new (window.AudioContext||window.webkitAudioContext)();
    }
    voiceAudioContext.resume().catch(()=>{});
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
    return jsonify(configured=steel_configured())

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
        return jsonify(status="ok", database="postgres" if DATABASE_URL else "sqlite", browser_configured=bool(TINYFISH_API_KEY))
    except Exception:
        app.logger.exception("Database health check failed")
        return jsonify(status="error", database="postgres" if DATABASE_URL else "sqlite"), 503

@app.get("/login")
def login():
    if is_logged_in():
        return redirect(url_for("home"))
    return render_template_string(
        LOGIN_HTML,
        csrf=csrf_token(),
        error=None
    )

@app.post("/login")
def login_post():
    supplied = request.form.get("csrf", "")
    if not supplied or not secrets.compare_digest(supplied, csrf_token()):
        abort(403)

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
            error="יותר מדי ניסיונות. נסה שוב בעוד כמה דקות."
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
            error="סיסמה שגויה"
        ), 401

    session.clear()
    session.permanent = True
    session["authenticated"] = True
    session["csrf"] = secrets.token_urlsafe(32)

    return redirect(url_for("home"))

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
