"""Render the screen as a self-contained, sortable/filterable HTML page."""
import json
from pathlib import Path

import pandas as pd

WORK = Path("/home/claude/mbf/work")
OUT = Path("/home/claude/mbf/out")

d = pd.read_parquet(WORK / "screen_today.parquet")
asof = pd.Timestamp(d["last_date"].max()).date()

cols = ["symbol", "name", "sector_name", "price", "score", "data_cov", "why",
        "caution", "pe_now", "pb_now", "roe", "off_hi250", "mom60", "atr_pct",
        "turnover20", "suggested_stop", "suggested_target", "shares_30k",
        "days_since_filing", "verify"]
t = d[cols].copy()
t["sector_name"] = t["sector_name"].fillna("—").str.title()
t["name"] = t["name"].fillna("")
for c in ("pe_now", "pb_now", "roe", "off_hi250", "mom60", "atr_pct",
          "price", "suggested_stop", "suggested_target", "score", "data_cov"):
    t[c] = pd.to_numeric(t[c], errors="coerce").round(3)
t["turnover20"] = (t["turnover20"] / 1e6).round(2)
t["days_since_filing"] = pd.to_numeric(t["days_since_filing"], errors="coerce")
t = t.where(pd.notna(t), None)
rows = json.loads(t.to_json(orient="records"))
sectors = sorted({r["sector_name"] for r in rows if r["sector_name"]})

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi Beggar Finder — PSX screen __ASOF__</title>
<style>
:root{
  --bg:#f7f7f5; --card:#fff; --ink:#1a1a18; --mut:#6b6b66; --line:#e3e3df;
  --pos:#1c7d54; --neg:#b4342a; --warn:#8a5a00; --warnbg:#fdf6e3; --accent:#2b5d8a;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#16171a; --card:#1e2024; --ink:#e9e9e6; --mut:#9a9a94; --line:#2e3136;
  --pos:#4ec08a; --neg:#e8776c; --warn:#d9a640; --warnbg:#2a2418; --accent:#7fb2dd;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1560px;margin:0 auto;padding:22px 18px 70px}
h1{font-size:21px;margin:0 0 3px;letter-spacing:-.2px}
.sub{color:var(--mut);font-size:12.5px;margin-bottom:16px}
.note{background:var(--warnbg);border:1px solid var(--line);border-left:3px solid var(--warn);
  padding:11px 14px;border-radius:5px;font-size:12.5px;color:var(--ink);margin-bottom:16px}
.note b{color:var(--warn)}
.ctl{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:13px}
input,select{background:var(--card);color:var(--ink);border:1px solid var(--line);
  border-radius:5px;padding:6px 9px;font-size:13px;font-family:inherit}
input[type=text]{min-width:190px}
label.ck{display:flex;gap:5px;align-items:center;font-size:12.5px;color:var(--mut);cursor:pointer}
.cnt{color:var(--mut);font-size:12.5px;margin-left:auto}
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--line);border-radius:7px;overflow:hidden}
th{background:var(--bg);text-align:left;font-size:11px;text-transform:uppercase;
  letter-spacing:.055em;color:var(--mut);padding:9px 10px;border-bottom:1px solid var(--line);
  cursor:pointer;white-space:nowrap;position:sticky;top:0;z-index:2}
th:hover{color:var(--ink)}
td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px}
tr:last-child td{border-bottom:none}
.sym{font-weight:650;font-size:14px;letter-spacing:-.1px}
.nm{color:var(--mut);font-size:11.5px;display:block;max-width:210px}
.sec{color:var(--mut);font-size:11px}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.why{max-width:430px;font-size:12.5px;line-height:1.48}
.flag{max-width:290px;font-size:11.5px;color:var(--warn);line-height:1.45}
.pos{color:var(--pos)} .neg{color:var(--neg)}
.bar{position:relative;min-width:64px}
.bar i{display:block;height:4px;background:var(--accent);border-radius:2px;margin-top:3px}
.lvl{font-size:11.5px;color:var(--mut);white-space:nowrap}
.lvl b{color:var(--ink);font-weight:600}
.badge{display:inline-block;background:var(--bg);border:1px solid var(--line);
  border-radius:3px;padding:0 5px;font-size:10.5px;color:var(--mut);margin-left:5px}
