"""Private editable life dashboard for DEAN."""
from flask import jsonify, render_template_string, request

DEFAULT_AREAS = [
 ("בריאות וכושר","💪"),("ביטוחים וזכויות","🛡️"),("עבודה ופרנסה","🏗️"),("כסף ופנסיה","💰"),
 ("הילד והמשפחה","👨‍👦"),("זוגיות","❤️"),("אמונה ותורה","📖"),
 ("בית","🏠"),("חברים ופנאי","🤝"),("לימוד והתפתחות","🧠"),
 ("רכב ותחבורה","🚗"),("סידורים אישיים","📋")
]

PAGE = r"""<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>יומן החיים | בניאל</title>
<style>
:root{--ink:#29243e;--muted:#77758c;--paper:#fff;--line:#eee8f1;--purple:#7457d9;--pink:#ed91b9;--shadow:0 12px 35px #45336b12}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font-family:Arial,sans-serif;background:radial-gradient(ellipse at 8% 0%,#f5eaff,transparent 34%),radial-gradient(ellipse at 95% 12%,#fff0e5,transparent 30%),#fff9f5;min-height:100vh}
.wrap{max-width:1180px;margin:auto;padding:22px}.hero,.card,.area{background:var(--paper);border:1px solid var(--line);border-radius:21px;padding:18px;margin-bottom:14px;box-shadow:var(--shadow)}.hero{background:linear-gradient(115deg,#7457d9,#9c75e8 55%,#e895b8);color:white;border:0;border-radius:27px;padding:27px;position:relative;overflow:hidden}.hero:after{content:"✦";position:absolute;left:28px;top:-45px;font-size:190px;color:#ffffff18}.hero h1{font-size:30px;margin:9px 0}.hero .muted{color:#ffffffdf}.brand{display:flex;align-items:center;gap:10px;font-weight:bold;letter-spacing:1px}.logo{width:44px;height:44px;border-radius:15px;background:linear-gradient(140deg,#8869ec,#e98db9);display:grid;place-items:center;color:white;font-size:23px}
h2{font-size:18px}.stats,.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin-top:15px}.stat{background:#ffffff20;border:1px solid #ffffff35;border-radius:15px;padding:13px}.stat b{display:block;font-size:25px;margin:5px 0}.tabs{display:flex;gap:8px;overflow:auto;margin:12px 0}.tabs button,button{font:inherit;border:0;border-radius:12px;padding:11px 14px;background:#fff;color:var(--ink);cursor:pointer;box-shadow:0 3px 12px #45336b0b}.tabs .active,.primary{background:var(--purple);color:white;font-weight:bold}.area{min-height:110px;background:linear-gradient(145deg,#fff,#fbf8ff)}.area strong{display:block;margin:8px 0}.bar{height:8px;background:#eeeaf5;border-radius:20px;overflow:hidden;margin:9px 0}.bar i{display:block;height:100%;border-radius:20px;background:linear-gradient(90deg,var(--purple),var(--pink))}.hidden{display:none}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}label{display:block;color:var(--muted);font-size:13px}input,textarea,select{width:100%;padding:12px;border:1px solid #e9e2f0;border-radius:12px;background:#fff;color:var(--ink);font:inherit;margin:5px 0 9px}input[type=range]{accent-color:var(--purple);padding:0}.goal{border-top:1px solid var(--line);padding:13px 0}.actions{display:flex;gap:7px;flex-wrap:wrap}.actions button{font-size:12px;padding:8px 11px;background:#f3effb;color:var(--purple)}.empty{padding:17px;color:var(--muted);text-align:center;background:#faf8fc;border-radius:14px}.note{font-size:11px;color:var(--muted);line-height:1.7;text-align:center}.chart{width:100%;height:auto;display:block}.chart-labels{display:flex;justify-content:space-around;color:var(--muted);font-size:11px;margin-top:4px}
@media(max-width:650px){.stats,.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.wrap{padding:11px}.hero{padding:22px}.hero h1{font-size:25px}}
</style><main class="wrap"><header class="hero"><div class="row"><span class="brand"><span class="logo">✦</span><span>בניאל · יומן החיים שלי</span></span><div class="theme-picks"><button type="button" id="sunsetTheme" class="active">🌅 שקיעה ואגם</button><button type="button" id="mountainTheme">🏔️ הרים</button></div></div><h1>הדרך שלי, בקצב שלי</h1><div class="muted" id="today"></div><p class="muted">מסתכלים על התמונה הגדולה, מסמנים התקדמות ובונים את הדרך שלך בקצב שלך.</p><div class="stats"><div class="stat"><b id="goalCount">0</b><span class="muted">מטרות פעילות</span></div><div class="stat"><b id="avg">0%</b><span class="muted">התקדמות ממוצעת</span></div><div class="stat"><b id="checks">0</b><span class="muted">דיווחים החודש</span></div><div class="stat"><b id="wins">0</b><span class="muted">מטרות שהושלמו</span></div></div></header>
<nav class="tabs"><button class="active" data-tab="overview">תמונה כללית</button><button data-tab="goals">מטרות ומדדים</button><button data-tab="daily">דיווח יומי</button><button data-tab="history">היסטוריה</button></nav>
<section id="overview"><div class="card"><div class="row"><h2>תחומי החיים</h2><button id="addArea">＋ תחום חדש</button></div><div class="grid" id="areas"></div></div><div class="card"><h2>דורש תשומת לב</h2><div id="attention"></div></div></section>
<section id="goals" class="hidden"><div class="card"><h2>הוספת מטרה</h2><label>שם המטרה</label><input id="goalName" placeholder="למשל: לחזור להתאמן בקביעות"><label>תחום</label><select id="goalArea"></select><label>איך מודדים הצלחה?</label><input id="goalMeasure" placeholder="למשל: 3 אימונים בשבוע"><label>יעד / תאריך</label><input id="goalTarget" placeholder="למשל: עד סוף החודש"><button class="primary" id="saveGoal">שמירת מטרה</button></div><div class="card"><h2>כל המטרות</h2><div id="goalList"></div></div></section>
<section id="daily" class="hidden"><div class="card"><h2>דיווח יומי קצר</h2><p class="muted">אין ציון על יום חלש. מתעדים כדי לראות את המציאות ולהתקדם.</p><label>תחום</label><select id="checkArea"></select><label>איך התקדם התחום היום? 0–100</label><input id="checkValue" type="range" min="0" max="100" value="50"><b id="rangeValue">50%</b><label>מה עשיתי בפועל?</label><textarea id="checkNote" rows="3"></textarea><label>מה הפריע או עיכב?</label><textarea id="checkBlock" rows="2"></textarea><button class="primary" id="saveCheck">שמירת דיווח</button><p id="checkSaved" class="muted"></p></div><div class="card"><h2>סיכום יום חופשי</h2><textarea id="daySummary" rows="3" placeholder="מה קרה היום? מה למדתי?"></textarea><button id="saveSummary">שמירת סיכום</button></div></section>
<section id="history" class="hidden"><div class="card"><h2>📈 מגמת ההתקדמות</h2><div id="trendChart"></div></div><div class="card"><h2>📚 סיכומי ימים</h2><div id="summaryList"></div></div><div class="card"><h2>היסטוריית דיווחים</h2><div id="historyList"></div></div></section>
<p class="note">הנתונים נשמרים במסד הנתונים של DEAN מאחורי ההתחברות. זהו בסיס ראשון שאפשר להרחיב: תחומים, מטרות, מדדים, דיווחים והיסטוריה.</p></main>
<script>
const csrf={{ csrf|tojson }};let data={areas:[],goals:[],checks:[],summaries:[]};const $=x=>document.getElementById(x);const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const now=new Date();$('today').textContent=now.toLocaleDateString('he-IL',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
async function api(url,method,body){const r=await fetch(url,{method:method||'GET',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'שגיאה');return d}
function select(id){$(id).innerHTML=data.areas.map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('')}
function trendSvg(checks){const list=checks.slice(0,12).reverse();if(!list.length)return '<div class="empty">אחרי הדיווח הראשון תופיע כאן מגמת ההתקדמות שלך.</div>';const w=520,h=150,p=22;const pts=list.map((c,i)=>{const x=p+(list.length===1?(w-2*p)/2:i*(w-2*p)/(list.length-1));return [x,h-p-(Number(c.value)/100)*(h-2*p)]});const poly=pts.map(v=>v.join(',')).join(' ');return '<svg class="chart" viewBox="0 0 '+w+' '+h+'"><polyline points="'+poly+'" fill="none" stroke="#8062df" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'+pts.map((v,i)=>'<circle cx="'+v[0]+'" cy="'+v[1]+'" r="5" fill="#e98db9"><title>'+list[i].value+'%</title></circle>').join('')+'</svg><div class="chart-labels">'+list.map(c=>'<span>'+new Date(c.created).toLocaleDateString('he-IL',{day:'numeric',month:'numeric'})+'</span>').join('')+'</div>'}
function render(){const active=data.goals.filter(g=>g.status!=='done');$('goalCount').textContent=active.length;$('wins').textContent=data.goals.length-active.length;$('avg').textContent=(active.length?Math.round(active.reduce((s,g)=>s+g.progress,0)/active.length):0)+'%';$('checks').textContent=data.checks.filter(c=>c.created.slice(0,7)===now.toISOString().slice(0,7)).length;
$('areas').innerHTML=data.areas.map(a=>{const gs=active.filter(g=>g.area_id===a.id);const p=gs.length?Math.round(gs.reduce((s,g)=>s+g.progress,0)/gs.length):0;return '<div class="area"><span>'+esc(a.icon)+'</span><strong>'+esc(a.name)+'</strong><span class="muted">'+gs.length+' מטרות · '+p+'%</span><div class="bar"><i style="width:'+p+'%"></i></div></div>'}).join('');
select('goalArea');select('checkArea');
$('goalList').innerHTML=data.goals.length?data.goals.map(g=>'<div class="goal"><div class="row"><b>'+esc(g.name)+'</b><span class="muted">'+esc(g.area_name)+'</span></div><div class="muted">'+esc(g.measure)+' · '+esc(g.target)+'</div><div class="bar"><i style="width:'+g.progress+'%"></i></div><div class="row"><input data-progress="'+g.id+'" type="range" min="0" max="100" value="'+g.progress+'"><b>'+g.progress+'%</b></div><div class="actions"><button data-done="'+g.id+'">הושלם</button><button data-edit="'+g.id+'">עריכת שם</button><button data-delete="'+g.id+'">מחיקה</button></div></div>').join(''):'<div class="empty">אין מטרות עדיין. נוסיף אותן יחד.</div>';
$('attention').innerHTML=active.slice().sort((a,b)=>a.progress-b.progress).slice(0,5).map(g=>'<div class="goal"><b>'+esc(g.name)+'</b><div class="muted">'+esc(g.area_name)+' · '+g.progress+'%</div><div class="bar"><i style="width:'+g.progress+'%"></i></div></div>').join('')||'<div class="empty">אין מטרות פעילות.</div>';
$('trendChart').innerHTML=trendSvg(data.checks);$('summaryList').innerHTML=data.summaries.map(s=>'<div class="goal"><div class="muted">'+new Date(s.created).toLocaleDateString('he-IL')+'</div><div>'+esc(s.summary)+'</div></div>').join('')||'<div class="empty">עדיין לא נשמרו סיכומי ימים.</div>';$('historyList').innerHTML=data.checks.map(c=>'<div class="goal"><div class="row"><b>'+esc(c.area_name)+'</b><span class="muted">'+new Date(c.created).toLocaleDateString('he-IL')+'</span></div><div class="bar"><i style="width:'+c.value+'%"></i></div><b>'+c.value+'%</b><div>'+esc(c.note)+'</div>'+(c.blocker?'<div class="muted">עיכוב: '+esc(c.blocker)+'</div>':'')+'</div>').join('')||'<div class="empty">הדיווחים יופיעו כאן.</div>'}
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
