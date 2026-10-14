# MarketLens web app

Next.js 16 (App Router, TypeScript, Tailwind 4). It only **reads** the JSON that the Python
evening job writes to `data/web/`. There is no database and no API of its own.

| page | file |
|---|---|
| Today: tonight's 3 strongest signals, open positions, market, upcoming calendar, warnings | `src/app/page.tsx` |
| Signal detail: plan, price chart, why, result, track record, fundamentals | `src/app/signals/[id]/page.tsx` |
| History: profit curve, by year, week by week with outcome filters | `src/app/history/page.tsx` |
| How it works: method, costs and taxes, warnings, what was rejected | `src/app/how-it-works/page.tsx` |
| Invite gate | `src/proxy.ts`, `src/app/access/page.tsx`, `src/lib/access.ts` |

## Run locally

```
# from the repo root: make sure data/web exists (the evening job, or a dry run)
.venv\Scripts\python -m mbf signals --dry-run
cd web
npm install
npm run dev        # http://localhost:3000
```

## Configuration (environment variables)

| variable | meaning |
|---|---|
| `MBF_DATA_DIR` | folder with the JSON (default `../data/web`): local use |
| `MBF_DATA_URL` | base URL the evening job publishes the JSON to: production. Pages re-read it every 5 minutes. |
| `ACCESS_CODES` | comma-separated invite codes, one per person. Unset = open site. Remove a code to revoke it. |
| `ACCESS_SECRET` | long random string used to sign the access cookie (required when `ACCESS_CODES` is set) |

See `env.example`.

## Checks

```
npx tsc --noEmit
npm run lint
npm run build
```

Charts are plain server-rendered SVG (`src/components/charts.tsx`), so there is no chart library.
Dates in the JSON are Pakistan-local days. `src/lib/format.ts` formats them without letting the
browser's timezone shift them.
