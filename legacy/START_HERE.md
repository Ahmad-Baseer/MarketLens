# START HERE — Multi Beggar Finder

**What this is:** a tool that looks at every share on the Pakistan Stock Exchange
and gives you a short ranked list worth researching, with the actual numbers
explaining why each one is on the list.

**What it is not:** a buy list. It narrows ~500 shares down to ~15 so you can do
your own homework on a handful instead of hundreds. Nothing more.

Everything lives in one folder: `D:\Investments\Multi Beggar Finder`

---

# PART 1 — One-time setup

You only ever do this once.

### Step 1. Check you have Python

Open **Command Prompt** (press `Windows key`, type `cmd`, press Enter). Type:

```
python --version
```

- If you see something like `Python 3.11.5` → good, skip to Step 3.
- If you see an error → do Step 2.

### Step 2. Install Python (only if Step 1 failed)

1. Go to <https://www.python.org/downloads/>
2. Click the big yellow **Download Python** button.
3. Run the installer. **Important:** tick the box that says
   **"Add python.exe to PATH"** at the bottom of the first screen.
4. Click Install Now, wait, close it.
5. Close Command Prompt, open a new one, and try Step 1 again.

### Step 3. Install the three add-ons Python needs

In Command Prompt, type this and press Enter:

```
pip install pandas numpy pyarrow
```

Wait for it to finish. You'll see a lot of text. As long as the last line
doesn't say `ERROR`, you're done.

**Setup is complete. You never have to do Part 1 again.**

---

# PART 2 — The daily routine (about 5 minutes)

Three steps. Same three steps every day.

## Step 1 — Get today's prices from AKD

**1a.** Open Chrome and go to <https://research.akdtrade.biz/screener>

Make sure you are **logged in**. If you see the screener table with prices,
you're logged in.

**1b.** Press the **F12** key. A panel opens on the side or bottom of the screen.
Click the tab that says **Console**.

> If you don't see "Console", look for `>>` or click the `»` arrows to find it.

**1c.** Open the file `AKD_PULL.js` from your Multi Beggar Finder folder
(right-click → Open with → Notepad). Select everything (`Ctrl+A`), copy it
(`Ctrl+C`).

**1d.** Click into the Console area in Chrome, paste (`Ctrl+V`), press **Enter**.

You should see:

```
MBF loaded.
  MBF.test()    — 3-second check that everything is reachable
  MBF.prices()  — ~4 min   prices + full announcement history (daily)
  MBF.full()    — ~25 min  everything (weekly/monthly)
```

**1e.** Type this and press Enter:

```
MBF.test()
```

Wait 3 seconds. You want to see **`ALL GOOD`** in green.

> If it says something is off, you're probably not logged in. Reload the page,
> log in, and start again from 1b.

**1f.** Type this and press Enter:

```
MBF.prices()
```

Now **leave the tab alone for about 4 minutes.** Don't close it, don't switch to
another tab if you can avoid it. You'll see progress bars counting up like:

```
[########....................] 180/641  28.1%  eta 3m10s
```

**1g.** Chrome may show a bar at the top saying **"Allow multiple downloads?"** —
click **Allow**. (If you miss it, just run `MBF.prices()` again.)

**1h.** When it's finished you'll see a green **DONE** message. Three files have
downloaded.

## Step 2 — Move the downloaded files

Open your **Downloads** folder. Find the files starting with `mbf_`:

- `mbf_announcements.csv`
- `mbf_prices.csv`
- `mbf_universe.csv`

**Cut** them (`Ctrl+X`) and **paste** them (`Ctrl+V`) into
`D:\Investments\Multi Beggar Finder`, replacing the old ones when Windows asks.

> **Tip to skip this step forever:** in Chrome go to Settings → Downloads →
> Change, and pick `D:\Investments\Multi Beggar Finder`. Then files land there
> automatically and you can skip Step 2 from now on.

## Step 3 — Rebuild the list

In Command Prompt, type these two lines (press Enter after each):

```
cd /d "D:\Investments\Multi Beggar Finder"
python refresh.py
```

Takes about 17 seconds. You'll see it work through 4 stages, then print the top
15 shares.

**One line to check.** Look for this:

```
de-adjust check on 393 dividend events: 99th-pct error 4.85e-05  ->  OK
```

If it says **OK**, everything is healthy. If it ever says **FAILED**, stop and
tell me — the numbers can't be trusted that day.

## Done. Now look at the results

Double-click **`mbf_screen.html`** in the folder. It opens in your browser.

- Click any **column heading** to sort by it.
- Use the dropdowns to filter by sector, price, or score.
- The **"Why it is on the list"** column is the important one — it's the actual
  numbers.
- The **"Check before you act"** column is warnings. Read them.
- Grey rows at the bottom have had a share split or rights issue, so their
  ratios are unreliable until you check the company manually.

---

# PART 3 — Once a month (about 25 minutes)

Company results and balance sheets only change every few months, so once a month
do the same three steps as Part 2, but in Step 1f type this instead:

```
MBF.full()
```

