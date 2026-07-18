export const APP_HTML = `<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>STEM Diagrams - members</title>
<style>
:root{--bg:#0f1420;--card:#161d2b;--ink:#e8ecf1;--muted:#9aa4b2;--line:#2a3140;--acc:#2a9d8f;--err:#e76f51}
@media(prefers-color-scheme:light){:root{--bg:#fff;--card:#f7f9fb;--ink:#1a1a2e;--muted:#5a6472;--line:#e6e9ee}}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--acc)}
/* auth */
#auth{max-width:380px;margin:8vh auto;padding:0 20px}
#auth h1{font-size:1.5rem;margin:0 0 4px}#auth .sub{color:var(--muted);margin:0 0 24px}
.field{margin-bottom:12px}.field input{width:100%;padding:11px 13px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:1rem}
.btn{width:100%;padding:12px;border:none;border-radius:10px;background:var(--acc);color:#fff;font-weight:700;font-size:1rem;cursor:pointer}
.btn:disabled{opacity:.6}
.toggle{margin-top:16px;color:var(--muted);font-size:.9rem;text-align:center}.toggle a{cursor:pointer;font-weight:600}
.msg{margin:10px 0;font-size:.9rem;min-height:1.2em}.msg.err{color:var(--err)}
/* app */
#app{display:none}
.topbar{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);z-index:6}
.topbar .wrap{max-width:1200px;margin:0 auto;padding:12px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.topbar h2{margin:0;font-size:1.1rem}
.who{color:var(--muted);font-size:.85rem}
.counts{color:var(--muted);font-size:.85rem;margin-left:auto}
.counts b{color:var(--ink)}
.dl{background:var(--acc);color:#fff;border:none;border-radius:9px;padding:9px 16px;font-weight:700;font-size:.9rem;cursor:pointer}
.dl:disabled{opacity:.6}
.lo{background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:9px;padding:9px 12px;font-size:.85rem;cursor:pointer}
.prog{max-width:1200px;margin:0 auto;padding:0 20px}.prog .bar{height:6px;background:var(--card);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-top:8px;display:none}.prog .fill{height:100%;background:var(--acc);width:0;transition:width .3s}
.prog .note{color:var(--muted);font-size:.82rem;margin-top:6px;min-height:1em}
.filters{max-width:1200px;margin:0 auto;padding:14px 20px 0;display:flex;flex-wrap:wrap;gap:8px}
.filters button{border:1px solid var(--line);background:var(--card);color:var(--muted);padding:7px 13px;border-radius:20px;font-size:.85rem;font-weight:600;cursor:pointer}
.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.grid{max-width:1200px;margin:0 auto;padding:16px 20px 60px;display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;cursor:pointer;position:relative}
.card img{width:100%;height:150px;object-fit:contain;background:#fff;display:block;padding:6px}
.card .m{padding:8px 10px;font-size:.72rem;color:var(--muted)}
.card .got{position:absolute;top:6px;right:6px;background:var(--acc);color:#fff;font-size:.62rem;padding:2px 6px;border-radius:10px}
.more{margin:24px auto;display:block;padding:10px 20px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-weight:600;cursor:pointer}
.lb{position:fixed;inset:0;background:rgba(8,12,20,.9);display:none;align-items:center;justify-content:center;z-index:20;padding:20px}.lb.on{display:flex}
.lb .inner{max-width:900px;width:100%;max-height:92vh;overflow:auto;background:var(--bg);border-radius:14px}
.lb img{width:100%;background:#fff;border-radius:14px 14px 0 0;max-height:70vh;object-fit:contain;padding:10px}
.lb .c{padding:14px 18px;line-height:1.5}.lb .x{position:fixed;top:16px;right:22px;color:#fff;font-size:2rem;cursor:pointer}
</style></head><body>
<div id=auth>
  <h1>STEM Diagrams</h1>
  <p class=sub>Sign in to browse and download the diagram library.</p>
  <div class=field><input id=email type=email placeholder="Email" autocomplete=username></div>
  <div class=field><input id=password type=password placeholder="Password (min 6 chars)" autocomplete=current-password></div>
  <div class="msg" id=msg></div>
  <button class=btn id=submit>Log in</button>
  <div class=toggle id=toggle>New here? <a id=tlink>Create an account</a></div>
</div>

<div id=app>
  <div class=topbar><div class=wrap>
    <h2>STEM Diagrams</h2>
    <span class=who id=who></span>
    <span class=counts id=counts></span>
    <button class=dl id=dlbtn>Download all</button>
    <button class=lo id=lobtn>Log out</button>
  </div>
  <div class=prog><div class=bar id=bar><div class=fill id=fill></div></div><div class=note id=note></div></div>
  </div>
  <div class=filters id=filters></div>
  <div class=grid id=grid></div>
  <button class=more id=moreb style=display:none>Show more</button>
</div>

<div class=lb id=lb><span class=x id=lbx>&times;</span><div class=inner><img id=lbimg><div class=c id=lbc></div></div></div>

<script>
const $=id=>document.getElementById(id);
const DISPLAY={semiconductor_engineering:"Semiconductor Engineering",manufacturing_engineering:"Manufacturing Engineering",robotics_automation:"Robotics & Automation",utilities_power_systems:"Utilities & Power Systems",telecommunications:"Telecommunications"};
let mode="login",DATA=null,cat=null,shown=0,PAGE=60;

function setMode(m){mode=m;$('submit').textContent=m==="login"?"Log in":"Create account";
 $('password').autocomplete=m==="login"?"current-password":"new-password";
 $('toggle').innerHTML=m==="login"?'New here? <a id=tlink>Create an account</a>':'Have an account? <a id=tlink>Log in</a>';
 $('tlink').onclick=()=>setMode(m==="login"?"register":"login");$('msg').textContent='';}
$('tlink').onclick=()=>setMode("register");
$('submit').onclick=async()=>{
 const email=$('email').value.trim(),password=$('password').value;
 $('msg').className='msg';$('msg').textContent='...';$('submit').disabled=true;
 try{const r=await fetch('/api/'+mode,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email,password})});
  const j=await r.json();
  if(!r.ok){$('msg').className='msg err';$('msg').textContent=j.error||'Failed';}
  else{location.reload();}
 }catch(e){$('msg').className='msg err';$('msg').textContent='Network error';}
 $('submit').disabled=false;
};
['email','password'].forEach(id=>$(id).addEventListener('keydown',e=>{if(e.key==='Enter')$('submit').click()}));

$('lobtn').onclick=async()=>{await fetch('/api/logout',{method:'POST'});location.reload()};
$('lbx').onclick=()=>$('lb').classList.remove('on');

function imgSrc(key){return '/'+key.replace(/^v3\\//,'')}
function renderCounts(){$('counts').innerHTML=\`<b>\${DATA.total.toLocaleString()}</b> diagrams · <b>\${DATA.downloaded.toLocaleString()}</b> downloaded · <b>\${DATA.pending.toLocaleString()}</b> new\`;
 $('dlbtn').textContent=DATA.pending>0?\`Download \${DATA.pending.toLocaleString()} new\`:"All downloaded";$('dlbtn').disabled=DATA.pending===0;}
function buildFilters(){const f=$('filters');f.innerHTML='';const counts={};DATA.images.forEach(x=>counts[x.field]=(counts[x.field]||0)+1);
 const mk=c=>{const b=document.createElement('button');b.className=c===null?'on':'';b.textContent=c?\`\${DISPLAY[c]||c} (\${counts[c]||0})\`:\`All (\${DATA.images.length})\`;b.onclick=()=>{[...f.children].forEach(x=>x.classList.remove('on'));b.classList.add('on');cat=c;render(true)};return b};
 f.appendChild(mk(null));Object.keys(DISPLAY).forEach(c=>{if(counts[c])f.appendChild(mk(c))});}
function render(reset){const grid=$('grid');if(reset){grid.innerHTML='';shown=0}
 const items=DATA.images.filter(x=>!cat||x.field===cat);
 for(const it of items.slice(shown,shown+PAGE)){
  const d=document.createElement('div');d.className='card';
  d.innerHTML=\`<img loading=lazy src="\${imgSrc(it.key)}">\${it.downloaded?'<span class=got>✓</span>':''}<div class=m>\${DISPLAY[it.field]||it.field} · p\${it.page}</div>\`;
  d.onclick=()=>{$('lbimg').src=imgSrc(it.key);
   $('lbc').innerHTML=(it.caption?\`<div style=margin-bottom:8px>\${it.caption}</div>\`:'')+\`<div style="color:var(--muted);font-size:.85rem">\${DISPLAY[it.field]||it.field} · page \${it.page} · <a href="https://arxiv.org/abs/\${it.arxiv_id}" target=_blank>arXiv:\${it.arxiv_id}</a></div>\`;$('lb').classList.add('on')};
  grid.appendChild(d);}
 shown+=Math.min(PAGE,Math.max(0,items.length-shown));
 $('moreb').style.display=shown<items.length?'block':'none';}
$('moreb').onclick=()=>render(false);

$('dlbtn').onclick=async()=>{
 $('dlbtn').disabled=true;$('bar').style.display='block';let batch=0,got=0;const start=DATA.pending;
 try{
  while(true){
   const r=await fetch('/api/download',{method:'POST'});
   const ct=r.headers.get('content-type')||'';
   if(ct.includes('json')){await r.json();break;}
   const remaining=+r.headers.get('x-remaining'),added=+r.headers.get('x-added');
   const blob=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(blob);
   a.download=\`stem-diagrams-\${String(++batch).padStart(2,'0')}.zip\`;a.click();URL.revokeObjectURL(a.href);
   got+=added;$('fill').style.width=(start?Math.min(100,got/start*100):100)+'%';
   $('note').textContent=\`Downloaded \${got.toLocaleString()} of \${start.toLocaleString()} new diagrams (\${batch} zip\${batch>1?'s':''})...\`;
   if(remaining<=0)break;
  }
  $('note').textContent=got?\`Done — \${got.toLocaleString()} new diagrams in \${batch} zip file\${batch>1?'s':''}. Next time you'll only get newer ones.\`:'Nothing new to download.';
 }catch(e){$('note').textContent='Download error: '+e.message;}
 setTimeout(()=>{$('bar').style.display='none'},1500);await load();
};

async function load(){const r=await fetch('/api/manifest');if(!r.ok)return;DATA=await r.json();renderCounts();buildFilters();render(true);}
async function boot(){
 const me=await fetch('/api/me');
 if(me.ok){const j=await me.json();$('auth').style.display='none';$('app').style.display='block';$('who').textContent=j.email;await load();}
 else{$('auth').style.display='block';setMode('login');}
}
boot();
</script></body></html>`;
