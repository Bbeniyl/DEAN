"""DEAN cinematic 3D nature world preview."""
from flask import render_template_string

WORLD_PAGE = r"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>DEAN · העולם שלי</title>
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#9bb8c0;font-family:Arial,sans-serif;color:#fff}
#scene{position:fixed;inset:0}canvas{display:block;width:100%;height:100%}
.hud{position:fixed;inset:0;pointer-events:none;display:flex;flex-direction:column;justify-content:space-between;padding:calc(16px + env(safe-area-inset-top)) 16px calc(16px + env(safe-area-inset-bottom))}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}.brand{font-size:12px;letter-spacing:3px;font-weight:700;text-shadow:0 2px 14px #152b35}.clock{font-size:clamp(28px,7vw,46px);font-weight:300;text-shadow:0 2px 18px #172e39}.date{font-size:12px;opacity:.9;margin-top:3px}
.glass{background:linear-gradient(145deg,#0d273b88,#142d3a55);border:1px solid #ffffff45;box-shadow:0 12px 35px #07192325;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-radius:18px;padding:12px 15px}
.weather{font-size:13px;line-height:1.7;text-align:left;direction:rtl;min-width:112px}
.bottom{display:flex;align-items:flex-end;justify-content:space-between;gap:10px}.welcome{max-width:68%;}.welcome h1{font-size:clamp(24px,6vw,38px);margin:0 0 5px;font-weight:500;text-shadow:0 2px 15px #142b34}.welcome p{margin:0;font-size:13px;line-height:1.5;color:#f0f7f7}
.controls{pointer-events:auto;display:flex;flex-direction:column;gap:8px}.controls button{border:1px solid #ffffff66;border-radius:14px;background:#102b3c88;color:#fff;padding:11px 13px;font-size:12px;backdrop-filter:blur(12px);cursor:pointer}.controls button:active{transform:scale(.97)}
.status{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);font-size:13px;color:#fff;background:#102b3caa;padding:10px 14px;border-radius:14px;pointer-events:none;transition:opacity .5s}
@media(min-width:700px){.hud{padding:28px 34px}.welcome{max-width:460px}.glass{padding:15px 19px}}
</style>
</head>
<body>
<div id="scene"></div>
<div class="hud">
 <div class="top">
  <div><div class="brand">D E A N</div><div class="clock" id="clock">--:--</div><div class="date" id="date"></div></div>
  <div class="glass weather"><div id="weatherIcon">🌤️</div><div id="weatherText">טוען מזג אוויר…</div><div id="place">מזהה מיקום</div></div>
 </div>
 <div class="bottom">
  <div class="welcome"><h1>הדרך שלי, בקצב שלי</h1><p id="skyline">רגע לעצור, לנשום ולהמשיך בדרך.</p></div>
  <div class="controls"><button id="locate">⌖ עדכון מיקום ומזג אוויר</button><button id="return">↻ חזרה לנוף</button><a href="/life" style="pointer-events:auto;text-decoration:none;color:#fff;text-align:center;font-size:12px;padding:10px;background:#102b3c88;border:1px solid #ffffff66;border-radius:14px">יומן החיים ←</a></div>
 </div>
</div>
<div class="status" id="status">בונה את העולם שלך…</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script>
(()=> {
const host=document.getElementById('scene'),status=document.getElementById('status');
if(!window.THREE){status.textContent='לא ניתן לטעון כרגע את מנוע התלת־ממד';return}
const scene=new THREE.Scene();scene.background=new THREE.Color(0x9fc4d0);scene.fog=new THREE.Fog(0x9fc4d0,23,78);
const camera=new THREE.PerspectiveCamera(48,innerWidth/innerHeight,.1,150);camera.position.set(0,5.1,14.5);camera.lookAt(0,2.2,-2);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio,1.7));renderer.setSize(innerWidth,innerHeight);renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputEncoding=THREE.sRGBEncoding;host.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xd9efff,0x5a6445,1.0));
const sunLight=new THREE.DirectionalLight(0xffe1b1,2.1);sunLight.position.set(-8,13,7);sunLight.castShadow=true;sunLight.shadow.mapSize.set(1024,1024);sunLight.shadow.camera.left=-22;sunLight.shadow.camera.right=22;sunLight.shadow.camera.top=22;sunLight.shadow.camera.bottom=-22;scene.add(sunLight);
const mat=(color,rough=.9)=>new THREE.MeshStandardMaterial({color,roughness:rough});
const ground= new THREE.Mesh(new THREE.PlaneGeometry(100,100,1,1),mat(0x52764a));ground.rotation.x=-Math.PI/2;ground.position.y=-.15;ground.receiveShadow=true;scene.add(ground);
function hill(x,z,sx,sy,sz,color){const m=new THREE.Mesh(new THREE.SphereGeometry(1,32,22),mat(color));m.position.set(x,sy*.34,z);m.scale.set(sx,sy,sz);m.receiveShadow=true;m.castShadow=true;scene.add(m);return m}
hill(-15, -12,13,8,9,0x698c83);hill(13,-17,16,10,12,0x78988c);hill(-1,-27,24,13,9,0x8da99a);
const mound= new THREE.Mesh(new THREE.SphereGeometry(1,48,32),mat(0x64834e));mound.position.set(0,-1.4,1);mound.scale.set(19,4.5,12);mound.receiveShadow=true;scene.add(mound);
const pathMat=mat(0x9b8c6b);const path=new THREE.Mesh(new THREE.CircleGeometry(3.5,48),pathMat);path.rotation.x=-Math.PI/2;path.scale.set(1.6,2.8,1);path.position.set(1,-.06,2);scene.add(path);
function tree(x,z,h=4){const trunk=new THREE.Mesh(new THREE.CylinderGeometry(.13,.23,h*.48,8),mat(0x60452f));trunk.position.set(x,h*.24,z);trunk.castShadow=true;scene.add(trunk);for(let i=0;i<3;i++){const crown=new THREE.Mesh(new THREE.IcosahedronGeometry(h*(.22-i*.025),1),mat([0x426b45,0x557d4d,0x6b8c52][i]));crown.position.set(x+(i-1)*.22,h*.53+i*h*.12,z);crown.castShadow=true;crown.receiveShadow=true;scene.add(crown)}}
[[-9,-5,5],[-12,1,4],[-8,5,3.2],[9,-6,5],[12,-1,4.4],[8,3,3.3],[-5,-13,5],[6,-15,5.5]].forEach(v=>tree(...v));
function bush(x,z,s=1){const g=new THREE.Group();for(let i=0;i<5;i++){const b=new THREE.Mesh(new THREE.IcosahedronGeometry(.45*s,1),mat(i%2?0x577d49:0x719254));b.position.set((Math.random()-.5)*s,.25*s+(Math.random()*.2), (Math.random()-.5)*s);b.castShadow=true;g.add(b)}g.position.set(x,0,z);scene.add(g)}
for(let i=0;i<34;i++)bush((Math.random()-.5)*27,(Math.random()-.5)*24,.45+Math.random()*.6);
const flowerColors=[0xffd3df,0xffe5a0,0xffffff,0xc6b7ff];
for(let i=0;i<130;i++){const x=(Math.random()-.5)*26,z=(Math.random()-.5)*22;if(Math.abs(x)<3&&z>0)continue;const stem=new THREE.Mesh(new THREE.CylinderGeometry(.012,.018,.22,5),mat(0x3c693e));stem.position.set(x,.1,z);scene.add(stem);const f=new THREE.Mesh(new THREE.SphereGeometry(.075,8,7),mat(flowerColors[i%4]));f.position.set(x,.23,z);scene.add(f)}
// small rock and a traveler with a backpack
const rock=new THREE.Mesh(new THREE.DodecahedronGeometry(.85,1),mat(0x777a72));rock.scale.set(1.35,.65,1);rock.position.set(-1.5,.1,2.4);rock.castShadow=true;rock.receiveShadow=true;scene.add(rock);
const person=new THREE.Group();person.position.set(-1.65,.55,2.05);person.rotation.y=-.18;scene.add(person);
const body=new THREE.Mesh(new THREE.CapsuleGeometry(.28,.72,5,10),mat(0x344d54));body.position.set(0,.72,0);body.castShadow=true;person.add(body);
const head=new THREE.Mesh(new THREE.SphereGeometry(.22,18,16),mat(0xd5a27d));head.position.set(0,1.28,.02);person.add(head);
const pack=new THREE.Mesh(new THREE.BoxGeometry(.42,.55,.25),mat(0x9a6840));pack.position.set(0,.78,-.28);pack.castShadow=true;person.add(pack);
const legmat=mat(0x343d43);for(let x of [-.14,.14]){const leg=new THREE.Mesh(new THREE.CylinderGeometry(.085,.1,.48,8),legmat);leg.position.set(x,.23,0);person.add(leg)}
// volumetric-looking layered clouds
const clouds=[];function cloud(x,y,z,scale=1){const g=new THREE.Group();for(let i=0;i<7;i++){const c=new THREE.Mesh(new THREE.SphereGeometry(.8+Math.random()*.35,16,12),new THREE.MeshStandardMaterial({color:0xf4f5f1,roughness:1,transparent:true,opacity:.91}));c.position.set((Math.random()-.5)*2.6,Math.random()*.55,(Math.random()-.5)*.7);c.scale.set(1.4,.7,1);g.add(c)}g.position.set(x,y,z);g.scale.setScalar(scale);scene.add(g);clouds.push(g)}
cloud(-10,9,-17,1.4);cloud(2,10,-22,1.1);cloud(13,8,-16,1.5);cloud(-2,12,-30,1.2);
const sun=new THREE.Mesh(new THREE.SphereGeometry(.85,24,24),new THREE.MeshBasicMaterial({color:0xffe2a0}));sun.position.set(-8,10,-20);scene.add(sun);
const stars=new THREE.Group();for(let i=0;i<170;i++){const st=new THREE.Mesh(new THREE.SphereGeometry(.035,6,6),new THREE.MeshBasicMaterial({color:0xffffff}));st.position.set((Math.random()-.5)*85,10+Math.random()*28,-35-Math.random()*30);stars.add(st)}scene.add(stars);
const rain=new THREE.Group();const drops=[];for(let i=0;i<240;i++){const d=new THREE.Mesh(new THREE.CylinderGeometry(.012,.012,.32,4),new THREE.MeshBasicMaterial({color:0xcce7f3,transparent:true,opacity:.6}));d.position.set((Math.random()-.5)*38,Math.random()*17-1,(Math.random()-.5)*35);rain.add(d);drops.push(d)}scene.add(rain);
let weatherCode=1,cloudCover=20,precip=0,wind=0,lat=31.25,lon=34.78,placeName='המיקום שלך',sunrise='06:00',sunset='17:00';
function hexLerp(a,b,t){return new THREE.Color(a).lerp(new THREE.Color(b),Math.max(0,Math.min(1,t)))}
function applySky(){const now=new Date(),mins=now.getHours()*60+now.getMinutes(),rise=Number(sunrise.slice(0,2))*60+Number(sunrise.slice(3,5)),set=Number(sunset.slice(0,2))*60+Number(sunset.slice(3,5));let daylight=Math.max(0,Math.min(1,(mins-rise)/(set-rise)));let phase=mins<rise||mins>set?0:Math.sin(daylight*Math.PI);let dawn=Math.max(0,1-Math.min(Math.abs(mins-rise),Math.abs(mins-set))/110);let base=hexLerp(0x101c38,0x86b7c7,phase);base.lerp(new THREE.Color(0xf2a16f),dawn*.7);if(cloudCover>55)base.lerp(new THREE.Color(0x71818b),Math.min(.55,(cloudCover-55)/100));scene.background=base;scene.fog.color.copy(base);sun.visible=phase>.02;sun.position.set(-13+daylight*26,2+phase*12,-20);sunLight.position.copy(sun.position);sunLight.intensity=.25+phase*2.1;sunLight.color.set(dawn>.2?0xffb77d:0xffe2b8);stars.visible=phase<.08;stars.children.forEach(s=>s.material.opacity=1);clouds.forEach(c=>c.children.forEach(p=>p.material.color.set(cloudCover>60?0x9da9ae:0xf4f5f1)));rain.visible=precip>.05||[51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99].includes(weatherCode);document.getElementById('skyline').textContent=precip>.2?'הגשם יורד בעולם שלך. קח רגע לנשום.':phase<.08?'לילה שקט. הדרך ממשיכה גם מחר.':dawn>.4?'האור חוזר לאט, יום חדש מתחיל.':mins>set-100&&mins<set+40?'השמש יורדת, והנוף נצבע בזהב.':'רגע לעצור, לנשום ולהמשיך בדרך.'}
async function loadWeather(useGeo){try{if(useGeo&&navigator.geolocation){const pos=await new Promise((ok,no)=>navigator.geolocation.getCurrentPosition(ok,no,{enableHighAccuracy:false,timeout:9000}));lat=pos.coords.latitude;lon=pos.coords.longitude}
const url='https://api.open-meteo.com/v1/forecast?latitude='+lat+'&longitude='+lon+'&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,cloud_cover,wind_speed_10m&daily=sunrise,sunset&timezone=auto&forecast_days=1';
const r=await fetch(url);if(!r.ok)throw Error('weather');const d=await r.json();weatherCode=d.current.weather_code;cloudCover=d.current.cloud_cover;precip=d.current.precipitation;wind=d.current.wind_speed_10m;sunrise=d.daily.sunrise[0].slice(11,16);sunset=d.daily.sunset[0].slice(11,16);
const codes=weatherCode;const weatherMap={0:['☀️','בהיר'],1:['🌤️','בהיר בדרך כלל'],2:['⛅','מעונן חלקית'],3:['☁️','מעונן'],45:['🌫️','ערפל'],48:['🌫️','ערפל כבד'],51:['🌦️','טפטוף קל'],53:['🌦️','טפטוף'],55:['🌧️','טפטוף חזק'],56:['🌧️','טפטוף קופא'],57:['🌧️','טפטוף קופא חזק'],61:['🌧️','גשם קל'],63:['🌧️','גשם'],65:['🌧️','גשם חזק'],66:['🌧️','גשם קופא'],67:['🌧️','גשם קופא חזק'],71:['🌨️','שלג קל'],73:['🌨️','שלג'],75:['❄️','שלג כבד'],77:['🌨️','פתיתי שלג'],80:['🌦️','ממטרים קלים'],81:['🌧️','ממטרים'],82:['⛈️','ממטרים חזקים'],85:['🌨️','ממטרי שלג'],86:['❄️','ממטרי שלג חזקים'],95:['⛈️','סופת רעמים'],96:['⛈️','רעמים וברד'],99:['⛈️','סופת רעמים חזקה']};const mapped=weatherMap[codes]||[precip>0?'🌧️':cloudCover>65?'☁️':cloudCover>25?'⛅':'☀️',precip>0?'משקעים':cloudCover>65?'מעונן':cloudCover>25?'מעונן חלקית':'בהיר'];let icon=mapped[0],condition=mapped[1];document.getElementById('weatherIcon').textContent=icon;document.getElementById('weatherText').textContent=Math.round(d.current.temperature_2m)+'° · רוח '+Math.round(wind)+' קמ״ש';document.getElementById('place').textContent=placeName+' · זריחה '+sunrise+' שקיעה '+sunset;try{parent.postMessage({type:'DEAN_WEATHER',payload:{icon,condition,temp:Math.round(d.current.temperature_2m),wind:Math.round(wind),humidity:Math.round(d.current.relative_humidity_2m),high:Math.round(d.daily.temperature_2m_max[0]),low:Math.round(d.daily.temperature_2m_min[0]),place:placeName,sunrise,sunset,updated:new Date().toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'})}},location.origin)}catch(e){}applySky();}catch(e){document.getElementById('weatherText').textContent='מזג אוויר לא זמין כרגע';document.getElementById('place').textContent='מציג לפי השעון המקומי';try{parent.postMessage({type:'DEAN_WEATHER_ERROR'},location.origin)}catch(e){}applySky()}}
function clock(){const n=new Date();document.getElementById('clock').textContent=n.toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'});document.getElementById('date').textContent=n.toLocaleDateString('he-IL',{weekday:'long',day:'numeric',month:'long'});applySky()}
document.getElementById('locate').onclick=()=>{placeName='המיקום שלך';loadWeather(true)};document.getElementById('return').onclick=()=>{camera.position.set(0,5.1,14.5);camera.lookAt(0,2.2,-2)};
let tick=0;function animate(){requestAnimationFrame(animate);tick+=.008;clouds.forEach((c,i)=>c.position.x+=Math.sin(tick+i)*.0015);rain.children.forEach((d,i)=>{if(rain.visible){d.position.y-=.22;if(d.position.y<-.2){d.position.y=15;d.position.x=(Math.random()-.5)*38}}});person.rotation.y=-.18+Math.sin(tick*.3)*.025;renderer.render(scene,camera)}
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)});clock();loadWeather(true);setInterval(clock,15000);setInterval(()=>loadWeather(false),15*60*1000);animate();setTimeout(()=>{status.style.opacity='0';setTimeout(()=>status.remove(),700)},1400);
})();
</script>
</body></html>"""

def register_world_preview(app, require_login):
    @app.get("/life-preview")
    @require_login
    def life_world_preview():
        return render_template_string(WORLD_PAGE)