This takes ~25 minutes and downloads **six** files instead of three (it adds
`mbf_statements.csv`, `mbf_profiles.csv`, `mbf_fundamentals.csv`). Move all six
in Step 2, then run `python refresh.py` as normal.

---

# PART 4 — What every file in the folder is

## The files you actually use

| File | What it does |
|---|---|
| **`AKD_PULL.js`** | You paste this into Chrome to download the data. Step 1. |
| **`refresh.py`** | You run this to rebuild the list. Step 3. |
| **`mbf_screen.html`** | **The result.** Double-click to open the dashboard. |
| `screen_today.csv` | Same result as a spreadsheet, if you prefer Excel. |
| `START_HERE.md` | This file. |

## Documents to read once

| File | What's in it |
|---|---|
| `FINDINGS.md` | What I tested and what I found. Includes the uncomfortable bits — e.g. the "volume spike" and "unusual movement notice" strategies are actually *worse* than random. |
| `HOW_TO_REFRESH.md` | The technical version of this file, with more detail and troubleshooting. |

## The data (downloaded — don't edit these by hand)

| File | What it holds |
|---|---|
| `mbf_prices.csv` | ~5 years of daily prices for 641 shares |
| `mbf_announcements.csv` | Every company announcement since 2018, including all dividend, bonus and rights dates |
| `mbf_fundamentals.csv` | P/E, P/B, ROE and other ratios per year |
| `mbf_statements.csv` | Quarterly profit and balance sheet figures |
| `mbf_profiles.csv` | Company name, sector, still-listed-or-not |
| `mbf_universe.csv` | The list of share symbols |

## `research\` folder — optional, for checking whether the ideas still work

You don't need these for daily use. Run them once every few months, in this
order, from Command Prompt inside the folder:

```
cd /d "D:\Investments\Multi Beggar Finder\research"
python panel.py
python baserate.py
python sweep.py
python signals.py
python validate.py
```

| File | What it tells you |
|---|---|
| `panel.py` | Prepares the data for testing. Run this first. Prints the "random guessing" benchmark that everything else is measured against. |
| `baserate.py` | What pure luck looks like. Shows that cheap shares swing more in *both* directions, so being cheap alone doesn't help. |
| `sweep.py` | Tests stop-loss and target combinations. Shows the popular "8% stop, 10% target" is the worst choice. |
| `signals.py` | Scores 19 different buying ideas. This is where the negative results came from. |
| `validate.py` | The reality check. Simulates actually trading it with Rs 30,000 positions. Read this one if you read any. |
| `eventstudy.py` | Helper file. Never run it directly. |

## `results\` folder

The output tables from when I ran the research myself. Open in Excel if curious.

If you run the research scripts yourself they create a **new `out\` folder** with
fresh versions of the same tables. `results\` is my run; `out\` is yours.

## `code\` folder — you can delete this

Old versions of three scripts. `refresh.py` replaced all of them. Kept only in
case you wanted to see them; safe to delete.

---

# PART 5 — If something goes wrong

| What you see | What to do |
|---|---|
| `MBF is not defined` | The paste didn't complete. Copy the whole `AKD_PULL.js` again and re-paste. |
| `401 — session expired` | Reload the AKD page, log in, re-paste, run again. |
| `access-token meta tag missing` | You're not logged into AKD on that page. |
| `'python' is not recognized` | Python isn't installed or wasn't added to PATH. Redo Part 1, Step 2, and tick the PATH box. |
| `ModuleNotFoundError: pandas` | Run `pip install pandas numpy pyarrow` again. |
| `Missing required file(s)` | The `mbf_` files aren't in the folder. Redo Step 2. |
| Only some files downloaded | Chrome blocked them. Click **Allow**, then re-run `MBF.prices()`. |
| `de-adjust check ... FAILED` | Stop. Don't use that day's list. Tell me. |
| The date at the top of the dashboard is old | The rebuild didn't run. Redo Step 3. |

---

# PART 6 — Please remember this

The score is a **ranking**, not a prediction. It means "worth twenty minutes of
reading", not "this will go up".

Some numbers from the testing, so you know what you're working with:

- Out of every 100 liquid PSX shares picked at random, about **65** will touch
  +10% within 3 months. But only about **44** will do it *before* first dropping
  8%. That's close to a coin flip.
- The single best-looking signal I found had overwhelming statistical support and
  **still lost money** when tested on years it hadn't seen. Statistical strength
  is not the same as making money.

Before you buy anything on this list, do these three things:

1. **Read the actual results filing** on the PSX website. The profit figure here
   comes from a summary feed that can't tell real trading profit from a one-off
   gain like selling a building.
2. **Check the share count hasn't changed** — any bonus, rights issue or split
   since the last accounts makes every per-share number on the screen wrong.
3. **Check the spread on your own terminal.** A share can look liquid here and
   still cost you 2% just to get in and out.

*Not investment advice. I'm not a licensed financial adviser. Every figure here
comes from a 4.7-year sample during an unusually strong market — it's evidence
about the past, not a forecast.*
