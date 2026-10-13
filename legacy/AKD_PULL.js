/* ===================================================================
   Multi Beggar Finder — AKD data pull
   ===================================================================
   WHY THIS IS BROWSER JAVASCRIPT AND NOT PYTHON
   The AKD endpoints require your logged-in session cookie. Verified:
       /api/v3/market?path=/daily/ASTM      no cookie -> 401
       /announcements/NULL?...              no cookie -> empty
       /api/v3/company-statement?...        no cookie -> 401 EVEN WITH a
                                            valid bearer token
   So a standalone script would need your credentials or your Chrome cookie
   store. Running inside the page avoids both: nothing leaves your browser
   except the CSV files it saves.

   HOW TO USE
   1. Open  https://research.akdtrade.biz/screener  and make sure you're
      logged in.
   2. Press F12 -> Console tab.
   3. Paste this whole file, press Enter.
   4. Choose a mode when prompted in the console, e.g.
          MBF.prices()    ~4 min   prices + announcements (daily refresh)
          MBF.full()      ~25 min  everything (weekly/monthly)
   5. Files download to your Chrome download folder. Move them to
      D:\Investments\Multi Beggar Finder  and run  python refresh.py
   Chrome may show "Allow multiple downloads?" — click Allow.

   Leave the tab open and in the foreground while it runs.
   =================================================================== */