.vfy td{opacity:.62}
footer{margin-top:22px;color:var(--mut);font-size:11.5px;line-height:1.7}
</style></head><body><div class="wrap">
<h1>Multi Beggar Finder</h1>
<div class="sub">PSX research funnel &middot; prices as of <b>__ASOF__</b> &middot;
__N__ tradeable names screened from 641 pulled</div>

<div class="note">
<b>Read this first.</b> This is a shortlist to research, not a buy list. None of these
components has demonstrated out-of-sample edge — the one that survived holdout testing
was deep-drawdown mean reversion (+6.5% CAGR vs +0.2% random), and it carries the
heaviest weight at 28%. Base rate for any liquid PSX stock touching +10% within 60
trading days is <b>65%</b>; doing it before falling 8% is only <b>44%</b>.
Rows greyed out at the bottom need a corporate-action check before their ratios mean
anything. Not investment advice.
</div>

<div class="ctl">
  <input type="text" id="q" placeholder="Search symbol or name…">
  <select id="sec"><option value="">All sectors</option>__SECTORS__</select>
  <select id="pmax"><option value="">Any price</option>
    <option value="10">under Rs 10</option><option value="30">under Rs 30</option>
    <option value="75">under Rs 75</option><option value="200">under Rs 200</option></select>
  <select id="smin"><option value="0">Any score</option><option value="55">score 55+</option>
    <option value="62">score 62+</option><option value="68">score 68+</option></select>
  <label class="ck"><input type="checkbox" id="clean" checked> hide names needing verification</label>
  <label class="ck"><input type="checkbox" id="nocaut"> hide any with caution flags</label>
  <label class="ck"><input type="checkbox" id="cov"> require 80%+ data coverage</label>
  <span class="cnt" id="cnt"></span>
</div>

<table><thead><tr>
  <th data-k="score">Score</th><th data-k="symbol">Symbol</th>
  <th data-k="price" class="num">Price</th>
  <th data-k="pe_now" class="num">P/E</th><th data-k="pb_now" class="num">P/B</th>
  <th data-k="roe" class="num">ROE</th>
  <th data-k="off_hi250" class="num">off 12m hi</th>
  <th data-k="mom60" class="num">60d</th>
  <th data-k="turnover20" class="num">Rs m/day</th>
  <th data-k="why">Why it is on the list</th>
  <th data-k="caution">Check before you act</th>
  <th data-k="atr_pct">Levels &middot; Rs 30k</th>
</tr></thead><tbody id="tb"></tbody></table>

