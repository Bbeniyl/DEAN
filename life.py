"""Private editable life dashboard for DEAN."""
from flask import jsonify, render_template_string, request

DEFAULT_AREAS = [
 ("בריאות וכושר","💪"),("ביטוחים וזכויות","🛡️"),("עבודה ופרנסה","🏗️"),("כסף ופנסיה","💰"),
 ("הילד והמשפחה","👨‍👦"),("זוגיות","❤️"),("אמונה ותורה","📖"),
 ("בית","🏠"),("חברים ופנאי","🤝"),("לימוד והתפתחות","🧠"),
 ("רכב ותחבורה","🚗"),("סידורים אישיים","📋")
]

PAGE = r"""<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>יומן החיים | DEAN</title>
<style>
:root{--bg:#101820;--p:#192632;--p2:#20313d;--line:#30424e;--ink:#f3f5f4;--muted:#a5b3b9;--gold:#e9b85d;--green:#65c69a}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Arial,sans-serif}.wrap{max-width:1050px;margin:auto;padding:16px}.hero,.card,.area{background:var(--p);border:1px solid var(--line);border-radius:16px;padding:16px;margin-bottom:12px}.hero{background:linear-gradient(130deg,#1c3441,#18232d)}h1{margin:8px 0}.muted{color:var(--muted);font-size:13px}.stats,.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-top:14px}.stat{background:#ffffff0c;border:1px solid var(--line);border-radius:12px;padding:12px}.stat b{display:block;font-size:23px}.tabs{display:flex;gap:7px;overflow:auto;margin:12px 0}.tabs button,button{font:inherit;border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--p2);color:var(--ink);cursor:pointer}.tabs .active,.primary{background:var(--gold);color:#1b2023;font-weight:bold}.area{text-align:right;cursor:pointer;min-height:95px}.area strong{display:block;margin:7px 0}.bar{height:7px;background:#344650;border-radius:8px;overflow:hidden;margin:8px 0}.bar i{display:block;height:100%;background:var(--green)}.hidden{display:none}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}.field{margin:8px 0}label{display:block;color:var(--muted);font-size:13px}input,textarea,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:9px;background:#111c25;color:var(--ink);font:inherit;margin:5px 0 9px}.goal{border-top:1px solid var(--line);padding:12px 0}.goal:first-child{border:0}.actions{display:flex;gap:7px;flex-wrap:wrap}.empty{padding:15px;color:var(--muted);text-align:center}.note{font-size:12px;color:var(--muted);line-height:1.6}@media(max-width:650px){.stats,.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.wrap{padding:10px}}
</style><main class="wrap"><header class="hero"><div class="row"><span>DEAN · מרכז השליטה האישי</span><a href="/" style="color:var(--gold)">חזרה לצ׳אט</a></div><h1>יומן החיים שלי</h1><div class="muted" id="today"></div><p class="muted">תמונה אמיתית של החיים: מטרות, צעדים קטנים ומגמות לאורך זמן.</p><div class="stats"><div class="stat"><b id="goalCount">0</b><span class="muted">מטרות פעילות</span></div><div class="stat"><b id="avg">0%</b><span class="muted">התקדמות ממוצעת</span></div><div class="stat"><b id="checks">0</b><span class="muted">דיווחים החודש</span></div><div class="stat"><b id="wins">0</b><span class="muted">מטרות שהושלמו</span></div></div></header>
<nav class="tabs"><button class="active" data-tab="overview">תמונה כללית</button><button data-tab="goals">מטרות ומדדים</button><button data-tab="daily">דיווח יומי</button><button data-tab="history">היסטוריה</button></nav>
<section id="overview"><div class="card"><div class="row"><h2>תחומי החיים</h2><button id="addArea">＋ תחום חדש</button></div><div class="grid" id="areas"></div></div><div class="card"><h2>דורש תשומת לב</h2><div id="attention"></div></div></section>
<section id="goals" class="hidden"><div class="card"><h2>הוספת מטרה</h2><label>שם המטרה</label><input id="goalName" placeholder="למשל: לחזור להתאמן בקביעות"><label>תחום</label><select id="goalArea"></select><label>איך מודדים הצלחה?</label><input id="goalMeasure" placeholder="למשל: 3 אימונים בשבוע"><label>יעד / תאריך</label><input id="goalTarget" placeholder="למשל: עד סוף החודש"><button class="primary" id="saveGoal">שמירת מטרה</button></div><div class="card"><h2>כל המטרות</h2><div id="goalList"></div></div></section>
<section id="daily" class="hidden"><div class="card"><h2>דיווח יומי קצר</h2><p class="muted">אין ציון על יום חלש. מתעדים כדי לראות את המציאות ולהתקדם.</p><label>תחום</label><select id="checkArea"></select><label>איך התקדם התחום היום? 0–100</label><input id="checkValue" type="range" min="0" max="100" value="50"><b id="rangeValue">50%</b><label>מה עשיתי בפועל?</label><textarea id="checkNote" rows="3"></textarea><label>מה הפריע או עיכב?</label><textarea id="checkBlock" rows="2"></textarea><button class="primary" id="saveCheck">שמירת דיווח</button><p id="checkSaved" class="muted"></p></div><div class="card"><h2>סיכום יום חופשי</h2><textarea id="daySummary" rows="3" placeholder="מה קרה היום? מה למדתי?"></textarea><button id="saveSummary">שמירת סיכום</button></div></section>
<section id="history" class="hidden"><div class="card"><h2>היסטוריה ומגמות</h2><div id="historyList"></div></div></section>
<p class="note">הנתונים נשמרים במסד הנתונים של DEAN מאחורי ההתחברות. זהו בסיס ראשון שאפשר להרחיב: תחומים, מטרות, מדדים, דיווחים והיסטוריה.</p></main>
<script>
const csrf={{ csrf|tojson }};let data={areas:[],goals:[],checks:[],summaries:[]};const $=x=>document.getElementById(x);const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const now=new Date();$('today').textContent=now.toLocaleDateString('he-IL',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
async function api(url,method,body){const r=await fetch(url,{method:method||'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'שגיאה');return d}
function select(id){$(id).innerHTML=data.areas.map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('')}
function render(){const active=data.goals.filter(g=>g.status!=='done');$('goalCount').textContent=active.length;$('wins').textContent=data.goals.length-active.length;$('avg').textContent=(active.length?Math.round(active.reduce((s,g)=>s+g.progress,0)/active.length):0)+'%';$('checks').textContent=data.checks.filter(c=>c.created.slice(0,7)===now.toISOString().slice(0,7)).length;
$('areas').innerHTML=data.areas.map(a=>{const gs=active.filter(g=>g.area_id===a.id);const p=gs.length?Math.round(gs.reduce((s,g)=>s+g.progress,0)/gs.length):0;return '<div class="area"><span>'+esc(a.icon)+'</span><strong>'+esc(a.name)+'</strong><span class="muted">'+gs.length+' מטרות · '+p+'%</span><div class="bar"><i style="width:'+p+'%"></i></div></div>'}).join('');
select('goalArea');select('checkArea');
$('goalList').innerHTML=data.goals.length?data.goals.map(g=>'<div class="goal"><div class="row"><b>'+esc(g.name)+'</b><span class="muted">'+esc(g.area_name)+'</span></div><div class="muted">'+esc(g.measure)+' · '+esc(g.target)+'</div><div class="bar"><i style="width:'+g.progress+'%"></i></div><div class="row"><input data-progress="'+g.id+'" type="range" min="0" max="100" value="'+g.progress+'"><b>'+g.progress+'%</b></div><div class="actions"><button data-done="'+g.id+'">הושלם</button><button data-edit="'+g.id+'">עריכת שם</button><button data-delete="'+g.id+'">מחיקה</button></div></div>').join(''):'<div class="empty">אין מטרות עדיין. נוסיף אותן יחד.</div>';
$('attention').innerHTML=active.slice().sort((a,b)=>a.progress-b.progress).slice(0,5).map(g=>'<div class="goal"><b>'+esc(g.name)+'</b><div class="muted">'+esc(g.area_name)+' · '+g.progress+'%</div><div class="bar"><i style="width:'+g.progress+'%"></i></div></div>').join('')||'<div class="empty">אין מטרות פעילות.</div>';
$('historyList').innerHTML=data.checks.map(c=>'<div class="goal"><div class="row"><b>'+esc(c.area_name)+'</b><span class="muted">'+new Date(c.created).toLocaleDateString('he-IL')+'</span></div><div class="bar"><i style="width:'+c.value+'%"></i></div><b>'+c.value+'%</b><div>'+esc(c.note)+'</div>'+(c.blocker?'<div class="muted">עיכוב: '+esc(c.blocker)+'</div>':'')+'</div>').join('')||'<div class="empty">הדיווחים יופיעו כאן.</div>'}
async function load(){data=await api('/api/life/dashboard');render()}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));['overview','goals','daily','history'].forEach(id=>$(id).classList.toggle('hidden',id!==b.dataset.tab))});
$('saveGoal').onclick=async()=>{try{await api('/api/life/goals','POST',{name:$('goalName').value,area_id:+$('goalArea').value,measure:$('goalMeasure').value,target:$('goalTarget').value});$('goalName').value='';$('goalMeasure').value='';$('goalTarget').value='';await load()}catch(e){alert(e.message)}};
$('saveCheck').onclick=async()=>{try{await api('/api/life/checkins','POST',{area_id:+$('checkArea').value,value:+$('checkValue').value,note:$('checkNote').value,blocker:$('checkBlock').value});$('checkNote').value='';$('checkBlock').value='';$('checkSaved').textContent='נשמר';await load()}catch(e){alert(e.message)}};
$('checkValue').oninput=()=> $('rangeValue').textContent=$('checkValue').value+'%';
$('saveSummary').onclick=async()=>{try{await api('/api/life/summary','POST',{summary:$('daySummary').value});$('daySummary').value='';alert('נשמר')}catch(e){alert(e.message)}};
$('addArea').onclick=async()=>{const n=prompt('שם התחום החדש?');if(!n)return;const i=prompt('אייקון לתחום?','⭐')||'⭐';try{await api('/api/life/areas','POST',{name:n,icon:i});await load()}catch(e){alert(e.message)}};
document.addEventListener('change',async e=>{if(e.target.dataset.progress){try{await api('/api/life/goals/'+e.target.dataset.progress,'PATCH',{progress:+e.target.value});await load()}catch(x){alert(x.message)}}});
document.addEventListener('click',async e=>{try{if(e.target.dataset.done){await api('/api/life/goals/'+e.target.dataset.done,'PATCH',{status:'done',progress:100});await load()}if(e.target.dataset.delete&&confirm('למחוק?')){await api('/api/life/goals/'+e.target.dataset.delete,'DELETE');await load()}if(e.target.dataset.edit){const g=data.goals.find(x=>x.id===+e.target.dataset.edit);const n=prompt('שם חדש',g.name);if(n){await api('/api/life/goals/'+g.id,'PATCH',{name:n});await load()}}}catch(x){alert(x.message)}});
load().catch(e=>alert(e.message));
</script></html>"""