(() => {
"use strict";

const SLEEP = ms => new Promise(r => setTimeout(r, ms));
const PACE = 110;            // ms between requests — polite, not hammering
const RETRIES = 3;

const tok = () => {
  const m = document.querySelector('meta[name="access-token"]');
  return m ? m.content : null;
};

function q(v) {
  if (v === null || v === undefined) return "";
  const s = String(v).replace(/"/g, '""').replace(/[\r\n]+/g, " ");
  return /[",]/.test(s) ? '"' + s + '"' : s;
}

function save(name, text) {
  const b = new Blob([text], { type: "text/csv" });
  const u = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = u; a.download = name;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(u); a.remove(); }, 8000);
  console.log(`%c  saved ${name}  (${(b.size / 1048576).toFixed(2)} MB)`,
              "color:#2a7");
  return b.size;
}

async function getJSON(url, auth) {
  const h = { Accept: "application/json" };
  if (auth) {
    const t = tok();
    if (!t) throw new Error("access-token meta tag missing — are you logged in?");
    h.Authorization = "Bearer " + t;
  }
  let last;
  for (let i = 0; i < RETRIES; i++) {
    try {
      const r = await fetch(url, { headers: h });
      if (r.status === 401) throw new Error("401 — session expired, reload the page and log in again");
      if (r.status === 429 || r.status >= 500) { last = new Error(r.status); await SLEEP(1200 * (i + 1)); continue; }
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      last = e;
      if (String(e.message).startsWith("401")) throw e;
      await SLEEP(900 * (i + 1));
    }
  }
  console.warn("  give up:", url, last && last.message);
  return null;
}

const bar = (done, total, t0) => {
  const pctg = done / total;
  const el = (Date.now() - t0) / 1000;
  const eta = pctg > 0.01 ? Math.round(el / pctg - el) : 0;
  const filled = Math.round(pctg * 28);
  return `[${"#".repeat(filled)}${".".repeat(28 - filled)}] ${done}/${total}` +
         `  ${(pctg * 100).toFixed(1)}%  eta ${Math.floor(eta / 60)}m${String(eta % 60).padStart(2, "0")}s`;
};

/* ---------------------------------------------------------------- announcements
   Also yields the symbol universe, INCLUDING names that have stopped trading —
   which is what keeps the backtest free of survivorship bias.               */
const ANN_FIELDS = ["symbol", "date", "announcementType", "periodEndDate",
  "previousPeriodEndDate", "unconsolidatedSales", "unconsolidatedPat",
  "unconsolidatedQuarterEps", "unconsolidatedQuarterEpsYOY", "dividend", "bonus",
  "rightIssue", "rightPrice", "exDate", "book_closure_date_from",
  "book_closure_date_to", "revised", "heldDate", "title"];

const JUNK = new Set(["AAL", "EXCHANGE", "HUSS", "NAZC", "OPENFUND", "OTHER",
                      "SGABL", "PSX"]);

async function pullAnnouncements(fromYear) {
  const yNow = new Date().getFullYear();
  const rows = [ANN_FIELDS.join(",")];
  const syms = new Set();
  const years = [];
  for (let y = fromYear; y <= yNow; y++) years.push(y);
  const t0 = Date.now();
  console.log(`%cannouncements ${fromYear}-${yNow}`, "font-weight:bold");
  for (let i = 0; i < years.length; i++) {
    const y = years[i];
    const to = (y === yNow) ? new Date().toISOString().slice(0, 10) : `${y}-12-31`;
    const j = await getJSON(`/announcements/NULL?rangeFrom=${y}-01-01&rangeTo=${to}&type=ALL`);
    const arr = Array.isArray(j) ? j : ((j && j.data) || []);
    for (const a of arr) {
      if (a.symbol && !JUNK.has(a.symbol)) syms.add(a.symbol);
      rows.push(ANN_FIELDS.map(f =>
        q(f === "title" ? String(a.title || "").slice(0, 90) : a[f])).join(","));
    }
    console.log("  " + bar(i + 1, years.length, t0) + `   ${y}: ${arr.length}`);
    await SLEEP(350);
  }
  return { rows, symbols: [...syms].sort() };
}

/* ------------------------------------------------------------------ per-symbol */
async function pullPerSymbol(symbols, opts) {
  const px = ["symbol,date,open,high,low,close,volume,value"];
  const st = ["symbol,stype,year,quarter,period_end,field_key,field_label,value"];
  const fdm = ["symbol,year,quarter,period_end,field_key,field_label,value"];
  const pf = ["symbol,name,sector_code,sector_name,status,year_end,par_value," +
              "employees,capacity,capacity_util"];
  const noPrice = [];
  const t0 = Date.now();
  console.log(`%c${symbols.length} symbols  (prices${opts.statements ? " + statements" : ""}` +
              `${opts.profiles ? " + profiles/fundamentals" : ""})`, "font-weight:bold");

  for (let i = 0; i < symbols.length; i++) {
    const s = symbols[i], es = encodeURIComponent(s);

    const j = await getJSON(`/api/v3/market?path=/daily/${es}`);
    const a = (j && j.data) || [];
    if (!a.length) noPrice.push(s);
    for (const d of a)
      px.push([s, q(d.date), d.open, d.high, d.low, d.close, d.volume, d.value].join(","));
    await SLEEP(PACE);

    if (opts.statements) {
      for (const ty of ["income", "balance"]) {
        const r = await getJSON(
          `/api/v3/company-statement?symbol=${es}&interval=quarterly&type=${ty}`, true);
        const d = (r && r.data) || {}, P = d.periods || [], F = d.fields || [];
        for (const f of F) {
          if (f.is_heading) continue;
          const v = f.values || [];
          for (let k = 0; k < P.length; k++) {
            if (v[k] === null || v[k] === undefined) continue;
            st.push([s, ty, P[k].year, q(P[k].quarter), P[k].period_end,
                     q(f.key), q(f.label), v[k]].join(","));
          }
        }
        await SLEEP(PACE);
      }
    }

    if (opts.profiles) {
      const r = await getJSON(
        `/api/v3/company-statement?symbol=${es}&interval=annual&type=profile`, true);
      const d = (r && r.data) || {};
      if (d.symbol || d.name)
        pf.push([s, q(d.name), q(d.sector_code), q(d.sector_name), q(d.status),
                 q(d.year_end), d.par_value ?? "", d.employees ?? "",
                 q(d.capacity), q(d.capacity_util)].join(","));
      await SLEEP(PACE);
      const r2 = await getJSON(
        `/api/v3/company-statement?symbol=${es}&interval=annual&type=fundamentals`, true);
      const d2 = (r2 && r2.data) || {}, P = d2.periods || [], F = d2.fields || [];
      for (const f of F) {
        if (f.is_heading) continue;
        const v = f.values || [];
        for (let k = 0; k < P.length; k++) {
          if (v[k] === null || v[k] === undefined) continue;
          fdm.push([s, P[k].year, q(P[k].quarter), P[k].period_end,
                    q(f.key), q(f.label), v[k]].join(","));
        }
      }
      await SLEEP(PACE);
    }

    if ((i + 1) % 25 === 0 || i === symbols.length - 1)
      console.log("  " + bar(i + 1, symbols.length, t0) +
                  `   px:${px.length - 1}` +
                  (opts.statements ? ` st:${st.length - 1}` : "") +
                  (opts.profiles ? ` fd:${fdm.length - 1}` : ""));
  }
  return { px, st, fdm, pf, noPrice };
}

async function run(opts) {
  if (!tok()) {
    console.error("%cNot logged in (no access-token on this page). " +
      "Open https://research.akdtrade.biz/screener, log in, and re-paste.",
      "color:#c33;font-weight:bold");
    return;
  }
  const T0 = Date.now();
  console.log("%c=== Multi Beggar Finder pull ===", "font-weight:bold;font-size:13px");

  const sx = opts.suffix || "";      // "_TEST" for mini(), "" for real runs
  const fn = base => `mbf_${base}${sx}.csv`;

  const ann = await pullAnnouncements(opts.fromYear);
  if (opts.announcements) save(fn("announcements"), ann.rows.join("\n"));

  const symbols = opts.limit ? ann.symbols.slice(0, opts.limit) : ann.symbols;
  const r = await pullPerSymbol(symbols, opts);

  const uni = ["symbol,has_price"];
  const np = new Set(r.noPrice);
  for (const s of symbols) uni.push(`${s},${np.has(s) ? 0 : 1}`);

  await SLEEP(1500); save(fn("universe"), uni.join("\n"));
  await SLEEP(2500); save(fn("prices"), r.px.join("\n"));
  if (opts.statements) { await SLEEP(3000); save(fn("statements"), r.st.join("\n")); }
  if (opts.profiles) {
    await SLEEP(2500); save(fn("profiles"), r.pf.join("\n"));
    await SLEEP(2500); save(fn("fundamentals"), r.fdm.join("\n"));
  }

  const mins = ((Date.now() - T0) / 60000).toFixed(1);
  console.log(`%cDONE in ${mins} min — ${symbols.length} symbols, ` +
              `${r.noPrice.length} without price data.`,
              "color:#2a7;font-weight:bold;font-size:13px");
  console.log("%cMove the downloaded files to D:\\Investments\\Multi Beggar Finder " +
              "then run:  python refresh.py", "font-weight:bold");
}

/* fromYear is ALWAYS 2018, even for the quick daily run.
   The announcements file is not just news — it carries every dividend, bonus and
   rights ex-date, which is what de-adjusts AKD's total-return price series back
   to real prices, and it supplies the 5-year P/B medians. Pulling only recent
   years would overwrite that history with a stub and silently corrupt both.
   It is 9 requests / ~10 seconds, so there is no reason to trim it. */
window.MBF = {
  // daily: prices + FULL announcement history. Fundamentals move quarterly, so
  // the existing statements/profiles/fundamentals files are left untouched.
  prices: () => run({ fromYear: 2018, announcements: true,
                      statements: false, profiles: false }),
  // weekly/monthly: the lot.
  full: () => run({ fromYear: 2018, announcements: true,
                    statements: true, profiles: true }),
  // dry run on a few symbols — proves the whole chain including the downloads.
  // Writes *_TEST.csv so it can never clobber your real files.
  mini: (n = 3) => run({ fromYear: new Date().getFullYear(), announcements: false,
                         statements: true, profiles: true, limit: n,
                         suffix: "_TEST" }),
  // small smoke test before trusting a long run
  test: async () => {
    const t0 = Date.now();
    const j = await getJSON("/api/v3/market?path=/daily/ASTM");
    const s = await getJSON(
      "/api/v3/company-statement?symbol=ASTM&interval=quarterly&type=income", true);
    const a = await getJSON(
      "/announcements/NULL?rangeFrom=2026-08-01&rangeTo=2026-08-21&type=ALL");
    const arr = Array.isArray(a) ? a : ((a && a.data) || []);
    console.log("prices rows      :", (j && j.data || []).length);
    console.log("statement fields :", ((s && s.data || {}).fields || []).length);
    console.log("announcements    :", arr.length);
    console.log("token            :", tok() ? "present" : "MISSING");
    const ok = (j && j.data || []).length > 100 &&
               ((s && s.data || {}).fields || []).length > 0 && arr.length > 0;
    console.log(ok ? "%cALL GOOD — run MBF.prices() or MBF.full()"
                   : "%cSOMETHING IS OFF — check you are logged in",
                ok ? "color:#2a7;font-weight:bold" : "color:#c33;font-weight:bold");
    console.log("elapsed", ((Date.now() - t0) / 1000).toFixed(1), "s");
    return ok;
  },
};

console.log("%cMBF loaded.", "color:#2a7;font-weight:bold;font-size:13px");
console.log("  MBF.test()    — 3-second check that everything is reachable");
console.log("  MBF.prices()  — ~4 min   prices + full announcement history (daily)");
console.log("  MBF.full()    — ~25 min  everything (weekly/monthly)");
})();
