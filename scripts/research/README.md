# Research scripts (reports/research_new_data.md)

These scripts produced the new-data research report. They are one-off studies, not part of the
pipeline. Run them from the repo root with the project venv, e.g.
`.venv\Scripts\python scripts\research\rights_study.py`.

| script | what it does |
|---|---|
| `notice_text.py` | downloads the PSX index-recomposition notices and saves page-1 text (OCR for scans) to `data/raw/notices/` |
| `build_changes.py` | the hand-checked transcription of those notices → `data/raw/notices/index_changes.csv` |
| `index_study.py` | maps names to tickers; tests KSE-100 / KSE-30 / KMI-30 additions and deletions |
| `kmi_robust.py` | robustness checks on KMI-30 additions (entry lag, exits, liquidity, per review) |
| `rights_build.py` | builds the rights-issue event table (PSX notices + AKD) → `data/research/rights_events.parquet` |
| `rights_study.py` | rights-issue event studies (run-up, ex-day, after ex-date, after decision) |
| `flows_study.py EXPORT.json` | NCCPL flows: sector rules by client group, market timing |
| `flows_robust.py EXPORT.json` | NCCPL data sanity checks and 4-week cumulative flows |

The NCCPL export (`data/raw/nccpl/nccpl_flows_2015-2026.json`) was collected in a browser: the site
blocks scripted access behind a Cloudflare check.