def register_life(app, require_login, require_csrf, csrf_token, get_db, postgres):
    def q(s): return s.replace("?", "%s") if postgres else s
    from datetime import datetime, timezone
    now=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_db() as con:
        if postgres:
            con.execute("CREATE TABLE IF NOT EXISTS life_areas(id BIGSERIAL PRIMARY KEY,name TEXT NOT NULL UNIQUE,icon TEXT NOT NULL DEFAULT '⭐',created TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS life_goals(id BIGSERIAL PRIMARY KEY,area_id BIGINT NOT NULL,name TEXT NOT NULL,measure TEXT NOT NULL DEFAULT '',target TEXT NOT NULL DEFAULT '',progress INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',created TEXT NOT NULL,updated TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS life_checkins(id BIGSERIAL PRIMARY KEY,area_id BIGINT NOT NULL,value INTEGER NOT NULL,note TEXT NOT NULL DEFAULT '',blocker TEXT NOT NULL DEFAULT '',created TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS life_summaries(id BIGSERIAL PRIMARY KEY,summary TEXT NOT NULL,created TEXT NOT NULL)")
        else:
            con.executescript("CREATE TABLE IF NOT EXISTS life_areas(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,icon TEXT NOT NULL DEFAULT '⭐',created TEXT NOT NULL); CREATE TABLE IF NOT EXISTS life_goals(id INTEGER PRIMARY KEY AUTOINCREMENT,area_id INTEGER NOT NULL,name TEXT NOT NULL,measure TEXT NOT NULL DEFAULT '',target TEXT NOT NULL DEFAULT '',progress INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',created TEXT NOT NULL,updated TEXT NOT NULL); CREATE TABLE IF NOT EXISTS life_checkins(id INTEGER PRIMARY KEY AUTOINCREMENT,area_id INTEGER NOT NULL,value INTEGER NOT NULL,note TEXT NOT NULL DEFAULT '',blocker TEXT NOT NULL DEFAULT '',created TEXT NOT NULL); CREATE TABLE IF NOT EXISTS life_summaries(id INTEGER PRIMARY KEY AUTOINCREMENT,summary TEXT NOT NULL,created TEXT NOT NULL)")
        for name,icon in DEFAULT_AREAS:
            con.execute(q("INSERT INTO life_areas(name,icon,created) VALUES(?,?,?) ON CONFLICT(name) DO NOTHING"),(name,icon,now()))

    @app.get("/life")
    @require_login
    def life_page(): return render_template_string(PAGE,csrf=csrf_token())

    @app.get("/api/life/dashboard")
    @require_login
    def life_dashboard():
        with get_db() as con:
            a=[dict(x) for x in con.execute("SELECT * FROM life_areas ORDER BY id").fetchall()]
            g=[dict(x) for x in con.execute("SELECT g.*,a.name AS area_name FROM life_goals g JOIN life_areas a ON a.id=g.area_id ORDER BY g.id DESC").fetchall()]
            c=[dict(x) for x in con.execute("SELECT c.*,a.name AS area_name FROM life_checkins c JOIN life_areas a ON a.id=c.area_id ORDER BY c.id DESC LIMIT 150").fetchall()]
            s=[dict(x) for x in con.execute("SELECT * FROM life_summaries ORDER BY id DESC LIMIT 60").fetchall()]
        return jsonify(areas=a,goals=g,checks=c,summaries=s)

    @app.post("/api/life/areas")
    @require_login
    @require_csrf
    def life_add_area():
        d=request.get_json(silent=True) or {}; n=str(d.get("name","")).strip()[:80]; icon=str(d.get("icon","⭐"))[:8]
        if not n:return jsonify(error="חסר שם תחום"),400
        try:
            with get_db() as con: con.execute(q("INSERT INTO life_areas(name,icon,created) VALUES(?,?,?)"),(n,icon,now()))
        except Exception:return jsonify(error="התחום כבר קיים"),409
        return jsonify(ok=True)

    @app.post("/api/life/goals")
    @require_login
    @require_csrf
    def life_add_goal():
        d=request.get_json(silent=True) or {}; n=str(d.get("name","")).strip()[:180]; aid=int(d.get("area_id",0) or 0)
        if not n:return jsonify(error="חסר שם מטרה"),400
        with get_db() as con:
            if not con.execute(q("SELECT id FROM life_areas WHERE id=?"),(aid,)).fetchone():return jsonify(error="תחום לא נמצא"),404
            con.execute(q("INSERT INTO life_goals(area_id,name,measure,target,created,updated) VALUES(?,?,?,?,?,?)"),(aid,n,str(d.get("measure",""))[:300],str(d.get("target",""))[:120],now(),now()))
        return jsonify(ok=True)

    @app.patch("/api/life/goals/<int:gid>")
    @require_login
    @require_csrf
    def life_update_goal(gid):
        d=request.get_json(silent=True) or {}; changes={k:v for k,v in d.items() if k in ("name","measure","target","progress","status")}
        if not changes:return jsonify(ok=False)
        if "progress" in changes:changes["progress"]=max(0,min(100,int(changes["progress"])))
        if "status" in changes and changes["status"] not in ("active","paused","done"):return jsonify(error="סטטוס לא תקין"),400
        if "name" in changes:changes["name"]=str(changes["name"]).strip()[:180]
        changes["updated"]=now(); clause=", ".join(k+"=?" for k in changes)
        with get_db() as con:con.execute(q("UPDATE life_goals SET "+clause+" WHERE id=?"),tuple(changes.values())+(gid,))
        return jsonify(ok=True)

    @app.delete("/api/life/goals/<int:gid>")
    @require_login
    @require_csrf
    def life_delete_goal(gid):
        with get_db() as con:con.execute(q("DELETE FROM life_goals WHERE id=?"),(gid,))
        return jsonify(ok=True)

    @app.post("/api/life/checkins")
    @require_login
    @require_csrf
    def life_add_checkin():
        d=request.get_json(silent=True) or {}; aid=int(d.get("area_id",0) or 0); v=max(0,min(100,int(d.get("value",0) or 0)))
        with get_db() as con:
            if not con.execute(q("SELECT id FROM life_areas WHERE id=?"),(aid,)).fetchone():return jsonify(error="תחום לא נמצא"),404
            con.execute(q("INSERT INTO life_checkins(area_id,value,note,blocker,created) VALUES(?,?,?,?,?)"),(aid,v,str(d.get("note",""))[:1500],str(d.get("blocker",""))[:1000],now()))
        return jsonify(ok=True)

    @app.post("/api/life/summary")
    @require_login
    @require_csrf
    def life_add_summary():
        d=request.get_json(silent=True) or {}; s=str(d.get("summary","")).strip()[:4000]
        if not s:return jsonify(error="סיכום ריק"),400
        with get_db() as con:con.execute(q("INSERT INTO life_summaries(summary,created) VALUES(?,?)"),(s,now()))
        return jsonify(ok=True)
