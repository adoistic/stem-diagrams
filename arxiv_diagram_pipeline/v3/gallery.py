"""Build and upload the shareable gallery.

One page at v3/gallery/index.html on the R2 public URL: pick a category, see
every diagram, click to view full-size or download, follow the arXiv source.
Reads v3/gallery/data.json (regenerated from the state DB as images upload).
"""

import json
import time
from pathlib import Path

import r2

R2_PUBLIC = "https://pub-4b177d3c9b154dfeb08296540e8242ee.r2.dev"
DISPLAY = {
    "semiconductor_engineering": "Semiconductor Engineering",
    "manufacturing_engineering": "Manufacturing Engineering",
    "robotics_automation": "Robotics & Automation",
    "utilities_power_systems": "Utilities & Power Systems",
    "telecommunications": "Telecommunications",
}
WORK = Path(__file__).resolve().parent / "work"

INDEX_HTML = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>STEM Diagrams — browse by field</title>
<style>
:root{--bg:#0f1420;--card:#161d2b;--ink:#e8ecf1;--muted:#9aa4b2;--line:#2a3140;--acc:#2a9d8f}
@media(prefers-color-scheme:light){:root{--bg:#fff;--card:#f7f9fb;--ink:#1a1a2e;--muted:#5a6472;--line:#e6e9ee}}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--ink)}
header{padding:26px 20px 10px;max-width:1200px;margin:0 auto}
h1{margin:0 0 4px;font-size:1.5rem}.sub{color:var(--muted);font-size:.95rem}
.bar{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);z-index:5;
padding:12px 20px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bar .wrap{max-width:1200px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px;align-items:center;width:100%}
button.cat{border:1px solid var(--line);background:var(--card);color:var(--muted);padding:7px 14px;
border-radius:20px;font-weight:600;font-size:.85rem;cursor:pointer}
button.cat.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.count{color:var(--muted);font-size:.85rem;margin-left:auto}
a.dl{margin-left:8px;font-size:.85rem;color:var(--acc);font-weight:600;text-decoration:none}
main{max-width:1200px;margin:0 auto;padding:16px 20px 60px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;cursor:pointer;
transition:transform .12s}.card:hover{transform:translateY(-3px)}
.card img{width:100%;height:150px;object-fit:contain;background:#fff;display:block;padding:6px}
.card .m{padding:8px 10px;font-size:.72rem;color:var(--muted)}
.lb{position:fixed;inset:0;background:rgba(8,12,20,.9);display:none;align-items:center;justify-content:center;
z-index:20;padding:20px}.lb.on{display:flex}.lb .inner{max-width:900px;width:100%;max-height:92vh;overflow:auto;
background:var(--bg);border-radius:14px}.lb img{width:100%;background:#fff;border-radius:14px 14px 0 0;
max-height:70vh;object-fit:contain;padding:10px}.lb .c{padding:14px 18px}.lb a{color:var(--acc)}
.lb .x{position:fixed;top:16px;right:22px;color:#fff;font-size:2rem;cursor:pointer}
.more{margin:24px auto;display:block;padding:10px 20px;border-radius:10px;border:1px solid var(--line);
background:var(--card);color:var(--ink);font-weight:600;cursor:pointer}
</style></head><body>
<header><h1>STEM Diagrams</h1><div class=sub id=sub>Loading…</div></header>
<div class=bar><div class=wrap id=cats></div></div>
<main><div class=grid id=grid></div><button class=more id=more style=display:none>Show more</button></main>
<div class=lb id=lb><span class=x onclick="lb.classList.remove('on')">&times;</span>
<div class=inner><img id=lbimg><div class=c id=lbc></div></div></div>
<script>
let DATA=null,cat=null,shown=0,PAGE=60;
const cats=document.getElementById('cats'),grid=document.getElementById('grid'),
sub=document.getElementById('sub'),more=document.getElementById('more'),lb=document.getElementById('lb');
function fmt(n){return n.toLocaleString()}
function render(reset){
 if(reset){grid.innerHTML='';shown=0}
 const items=DATA.images.filter(x=>!cat||x.category===cat);
 const slice=items.slice(shown,shown+PAGE);
 for(const it of slice){
  const d=document.createElement('div');d.className='card';
  d.innerHTML=`<img loading=lazy src="${DATA.base}/${it.url}"><div class=m>${DATA.display[it.category]} · p${it.page}</div>`;
  d.onclick=()=>{document.getElementById('lbimg').src=`${DATA.base}/${it.url}`;
   document.getElementById('lbc').innerHTML=`${DATA.display[it.category]} · page ${it.page} ·
   <a href="https://arxiv.org/abs/${it.arxiv_id}" target=_blank>arXiv:${it.arxiv_id}</a> ·
   <a href="${DATA.base}/${it.url}" download>download</a>`;lb.classList.add('on')};
  grid.appendChild(d);
 }
 shown+=slice.length;more.style.display=shown<items.length?'block':'none';
 sub.textContent=`${fmt(DATA.images.length)} diagrams across ${Object.keys(DATA.display).length} fields · updated ${DATA.updated}`;
}
function setCat(c){cat=c;[...cats.children].forEach(b=>b.classList.toggle('on',b.dataset.c===(c||'')));render(true)}
more.onclick=()=>render(false);
fetch('data.json?t='+Date.now()).then(r=>r.json()).then(d=>{
 DATA=d;
 const counts={};d.images.forEach(x=>counts[x.category]=(counts[x.category]||0)+1);
 const mk=(label,c)=>{const b=document.createElement('button');b.className='cat'+(c===null?' on':'');
  b.dataset.c=c||'';b.textContent=c?`${d.display[c]} (${fmt(counts[c]||0)})`:`All (${fmt(d.images.length)})`;
  b.onclick=()=>setCat(c);return b};
 cats.appendChild(mk('All',null));
 Object.keys(d.display).forEach(c=>cats.appendChild(mk(c,c)));
 render(true);
});
</script></body></html>"""


def build_and_upload(conn):
    rows = conn.execute(
        "SELECT name, field, arxiv_id, page FROM images WHERE status='uploaded' "
        "ORDER BY field, name").fetchall()
    images = [{"url": f"v3/img/{f}/{n}", "category": f, "arxiv_id": a, "page": p}
              for (n, f, a, p) in rows]
    data = {"base": R2_PUBLIC, "display": DISPLAY,
            "updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "images": images}
    gdir = WORK / "gallery"
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "data.json").write_text(json.dumps(data))
    (gdir / "index.html").write_text(INDEX_HTML)
    ok1, _ = r2.put(gdir / "data.json", "v3/gallery/data.json", "application/json")
    ok2, _ = r2.put(gdir / "index.html", "v3/gallery/index.html", "text/html")
    return ok1 and ok2, len(images)
