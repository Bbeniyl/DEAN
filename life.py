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
*{box-sizing:border-box}body{margin:0;color:#fff;font-family:Arial,sans-serif;background-color:#26313a;background-size:cover;background-position:center;background-attachment:fixed;min-height:100vh;transition:background-image .35s ease}body.theme-sunset{background-image:linear-gradient(135deg,#14212b99,#182b3b66),url('https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=2200&q=85')}body.theme-mountains{background-image:linear-gradient(135deg,#101d2b99,#142a3a66),url('https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=2200&q=85')}
.wrap{max-width:1180px;margin:auto;padding:22px}.hero,.card,.area{background:rgba(17,29,40,.48);border:1px solid rgba(255,255,255,.24);border-radius:21px;padding:18px;margin-bottom:14px;box-shadow:0 12px 35px #0003;backdrop-filter:blur(13px);-webkit-backdrop-filter:blur(13px);color:#fff}.hero{background:rgba(13,25,36,.42);color:white;border:1px solid rgba(255,255,255,.28);border-radius:27px;padding:27px;position:relative;overflow:hidden}.hero:after{content:"✦";position:absolute;left:28px;top:-45px;font-size:190px;color:#ffffff18}.theme-picks{display:flex;gap:8px;flex-wrap:wrap;position:relative;z-index:2}.theme-picks button{background:rgba(255,255,255,.16);color:#fff;border:1px solid #ffffff55;box-shadow:none}.theme-picks button.active{background:#d7b77b;color:#17232c;border-color:#f5dfb6}.hero h1{font-size:30px;margin:9px 0}.hero .muted{color:#ffffffdf}.world-meta{display:flex;flex-direction:column;text-align:left;gap:3px;text-shadow:0 2px 12px #000}.world-meta strong{font-size:25px;font-weight:400}.world-meta span{font-size:11px;color:#eee}.brand{display:flex;align-items:center;gap:10px;font-weight:bold;letter-spacing:1px}.logo{width:44px;height:44px;border-radius:15px;background:linear-gradient(140deg,#8869ec,#e98db9);display:grid;place-items:center;color:white;font-size:23px}
h2{font-size:18px}.stats,.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px;margin-top:15px}.stat{background:#ffffff20;border:1px solid #ffffff35;border-radius:15px;padding:13px}.stat b{display:block;font-size:25px;margin:5px 0}.tabs{display:flex;gap:8px;overflow:auto;margin:12px 0}.tabs button,button{font:inherit;border:0;border-radius:12px;padding:11px 14px;background:#fff;color:var(--ink);cursor:pointer;box-shadow:0 3px 12px #45336b0b}.tabs .active,.primary{background:#d7b77b;color:#17232c;font-weight:bold}.tabs button{background:rgba(16,29,40,.55);color:#fff;border:1px solid #ffffff35}.area{min-height:110px;background:rgba(255,255,255,.13)}.area strong{display:block;margin:8px 0} .bar{height:8px;background:#ffffff35;border-radius:20px;overflow:hidden;margin:9px 0}.bar i{display:block;height:100%;border-radius:20px;background:linear-gradient(90deg,#e4c48c,#fff0cf)}.hidden{display:none}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}label{display:block;color:#f1e9dc;font-size:13px}.muted,.note,.chart-labels{color:#e8e3da!important}input,textarea,select{width:100%;padding:12px;border:1px solid #e9e2f0;border-radius:12px;background:#fff;color:var(--ink);font:inherit;margin:5px 0 9px}input[type=range]{accent-color:var(--purple);padding:0}.goal{border-top:1px solid var(--line);padding:13px 0}.actions{display:flex;gap:7px;flex-wrap:wrap}.actions button{font-size:12px;padding:8px 11px;background:#f3effb;color:var(--purple)}.empty{padding:17px;color:#fff;text-align:center;background:rgba(255,255,255,.12);border-radius:14px}.note{font-size:11px;color:var(--muted);line-height:1.7;text-align:center}.chart{width:100%;height:auto;display:block}.chart-labels{display:flex;justify-content:space-around;color:var(--muted);font-size:11px;margin-top:4px}
@media(max-width:650px){.stats,.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.wrap{padding:11px}.hero{padding:22px}.hero h1{font-size:25px}}

/* DEAN cinematic world behind the existing interactive life journal */
body{background:transparent!important;background-image:none!important;position:relative;isolation:isolate}
#deanWorld{position:fixed;inset:0;width:100%;height:100%;border:0;z-index:0;pointer-events:none}
.wrap{position:relative;z-index:1}
.hero,.card,.area{background:rgba(14,29,40,.48);border-color:rgba(255,255,255,.25);color:#fff}
.hero{background:rgba(10,24,36,.48)}

/* DEAN WORLD JOURNAL — immersive, calm, mobile-first */
:root{--gold:#e9cf9a;--glass:rgba(8,22,29,.34);--glass2:rgba(8,22,29,.48);--softline:rgba(255,255,255,.16)}
html{min-height:100%;background:#172a30}
html{background:transparent!important}body{min-height:100vh;background:transparent!important;color:#f7f4eb!important;font-family:Arial,sans-serif;position:relative!important;isolation:isolate!important}
#deanWorld{position:fixed!important;inset:0!important;width:100vw!important;height:100dvh!important;z-index:1!important;display:block!important;pointer-events:none!important}
.wrap{max-width:1040px!important;padding:clamp(14px,3vw,34px)!important;margin:0 auto!important;z-index:2!important;background:transparent!important}
.hero{background:linear-gradient(115deg,rgba(7,22,29,.56),rgba(7,22,29,.12))!important;border:1px solid var(--softline)!important;border-radius:28px!important;padding:clamp(19px,4vw,34px)!important;box-shadow:0 18px 60px #07151b45!important;backdrop-filter:blur(10px)!important}
.hero:after{content:none!important}
.brand{letter-spacing:.4px!important}.logo{background:rgba(233,207,154,.2)!important;border:1px solid #e9cf9a88!important;color:var(--gold)!important;border-radius:50%!important}
.hero h1{font-size:clamp(27px,5vw,43px)!important;line-height:1.15!important;letter-spacing:-.7px!important;margin:22px 0 8px!important}
.hero p{max-width:560px;line-height:1.8}
.world-meta strong{font-size:clamp(24px,4vw,34px)!important;color:var(--gold)}
.stats{display:flex!important;flex-wrap:wrap!important;gap:0!important;margin-top:24px!important;border-top:1px solid var(--softline);padding-top:16px}
.stat{flex:1 1 115px!important;background:transparent!important;border:0!important;border-left:1px solid var(--softline)!important;border-radius:0!important;padding:5px 15px!important}
.stat:last-child{border-left:0!important}.stat b{font-size:clamp(23px,3vw,30px)!important;color:var(--gold)!important;font-weight:500}
.tabs{position:sticky;top:8px;z-index:5;display:flex;gap:7px;padding:7px;margin:15px 0 20px!important;background:rgba(5,18,25,.48);border:1px solid var(--softline);border-radius:18px;backdrop-filter:blur(16px);box-shadow:0 8px 28px #06151b33}
.tabs button{flex:1;white-space:nowrap;background:transparent!important;color:#f5f0e5!important;border:1px solid transparent!important;box-shadow:none!important;padding:11px 9px!important;border-radius:12px!important}
.tabs button.active{background:rgba(233,207,154,.2)!important;border-color:#e9cf9a66!important;color:#ffe4ae!important}
.card{background:var(--glass)!important;border:1px solid var(--softline)!important;border-radius:23px!important;padding:clamp(17px,3vw,25px)!important;margin-bottom:16px!important;box-shadow:0 14px 42px #06151b35!important;backdrop-filter:blur(16px)!important}
.card h2{font-size:19px!important;color:#f7e8c8!important;margin:0 0 15px!important}
.grid{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))!important;gap:9px!important}
.area{min-height:0!important;display:grid;grid-template-columns:42px 1fr;grid-template-rows:auto auto;align-items:center;column-gap:12px;background:rgba(255,255,255,.075)!important;border:1px solid rgba(255,255,255,.1)!important;border-radius:17px!important;padding:14px 15px!important;margin:0!important;box-shadow:none!important}
.area>span:first-child{grid-row:1/3;width:40px;height:40px;display:grid;place-items:center;border-radius:50%;background:rgba(233,207,154,.15);font-size:20px}
.area strong{margin:0!important;font-size:15px;color:#fff!important}
.area .muted{font-size:12px!important;color:#e6dfd1!important}
.area .bar{grid-column:2;margin:6px 0 0!important;height:4px!important}
.bar{background:#ffffff25!important}.bar i{background:linear-gradient(90deg,#c5a66f,#f4e2b9)!important}
.goal{border-color:rgba(255,255,255,.13)!important;padding:15px 0!important}
.goal b{color:#fff}.goal .muted{color:#d9d5ca!important}
label{color:#e8dcc4!important}
input,textarea,select{border:1px solid rgba(255,255,255,.22)!important;border-radius:13px!important;background:rgba(245,244,235,.95)!important;color:#182a2d!important}
button{transition:transform .15s ease,background .15s ease}
button:active{transform:scale(.98)}
button.primary,.primary{background:linear-gradient(135deg,#f0d9a9,#d6b77d)!important;color:#1e2d2d!important;border:0!important}
.actions button{background:rgba(233,207,154,.16)!important;color:#f5dfb5!important;border:1px solid #e9cf9a55!important}
.empty{background:rgba(255,255,255,.075)!important;border:1px dashed rgba(255,255,255,.2);border-radius:16px!important;color:#f4eddf!important}
.note{color:#ddd5c6!important;padding:10px 0 24px}
.hidden{display:none!important}
@media(max-width:650px){
 .wrap{padding:12px!important}
 .hero{border-radius:22px!important;padding:18px!important}
 .hero h1{margin-top:17px!important}
 .stats{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important}
 .stat{border-left:0!important;border-bottom:1px solid var(--softline)!important;padding:9px!important}
 .tabs{top:5px;overflow-x:auto}.tabs button{flex:0 0 auto;font-size:13px!important}
 .grid{grid-template-columns:1fr!important}
}



/* Live weather from DEAN's 3D world (Open-Meteo) */
.weather-dock{grid-column:1/-1!important;display:flex;align-items:center;gap:14px;margin-top:2px;padding:13px 16px;border:1px solid rgba(217,189,131,.23);border-radius:12px;background:linear-gradient(100deg,rgba(217,189,131,.10),rgba(255,255,255,.025));color:#e8eee7}
.weather-symbol{font-size:27px;line-height:1}
.weather-dock b{display:block;font-size:21px;font-weight:600;color:#f1d9a6;font-variant-numeric:tabular-nums}
.weather-dock small{display:block;color:#b8c6bd;font-size:11px;margin-top:2px}
.weather-extra{font-size:12px;color:#c4d0c8;border-right:1px solid var(--edge);padding-right:14px}
.weather-updated{margin-right:auto;font-size:10px;color:#81928b}
@media(max-width:560px){.weather-dock{gap:9px;padding:10px}.weather-extra{font-size:10px;padding-right:8px}.weather-updated{display:none}}

/* DEAN DESKTOP WORKSPACE — app-like computer interface */
:root{--desk:#0b151b;--panel:rgba(17,31,39,.92);--panel2:rgba(24,42,50,.88);--edge:rgba(214,226,220,.13);--accent:#d9bd83}
html,body{min-height:100%;background:var(--desk)!important;color:#e9eee9!important}
body{overflow-x:hidden}
#deanWorld{position:fixed!important;inset:0 0 0 auto!important;width:100%!important;height:100%!important;z-index:-2!important;opacity:.26!important;filter:saturate(.72) brightness(.7)}
.wrap{width:auto!important;max-width:none!important;min-height:100vh;margin:0 236px 0 0!important;padding:28px 34px 48px!important;background:linear-gradient(115deg,rgba(8,18,23,.90),rgba(8,18,23,.72))!important;z-index:1!important}
.tabs{position:fixed!important;z-index:20!important;right:0!important;top:0!important;bottom:0!important;width:218px!important;margin:0!important;padding:28px 16px!important;display:flex!important;flex-direction:column!important;justify-content:flex-start!important;gap:9px!important;overflow:visible!important;background:rgba(10,22,28,.97)!important;border-left:1px solid var(--edge)!important;box-shadow:-18px 0 55px #0003!important}
.tabs:before{content:"DEAN";display:block;color:#f2e6c9;font-size:23px;font-weight:800;letter-spacing:5px;padding:8px 12px 2px}
.tabs:after{content:"LIFE WORKSPACE  ·  PERSONAL OS";display:block;order:9;margin-top:auto;padding:16px 10px 8px;border-top:1px solid var(--edge);font-size:9px;letter-spacing:1.4px;line-height:1.8;color:#8e9e9d}
.tabs button{width:100%!important;text-align:right!important;border:1px solid transparent!important;border-radius:10px!important;background:transparent!important;color:#aebbb7!important;padding:14px 13px!important;box-shadow:none!important;font-size:14px!important}
.tabs button:hover{background:#ffffff0b!important;color:#fff!important}
.tabs button.active{background:linear-gradient(90deg,rgba(217,189,131,.18),rgba(217,189,131,.05))!important;border-color:rgba(217,189,131,.25)!important;color:#f0d9a9!important;box-shadow:inset -3px 0 #d9bd83!important}
.hero{display:grid!important;grid-template-columns:1fr auto!important;align-items:center!important;gap:12px 24px!important;padding:24px 28px!important;margin-bottom:22px!important;border-radius:16px!important;background:linear-gradient(115deg,rgba(23,43,49,.96),rgba(14,28,35,.92))!important;border:1px solid var(--edge)!important;box-shadow:0 18px 50px #0002!important}
.hero>.row{grid-column:1/-1!important;padding-bottom:14px!important;border-bottom:1px solid var(--edge)!important}
.hero h1{font-size:clamp(25px,3vw,36px)!important;margin:6px 0!important;letter-spacing:-.5px}
.hero>p{margin:4px 0!important;max-width:650px!important;color:#b8c4bf!important}
.hero .muted{color:#aab9b3!important}
.world-meta strong{color:#f1d9a6!important;font-variant-numeric:tabular-nums}
.logo{background:linear-gradient(145deg,#d9bd83,#8d7750)!important;color:#17252a!important;border-radius:10px!important}
.stats{grid-column:1/-1!important;display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:0!important;margin-top:10px!important;border-top:1px solid var(--edge)!important}
.stat{background:transparent!important;border:0!important;border-left:1px solid var(--edge)!important;border-radius:0!important;padding:14px 18px 4px!important}
.stat:last-child{border-left:0!important}
.stat b{font-size:27px!important;color:#f0d8a7!important;font-weight:500!important}
.stat .muted{font-size:12px!important}
section{min-height:420px}
.card{background:rgba(16,30,37,.91)!important;border:1px solid var(--edge)!important;border-radius:14px!important;padding:22px 24px!important;margin-bottom:16px!important;box-shadow:0 12px 36px #0002!important;backdrop-filter:blur(16px)!important}
.card h2{font-size:16px!important;color:#f0dfbd!important;font-weight:600!important;margin:0 0 18px!important}
#overview{display:grid!important;grid-template-columns:minmax(0,1.65fr) minmax(280px,.85fr)!important;gap:16px!important;align-items:start!important}
#overview>.card{margin:0!important;min-width:0!important}
#overview>.card:first-child{grid-row:span 2!important}
.grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:0!important;margin-top:14px!important}
.area{display:grid!important;grid-template-columns:36px 1fr auto!important;align-items:center!important;gap:5px 10px!important;min-height:78px!important;margin:0!important;padding:14px 8px!important;border:0!important;border-bottom:1px solid var(--edge)!important;border-radius:0!important;background:transparent!important;box-shadow:none!important}
.area>span:first-child{grid-row:span 2!important;font-size:22px!important}
.area strong{margin:0!important;font-size:14px!important}
.area .muted{font-size:11px!important}
.area .bar{grid-column:2/-1!important;margin:4px 0 0!important;height:4px!important}
.bar{background:#ffffff16!important}.bar i{background:linear-gradient(90deg,#9eaa82,#e2c98f)!important}
.goal{border-color:var(--edge)!important;padding:16px 0!important}
input,textarea,select{background:#0b1a21!important;color:#edf1e9!important;border:1px solid #ffffff22!important;border-radius:9px!important}
input::placeholder,textarea::placeholder{color:#778984!important}
button{border-radius:9px!important}
.primary,.tabs button.active{background:#d9bd83!important;color:#18262b!important}
.actions button{background:#263b40!important;color:#e8d8b5!important}
.empty{background:#ffffff08!important;color:#aebbb7!important;border:1px dashed var(--edge)!important}
.note{color:#71827d!important}
@media(max-width:900px){
 .wrap{margin:0!important;padding:16px!important;padding-top:90px!important}
 .tabs{top:0!important;right:0!important;left:0!important;bottom:auto!important;width:100%!important;height:auto!important;min-height:66px!important;padding:9px 12px!important;flex-direction:row!important;align-items:center!important;gap:6px!important;border-left:0!important;border-bottom:1px solid var(--edge)!important;overflow-x:auto!important}
 .tabs:before{font-size:15px!important;padding:0 8px!important;letter-spacing:2px!important}
 .tabs:after{display:none!important}
 .tabs button{width:auto!important;white-space:nowrap!important;padding:10px 11px!important;font-size:12px!important}
 #overview{grid-template-columns:1fr!important}
 #overview>.card:first-child{grid-row:auto!important}
}
@media(max-width:560px){
 .wrap{padding:12px!important;padding-top:82px!important}
 .hero{padding:17px!important;grid-template-columns:1fr!important}
 .stats{grid-template-columns:repeat(2,minmax(0,1fr))!important}
 .stat{border-bottom:1px solid var(--edge)!important}
 .grid{grid-template-columns:1fr!important}
 .card{padding:17px!important}
 .tabs:before{display:none!important}
}


/* DEAN — final visual pass based on the two selected left-side concepts */
html{background:#07131b!important}
body{background:transparent!important;isolation:isolate!important}
#deanWorld{z-index:0!important;opacity:.78!important;filter:saturate(1.12) brightness(.9) contrast(1.04)!important}
.wrap{position:relative!important;z-index:2!important;background:linear-gradient(115deg,rgba(7,18,27,.70),rgba(7,18,27,.48))!important;backdrop-filter:blur(1px)}
.tabs{z-index:30!important;background:linear-gradient(180deg,rgba(7,19,28,.96),rgba(9,27,35,.94))!important;border-left:1px solid rgba(224,194,130,.28)!important}
.tabs:before{color:#f4dfb4!important;letter-spacing:5px!important}
.hero{background:linear-gradient(115deg,rgba(9,28,39,.78),rgba(19,39,45,.58))!important;border:1px solid rgba(230,203,151,.34)!important;box-shadow:0 22px 65px rgba(0,0,0,.28),inset 0 1px rgba(255,255,255,.10)!important}
.hero>.row{border-bottom-color:rgba(230,203,151,.25)!important}
.card{background:linear-gradient(145deg,rgba(10,27,37,.88),rgba(15,34,42,.76))!important;border-color:rgba(231,204,153,.20)!important;box-shadow:0 18px 48px rgba(0,0,0,.22),inset 0 1px rgba(255,255,255,.045)!important}
.stat b{color:#f4d99e!important;text-shadow:0 2px 15px rgba(217,189,131,.18)}
.stat{border-left-color:rgba(230,203,151,.22)!important}
.weather-dock{background:linear-gradient(105deg,rgba(217,189,131,.17),rgba(10,28,37,.52))!important;border-color:rgba(235,207,155,.34)!important;box-shadow:inset 0 1px rgba(255,255,255,.08)!important}
.weather-dock b{font-size:25px!important;color:#ffe4ae!important}
.weather-symbol{filter:drop-shadow(0 2px 9px rgba(255,220,150,.35))}
.area{border-bottom-color:rgba(230,203,151,.16)!important}
.area:hover{background:rgba(230,203,151,.07)!important}
.primary{background:linear-gradient(135deg,#f0d59b,#c49b59)!important;color:#17262d!important}
@media(min-width:901px){
 .wrap{margin-right:236px!important;padding:30px clamp(28px,3vw,54px) 54px!important}
 .hero{min-height:250px!important}
 #overview{grid-template-columns:minmax(0,1.7fr) minmax(300px,.8fr)!important}
}
@media(max-width:900px){
 #deanWorld{opacity:1!important}
 .wrap{background:transparent!important}
}

</style><iframe id="deanWorld" title="DEAN 3D world" src="/life-preview" loading="eager" aria-hidden="true" onload="try{this.contentDocument.querySelector('.hud').style.display='none';this.contentDocument.querySelector('.status')?.remove()}catch(e){}"></iframe><main class="wrap"><header class="hero"><div class="row"><span class="brand"><span class="logo">✦</span><span>בניאל · יומן החיים שלי</span></span><div class="world-meta"><strong id="worldClock">--:--</strong><span id="worldDate"></span></div></div><h1>הדרך שלי, בקצב שלי</h1><div class="muted" id="today"></div><p class="muted">מסתכלים על התמונה הגדולה, מסמנים התקדמות ובונים את הדרך שלך בקצב שלך.</p><div class="stats"><div class="stat"><b id="goalCount">0</b><span class="muted">מטרות פעילות</span></div><div class="stat"><b id="avg">0%</b><span class="muted">התקדמות ממוצעת</span></div><div class="stat"><b id="checks">0</b><span class="muted">דיווחים החודש</span></div><div class="stat"><b id="wins">0</b><span class="muted">מטרות שהושלמו</span></div></div><div class="weather-dock" id="liveWeather" aria-live="polite"><span class="weather-symbol">🌤️</span><span><b id="weatherTemp">--°</b><small id="weatherCondition">מתחבר למזג האוויר…</small></span><span class="weather-extra" id="weatherDetails">מיקום · לחות · רוח</span><span class="weather-updated" id="weatherUpdated">עדכון אוטומטי</span></div></header>
<nav class="tabs"><button class="active" data-tab="overview">תמונה כללית</button><button data-tab="goals">מטרות ומדדים</button><button data-tab="daily">דיווח יומי</button><button data-tab="history">היסטוריה</button></nav>
<section id="overview"><div class="card"><div class="row"><h2>תחומי החיים</h2><button id="addArea">＋ תחום חדש</button></div><div class="grid" id="areas"></div></div><div class="card"><h2>דורש תשומת לב</h2><div id="attention"></div></div></section>
<section id="goals" class="hidden"><div class="card"><h2>הוספת מטרה</h2><label>שם המטרה</label><input id="goalName" placeholder="למשל: לחזור להתאמן בקביעות"><label>תחום</label><select id="goalArea"></select><label>איך מודדים הצלחה?</label><input id="goalMeasure" placeholder="למשל: 3 אימונים בשבוע"><label>יעד / תאריך</label><input id="goalTarget" placeholder="למשל: עד סוף החודש"><button class="primary" id="saveGoal">שמירת מטרה</button></div><div class="card"><h2>כל המטרות</h2><div id="goalList"></div></div></section>
<section id="daily" class="hidden"><div class="card"><h2>דיווח יומי קצר</h2><p class="muted">אין ציון על יום חלש. מתעדים כדי לראות את המציאות ולהתקדם.</p><label>תחום</label><select id="checkArea"></select><label>איך התקדם התחום היום? 0–100</label><input id="checkValue" type="range" min="0" max="100" value="50"><b id="rangeValue">50%</b><label>מה עשיתי בפועל?</label><textarea id="checkNote" rows="3"></textarea><label>מה הפריע או עיכב?</label><textarea id="checkBlock" rows="2"></textarea><button class="primary" id="saveCheck">שמירת דיווח</button><p id="checkSaved" class="muted"></p></div><div class="card"><h2>סיכום יום חופשי</h2><textarea id="daySummary" rows="3" placeholder="מה קרה היום? מה למדתי?"></textarea><button id="saveSummary">שמירת סיכום</button></div></section>
<section id="history" class="hidden"><div class="card"><h2>📈 מגמת ההתקדמות</h2><div id="trendChart"></div></div><div class="card"><h2>📚 סיכומי ימים</h2><div id="summaryList"></div></div><div class="card"><h2>היסטוריית דיווחים</h2><div id="historyList"></div></div></section>
<p class="note">הנתונים נשמרים במסד הנתונים של DEAN מאחורי ההתחברות. זהו בסיס ראשון שאפשר להרחיב: תחומים, מטרות, מדדים, דיווחים והיסטוריה.</p></main>
<script>
const csrf={{ csrf|tojson }};window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==$('deanWorld')?.contentWindow||e.data?.type!=='DEAN_WEATHER')return;const w=e.data.payload||{};$('weatherTemp').textContent=(w.temp??'--')+'°';$('weatherCondition').textContent=(w.icon||'🌤️')+' '+(w.condition||'מזג אוויר');$('weatherDetails').textContent=(w.place||'מיקום')+' · לחות '+(w.humidity??'--')+'% · רוח '+(w.wind??'--')+' קמ״ש · '+(w.low??'--')+'°–'+(w.high??'--')+'°';$('weatherUpdated').textContent='עודכן '+(w.updated||'עכשיו')+' · זריחה '+(w.sunrise||'--:--')+' שקיעה '+(w.sunset||'--:--');});window.addEventListener('message',e=>{if(e.origin===location.origin&&e.source===$('deanWorld')?.contentWindow&&e.data?.type==='DEAN_WEATHER_ERROR')$('weatherCondition').textContent='נתוני מזג האוויר לא זמינים כרגע';});let data={areas:[],goals:[],checks:[],summaries:[]};const $=x=>document.getElementById(x);const esc=s=>String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const now=new Date();$('today').textContent=now.toLocaleDateString('he-IL',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
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
function updateWorldClock(){const d=new Date();$('worldClock').textContent=d.toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'});$('worldDate').textContent=d.toLocaleDateString('he-IL',{weekday:'long',day:'numeric',month:'long'})}updateWorldClock();setInterval(updateWorldClock,15000);
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
