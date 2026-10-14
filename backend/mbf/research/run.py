"""Run the pre-registered signal scoreboard and write reports/research_signals.md."""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from mbf import config
from mbf.research import data, evaluate, families

log = logging.getLogger(__name__)



def _fmt(df: pd.DataFrame) -> str:
    pct = ["win", "mean_net", "ctrl_net", "edge", "dev_edge", "hold_edge"]
    out = df.copy()
    for c in out.columns:
        if c in pct:
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else f"{v:+.2%}" if c != "win" else f"{v:.0%}")
        elif c in ("t", "dev_t", "hold_t"):
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else f"{v:+.1f}")
    cols = [str(c) for c in out.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in out.itertuples(index=False)]
    return "\n".join(lines) + "\n"


def scoreboard(cost: float | None = None) -> tuple[pd.DataFrame, dict]:
    f, out = data.load(cost=cost) if cost is not None else data.load()
    sigs = families.build(f)
    ctrls: dict[str, pd.DataFrame] = {}
    rows, detail = [], {}
    for name, (mask, rules) in sigs.items():
        for r in rules or families.DEFAULT_RULES:
            if r not in ctrls:
                ctrls[r] = evaluate.control_means(f, out, r)
            res = evaluate.evaluate(f, out, mask, r, ctrls[r])
            rows.append(evaluate.row(name, r, res))
            detail[(name, r)] = res
            log.info("%-45s %-16s n=%5s edge=%s t=%s", name, r, res.get("n"),
                     f"{res.get('edge', np.nan):+.4f}", f"{res.get('t', np.nan):+.1f}")
    return pd.DataFrame(rows), detail


def write_report(sb: pd.DataFrame, detail: dict) -> str:
    best = sb.sort_values("t", ascending=False)
    lines = [f"# Signal scoreboard — {date.today()}", "",
             f"Data: PSX, modern era {config.MODERN_FROM} -> latest; event signals 2018+ (AKD history). "
             "Universe: up to 200 most-traded stocks/day (>= Rs 2m/day, price >= Rs 5). "
             "Rules: `timeN` / `atr_s_g_hN` = buy at the next open, sell at a close (or stop/target); "
             "`C_..._O` = buy near the next close, sell at an opening auction. Costs 0.6% round trip; "
             "dividends collected are net of 15% withholding. **mean_net** is the absolute return per trade; "
             "**edge** = mean_net minus the same-day matched control (random universe stocks, same "
             "liquidity and volatility bucket, same rule). **t** is computed across dates. "
             "Development <= 2022, holdout 2023+.", "",
             f"{len(sb)} tests were run. With that many, |t| > 3 is the bar for 'real'; a survivor must "
             "also hold up in the holdout and in most years.", "",
             _fmt(best[["signal", "rule", "n", "dates", "win", "mean_net", "ctrl_net", "edge", "t",
                        "yrs+", "dev_edge", "dev_t", "hold_n", "hold_edge", "hold_t"]]), ""]
    lines += ["## By year (edge vs control, rule with the best t per signal)", ""]
    top = best.dropna(subset=["t"]).drop_duplicates("signal")
    yrs = []
    for r in top.itertuples():
        yrs.append({"signal": r.signal, "rule": r.rule, **{str(k): v for k, v in
                                                            detail[(r.signal, r.rule)]["by_year"].items()}})
    y = pd.DataFrame(yrs).fillna("")
    for c in y.columns[2:]:
        y[c] = y[c].map(lambda v: "" if v == "" else f"{v:+.1%}")
    cols = list(y.columns)
    lines += ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in y.itertuples(index=False)]
    path = config.REPORTS_DIR / "research_signals.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def main():
    sb, detail = scoreboard()
    p = write_report(sb, detail)
    log.info("wrote %s", p)
    return sb, detail