<footer>
Score components and weights: drawdown vs 12-month high 28%, year-on-year quarterly EPS
surprise 20%, P/B vs own 5-year median 15%, earnings yield 12%, P/B vs sector 10%,
sales growth 8%, ROE 7%. Missing inputs score neutral, and the
&ldquo;data coverage&rdquo; badge shows how much of each score rests on real data.<br>
Suggested stop is 2.5&times;ATR20 below price and target 3.0&times;ATR20 above — geometry chosen
because the median PSX stock moves 4.19% a day, so a conventional 8% stop sits inside the
noise and loses 0.95% per trade on random entries.<br>
Signals shown as cautions were measured as <i>negative</i> edge: volume expansion &minus;11.2%
(z&nbsp;=&nbsp;&minus;7.8), 60-day momentum chasing &minus;3.4% (z&nbsp;=&nbsp;&minus;16.0),
PSX unusual-movement letters &minus;7.9% (z&nbsp;=&nbsp;&minus;3.8).
</footer>
</div>
<script>
const D=__DATA__;
const f=(v,d=2)=>v==null||isNaN(v)?'&ndash;':(+v).toFixed(d);
const pc=v=>v==null||isNaN(v)?'&ndash;':(v*100).toFixed(0)+'%';
const sgn=v=>v==null||isNaN(v)?'':(v<0?'neg':'pos');
let sk='score', sd=-1;
function draw(){
  const q=document.getElementById('q').value.toLowerCase().trim();
  const sc=document.getElementById('sec').value;
  const pm=parseFloat(document.getElementById('pmax').value)||1e9;
  const sm=parseFloat(document.getElementById('smin').value)||0;
  const cl=document.getElementById('clean').checked;
  const nc=document.getElementById('nocaut').checked;
  const cv=document.getElementById('cov').checked;
  let r=D.filter(x=>{
    if(cl&&x.verify)return false;
    if(nc&&x.caution)return false;
    if(cv&&(x.data_cov||0)<80)return false;
    if(x.price>pm)return false;
    if((x.score||0)<sm)return false;
    if(sc&&x.sector_name!==sc)return false;
    if(q&&!((x.symbol||'').toLowerCase().includes(q)||(x.name||'').toLowerCase().includes(q)))return false;
    return true;});
  r.sort((a,b)=>{let u=a[sk],v=b[sk];
    if(u==null)return 1; if(v==null)return -1;
    return typeof u==='string'?sd*u.localeCompare(v):sd*(u-v);});
  document.getElementById('cnt').textContent=r.length+' of '+D.length+' shown';
  document.getElementById('tb').innerHTML=r.map(x=>`
   <tr class="${x.verify?'vfy':''}">
    <td class="bar"><b>${f(x.score,1)}</b><i style="width:${Math.max(4,(x.score||0))}%"></i>
      <div class="sec">${f(x.data_cov,0)}% data</div></td>
    <td><span class="sym">${x.symbol}</span><span class="nm">${x.name||''}</span>
      <span class="sec">${x.sector_name||''}</span></td>
    <td class="num">${f(x.price)}</td>
    <td class="num">${f(x.pe_now,1)}</td>
    <td class="num">${f(x.pb_now)}</td>
    <td class="num">${x.roe==null?'&ndash;':f(x.roe,0)+'%'}</td>
    <td class="num ${sgn(x.off_hi250)}">${pc(x.off_hi250)}</td>
    <td class="num ${sgn(x.mom60)}">${pc(x.mom60)}</td>
    <td class="num">${f(x.turnover20,1)}</td>
    <td class="why">${x.why||''}</td>
    <td class="flag">${x.caution||''}</td>
    <td class="lvl">stop <b>${f(x.suggested_stop)}</b> &middot; target <b>${f(x.suggested_target)}</b>
      <br>ATR ${pc(x.atr_pct)}/day<span class="badge">${x.shares_30k} sh</span></td>
   </tr>`).join('');
}
document.querySelectorAll('th').forEach(th=>th.onclick=()=>{
  const k=th.dataset.k; sd=(k===sk)?-sd:(k==='symbol'||k==='why'||k==='caution'?1:-1); sk=k; draw();});
['q','sec','pmax','smin','clean','nocaut','cov'].forEach(id=>{
  const e=document.getElementById(id);
  e.addEventListener(e.type==='checkbox'?'change':'input',draw);
  e.addEventListener('change',draw);});
draw();
</script></body></html>"""

html = (HTML.replace("__DATA__", json.dumps(rows))
            .replace("__ASOF__", str(asof))
            .replace("__N__", str(len(rows)))
            .replace("__SECTORS__", "".join(f'<option>{s}</option>' for s in sectors)))
p = OUT / "mbf_screen.html"
p.write_text(html, encoding="utf-8")
print(f"wrote {p}  ({p.stat().st_size/1024:.0f} KB, {len(rows)} rows)")
