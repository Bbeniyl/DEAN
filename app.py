import os
import sqlite3
import secrets
import time
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for,
    jsonify, render_template_string, abort
)
from openai import OpenAI

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DEAN_PASSWORD = os.getenv("DEAN_PASSWORD", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-sol").strip()
DB_PATH = os.getenv("DB_PATH", "/tmp/dean.sqlite3").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

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
            """)
        con.commit()

init_db()

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

def list_memories(limit=100):
    with get_db() as con:
        rows = con.execute(
            db_sql("SELECT id,content,created FROM memories ORDER BY id DESC LIMIT ?"),
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]

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

def maybe_handle_local_command(message):
    text = message.strip()

    prefixes = ["תזכור ", "תזכרי ", "תשמור ", "תשמרי ", "שמור ", "שמרי "]
    for prefix in prefixes:
        if text.startswith(prefix):
            content = text[len(prefix):].strip()
            if content:
                save_memory(content)
                return f"שמרתי בזיכרון: {content}"

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

    if text in {"/tasks", "משימות", "מה המשימות שלי"}:
        tasks = list_tasks(50)
        if not tasks:
            return "אין כרגע משימות."
        return "המשימות שלך:\\n" + "\\n".join(
            f"{'✅' if t['done'] else '⬜'} {t['id']}. {t['content']}" for t in tasks
        )

    return None

def dean_instructions():
    memories = list_memories(80)
    tasks = list_tasks(80)

    memory_text = "\\n".join(f"- {m['content']}" for m in memories) or "- אין עדיין"
    task_text = "\\n".join(
        f"- {'בוצע' if t['done'] else 'פתוח'}: {t['content']}" for t in tasks
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
- דבר בעברית מדוברת של יום-יום, כמו שיחה אמיתית בין שני אנשים שמכירים טוב. אל תישמע כמו AI, רובוט, מוקד שירות, מאמן, מטפל או מסמך רשמי.\n- התשובה צריכה להרגיש כמו דיבור טבעי: קצרה כשאפשר, זורמת, ישירה, עם מילים פשוטות. אל תפתח כל תשובה בשם בניאל ואל תסכם כל דבר בצורה רשמית.\n- אל תשתמש בביטויים מלאכותיים כמו "אני כאן כדי", "להלן", "בהחלט", "אשמח לסייע", "בוא נצלול", "חשוב לציין", "אני מבין את התסכול", אלא אם הם באמת טבעיים בהקשר.\n- אל תחזור על השאלה של בניאל ואל תסביר דברים מובנים מאליהם. אם הוא שואל משהו פשוט, תענה פשוט.\n- אפשר לדבר בחום, בהומור קל ובחברותיות כשזה מתאים, אבל בלי התלהבות מזויפת, בלי חנופה ובלי טון מרוחק.\n- אם יש כמה צעדים, תן אותם כמו שאדם היה אומר אותם בשיחה, לא כמו מדריך רשמי.\n- אל תשתמש בסימוני Markdown כמו כוכביות, סולמיות, קווים תחתיים או הדגשות בתשובות לבניאל. כתוב טקסט נקי שמתאים להקראה בקול.
- התאם את אורך התשובה לצורך. אל תעמיס סתם.
- התייחס להיסטוריית השיחה ולזיכרונות המצורפים ולא כאילו זו פגישה ראשונה.
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
""".strip()

def ask_dean(message):
    history = load_history(12)
    response = client.responses.create(
        model=MODEL,
        instructions=dean_instructions(),
        input=history + [{"role": "user", "content": message}],
        tools=[{"type": "web_search"}],
        reasoning={"effort": "low"},
        max_output_tokens=1200,
    )
    text = (response.output_text or "").strip()
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
.main{min-width:0;display:grid;grid-template-rows:72px 1fr auto}.top{border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 24px;background:rgba(7,11,19,.48);backdrop-filter:blur(18px)}
.title{display:flex;align-items:center;gap:11px}.title .avatar{width:39px;height:39px;border-radius:13px;font-size:15px}.title small{color:var(--muted)}
.chat{overflow:auto;padding:26px clamp(12px,5vw,70px);scroll-behavior:smooth}.welcome{max-width:760px;margin:10vh auto 44px;text-align:center}.big{width:82px;height:82px;border-radius:27px;margin:auto;display:grid;place-items:center;background:linear-gradient(135deg,var(--a),var(--b));color:#041018;font-size:34px;font-weight:900;box-shadow:0 18px 55px rgba(88,169,255,.22)}
.welcome h2{font-size:36px;margin:22px 0 8px}.welcome p{color:var(--muted);font-size:16px}
.msg{max-width:840px;margin:0 auto 17px;display:flex;gap:11px;align-items:flex-start}.mini{width:33px;height:33px;border-radius:11px;display:grid;place-items:center;flex:none;font-size:11px;font-weight:800}.user .mini{background:#26344c}.assistant .mini{background:linear-gradient(135deg,var(--a),var(--b));color:#041018}
.bubble{padding:14px 16px;border-radius:20px;max-width:min(760px,84vw);white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.55;border:1px solid var(--line)}.user .bubble{background:#1a2941}.assistant .bubble{background:rgba(16,24,41,.82)}
.bottom{padding:12px clamp(10px,5vw,70px) 20px;background:linear-gradient(transparent,var(--bg) 30%)}.compose{max-width:840px;margin:auto;position:relative}textarea{width:100%;resize:none;min-height:60px;max-height:180px;padding:17px 62px 17px 16px;border:1px solid rgba(255,255,255,.12);border-radius:21px;background:rgba(14,21,36,.94);color:#fff;font:inherit;outline:none;box-shadow:0 18px 50px rgba(0,0,0,.24)}
textarea:focus{border-color:rgba(105,236,192,.52);box-shadow:0 0 0 4px rgba(105,236,192,.07),0 18px 50px rgba(0,0,0,.24)}.send{position:absolute;left:9px;bottom:9px;width:43px;height:43px;border:0;border-radius:14px;background:linear-gradient(135deg,var(--a),var(--b));color:#041018;font-size:18px;font-weight:900}.tools{max-width:840px;margin:8px auto 0;display:flex;gap:8px;flex-wrap:wrap}.tool{border:1px solid var(--line);background:rgba(16,24,41,.65);color:#c2cede;border-radius:12px;padding:8px 11px}.thinking{max-width:840px;margin:0 auto 8px;color:var(--muted);font-size:12px}
.logout{margin-top:auto}
@media(max-width:800px){.app{grid-template-columns:1fr}.side{display:none}.top{padding:0 14px}.chat{padding:17px 10px}.bottom{padding:10px 10px 14px}.welcome{margin-top:8vh}.welcome h2{font-size:29px}}
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
<button class="tool" type="button" id="read">🔊 הקרא</button>
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
let last={{ last_answer|tojson }};
let workTimer=null, workStarted=0;
function startWork(){workStarted=Date.now(); if(workTimer)clearInterval(workTimer); const tick=()=>{const s=Math.floor((Date.now()-workStarted)/1000); const m=String(Math.floor(s/60)).padStart(2,"0"); const ss=String(s%60).padStart(2,"0"); statusEl.textContent=`🟢 DEAN עובד · ${m}:${ss}`;}; tick(); workTimer=setInterval(tick,1000);}
function finishWork(){if(workTimer)clearInterval(workTimer); workTimer=null; statusEl.textContent="✅ הסתיים"; const u=new SpeechSynthesisUtterance("סיימתי"); u.lang="he-IL"; speechSynthesis.cancel(); speechSynthesis.speak(u);}
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
    const r=await fetch("/api/chat",{
      method:"POST",
      credentials:"same-origin",
      headers:{
        "Content-Type":"application/json",
        "X-CSRF-Token":csrf
      },
      body:JSON.stringify({message:text})
    });

    if(r.status===401){
      location.href="/login";
      return;
    }

    const data=await r.json();

    if(!r.ok){
      throw new Error(data.error||"שגיאה");
    }

    last=data.answer;
    addMessage("assistant",last);
    finishWork();
  }catch(err){
    failWork("שגיאה: "+err.message);
    message.value=text;
  }finally{
    document.getElementById("send").disabled=false;
  }
});

document.getElementById("copy").onclick=async()=>{
  if(last)await navigator.clipboard.writeText(last);
};

const readBtn=document.getElementById("read");
readBtn.onclick=()=>{
  if(speechSynthesis.speaking || speechSynthesis.pending){
    speechSynthesis.cancel();
    readBtn.textContent="🔊 הקרא";
    return;
  }
  if(!last)return;
  const spoken=last.replace(/[*#_`~>|]/g,"").replace(/\[(.*?)\]\([^)]*\)/g,"$1");\n  const u=new SpeechSynthesisUtterance(spoken);
  u.lang="he-IL";
  u.onend=()=>{readBtn.textContent="🔊 הקרא";};
  u.onerror=()=>{readBtn.textContent="🔊 הקרא";};
  readBtn.textContent="⏹ עצור";
  speechSynthesis.speak(u);
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

@app.get("/health")
def health():
    try:
        with get_db() as con:
            con.execute("SELECT 1").fetchone()
        return jsonify(status="ok", database="postgres" if DATABASE_URL else "sqlite")
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

    return jsonify(answer=answer)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
