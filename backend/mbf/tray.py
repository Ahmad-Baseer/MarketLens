"""MarketLens in the Windows system tray.

    .venv\\Scripts\\pythonw.exe -m mbf.tray              run it (no console window)
    .venv\\Scripts\\python.exe -m mbf.tray --startup on  start it when you log in (off: don't)

Left-click opens the website, starting it if needed; right-click for the menu. The icon's
colour is the state of the data:
  green  up to date                 blue  a job is running
  amber  a scheduled run was missed ("Check scheduled jobs now" runs it)
  red    the last run failed        grey  scheduled jobs are paused
Notifications: new signals, a failed run, a missed run being caught up, and the end of a
run started from the menu. The website is the production build (`next start`, this
computer only), rebuilt first whenever the web code is newer than the build. Its port is
the one in web/package.json's "start" script, the only place it is set.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from mbf import config, jobs

log = logging.getLogger("mbf.tray")

WEB = config.ROOT / "web"
NEXT_DEFAULT_PORT = 3000                       # what `next start` uses when no port is given
SCRIPT = config.ROOT / "scripts" / "run_daily.ps1"
PYTHONW = config.ROOT / ".venv" / "Scripts" / "pythonw.exe"
LOGS = config.DATA_DIR / "logs"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
TASKS = ("MarketLens evening update", "MarketLens weekly maintenance")
JOB_MUTEX = "Local\\MarketLensDataJob"        # held by scripts\run_daily.ps1 while a job runs
TRAY_MUTEX = "Local\\MarketLensTray"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MarketLens tray"
POLL_S = 10
TASKS_POLL_S = 60
NO_WINDOW = 0x08000000                         # CREATE_NO_WINDOW
COLOURS = {"green": "#0d7a6f", "blue": "#2563eb", "amber": "#d97706", "red": "#dc2626", "grey": "#6b7280"}
JOB_NAMES = {"daily_update": "evening update", "weekly_maintenance": "weekly run",
             "update": "evening update", "weekly": "weekly run"}
WEB_SOURCES = ("src", "public", "package.json", "package-lock.json", "next.config.ts",
               "postcss.config.mjs", "tsconfig.json")


# ------------------------------------------------------------------ what the menu shows
def _when(ts) -> datetime:
    return ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts)[:19])


def _day(ts) -> str:
    d = _when(ts)
    return f"{d:%a} {d.day} {d:%b}"


def data_as_of(status: dict) -> str | None:
    """The last session the data covers, from the newest successful run."""
    days = [r["detail"]["last_session"] for k in ("daily_update", "weekly_maintenance")
            if (r := status.get(k)) and r.get("ok") and isinstance(r.get("detail"), dict)
            and r["detail"].get("last_session")]
    return max(days) if days else None


def summarize(status: dict, due: str | None, running: bool, paused: bool | None,
              now: datetime) -> tuple[str, str]:
    """(icon colour, status line) for the tooltip and the top of the menu."""
    asof = data_as_of(status)
    tail = f"data up to {_day(asof)}" if asof else "no data yet"
    if paused:
        return "grey", f"Scheduled jobs paused · {tail}"
    if running:
        return "blue", f"Updating · {tail}"
    last = max((r for k in ("daily_update", "weekly_maintenance") if (r := status.get(k))),
               key=lambda r: r.get("started", ""), default=None)
    if last and not last.get("ok"):
        return "red", f"Last run failed · {tail}"
    if due:
        return "amber", f"Missed {JOB_NAMES[due]} · {tail}"
    when = jobs.next_runs(now)[0][0]
    return "green", f"Up to date · {tail} · next run {_day(when)} {when:%H:%M}"


_RUN = re.compile(r"=== (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) (update|weekly) (start|exit|skipped)(.*)")


def recent_runs(log_dir: Path, n: int = 8) -> list[dict]:
    """Newest first, from the start/exit lines run_daily.ps1 writes. A start with no exit
    is a run that was cut off (or is still running: the caller knows which)."""
    files = sorted(list(log_dir.glob("update_*.log")) + list(log_dir.glob("weekly_*.log")),
                   key=lambda p: p.name.split("_", 1)[1])[-n:]
    runs = []
    for f in files:
        current = None
        for line in f.read_text(encoding="utf-8", errors="ignore").replace("\0", "").splitlines():
            m = _RUN.search(line)
            if not m:
                continue
            ts, kind, what, rest = m.groups()
            if what == "start":
                current = {"kind": kind, "start": datetime.fromisoformat(ts), "log": f,
                           "catch_up": "catch-up" in rest, "result": "cut off"}
                runs.append(current)
            elif what == "exit" and current is not None:
                code = rest.strip()
                current["result"] = "ok" if code == "0" else "failed"
                current = None
            elif what == "skipped":
                runs.append({"kind": kind, "start": datetime.fromisoformat(ts), "log": f,
                             "catch_up": False, "result": "skipped"})
    return sorted(runs, key=lambda r: r["start"], reverse=True)[:n]


def run_label(r: dict) -> str:
    mark = {"ok": "✓", "failed": "✗", "cut off": "⚠", "running": "⟳", "skipped": "–"}[r["result"]]
    what = JOB_NAMES[r["kind"]] + (" (catch-up)" if r["catch_up"] else "")
    note = "" if r["result"] in ("ok", "running") else f" — {r['result']}"
    return f"{mark}  {_day(r['start'])} {r['start']:%H:%M} · {what}{note}"


def build_needed(web: Path = WEB) -> bool:
    """No production build yet, or web code changed since the last one."""
    bid = web / ".next" / "BUILD_ID"
    if not bid.exists():
        return True
    built = bid.stat().st_mtime
    for name in WEB_SOURCES:
        p = web / name
        files = p.rglob("*") if p.is_dir() else [p] if p.exists() else []
        if any(f.is_file() and f.stat().st_mtime > built for f in files):
            return True
    return False


def web_port(web: Path = WEB) -> int:
    """The website's port: --port/-p in web/package.json's "start" script, so it is set in
    one place for `npm run start` and the tray alike (read on every use: an edit applies at
    once)."""
    try:
        start = json.loads((web / "package.json").read_text(encoding="utf-8"))["scripts"]["start"]
    except (OSError, ValueError, KeyError):
        return NEXT_DEFAULT_PORT
    m = re.search(r"(?:--port|-p)[\s=]+(\d+)", start)
    return int(m.group(1)) if m else NEXT_DEFAULT_PORT


def web_url() -> str:
    return f"http://localhost:{web_port()}"


def listener_pid(netstat: str, port: int | None = None) -> int | None:
    """The PID listening on `port` (default: the website's), from `netstat -ano` (state words
    are localized, so a listening socket is recognised by its unconnected remote address)."""
    port = port or web_port()
    for line in netstat.splitlines():
        p = line.split()
        if len(p) >= 5 and p[0] == "TCP" and p[1].rsplit(":", 1)[-1] == str(port) \
                and p[2] in ("0.0.0.0:0", "[::]:0") and p[-1].isdigit():
            return int(p[-1])
    return None


# ------------------------------------------------------------------ the machine
def _run(args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW, **kw)


def site_up() -> bool:
    port = web_port()
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            pass
    return False


def job_running() -> bool:
    """A run_daily.ps1 job is running (or queued for the lock)."""
    k32 = ctypes.windll.kernel32
    k32.OpenMutexW.restype = ctypes.c_void_p
    h = k32.OpenMutexW(0x00100000, False, JOB_MUTEX)         # SYNCHRONIZE
    if h:
        k32.CloseHandle(ctypes.c_void_p(h))
    return bool(h)


def start_job(*args: str) -> subprocess.Popen:
    return subprocess.Popen([str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", str(SCRIPT), *args], cwd=config.ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=NO_WINDOW)


def job_pids() -> list[int]:
    path = str(SCRIPT).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object "
          f"{{ $_.CommandLine -and $_.CommandLine.Contains('{path}') }} | ForEach-Object {{ $_.ProcessId }}")
    out = _run([str(POWERSHELL), "-NoProfile", "-Command", ps]).stdout
    return [int(x) for x in out.split() if x.isdigit()]


def kill_tree(pid: int):
    _run(["taskkill", "/PID", str(pid), "/T", "/F"])


def tasks_paused() -> bool | None:
    """True if every MarketLens scheduled task is disabled; None if none is registered."""
    names = ",".join(f"'{t}'" for t in TASKS)
    out = _run([str(POWERSHELL), "-NoProfile", "-Command",
                f"Get-ScheduledTask -TaskName {names} -ErrorAction SilentlyContinue | "
                "ForEach-Object { [string]$_.State }"]).stdout.split()
    return all(s == "Disabled" for s in out) if out else None


def set_paused(on: bool):
    verb = "Disable" if on else "Enable"
    names = ",".join(f"'{t}'" for t in TASKS)
    _run([str(POWERSHELL), "-NoProfile", "-Command",
          f"Get-ScheduledTask -TaskName {names} -ErrorAction SilentlyContinue | {verb}-ScheduledTask"])


def startup_command() -> str:
    return f'"{PYTHONW}" -m mbf.tray'


def startup_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def set_startup(on: bool):
    """Start the tray app at Windows logon (HKCU Run key: no admin rights needed)."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


def confirm(title: str, text: str) -> bool:
    MB_YESNO, MB_ICONQUESTION, MB_SETFOREGROUND, MB_TOPMOST, IDYES = 0x4, 0x20, 0x10000, 0x40000, 6
    return ctypes.windll.user32.MessageBoxW(
        None, text, title, MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def make_icon(colour: str):
    """The site's logo (magnifier over a rising line) on the status colour."""
    from PIL import Image, ImageDraw
    s = 4                                                    # draw at 4x 32px, then shrink
    im = Image.new("RGBA", (32 * s, 32 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, 32 * s - 1, 32 * s - 1), radius=9 * s, fill=COLOURS[colour])
    d.ellipse((7 * s, 7 * s, 21 * s, 21 * s), outline="white", width=int(2.5 * s))
    d.line((19 * s, 19 * s, 25 * s, 25 * s), fill="white", width=int(2.75 * s))
    d.line([(10.5 * s, 16 * s), (13 * s, 13.5 * s), (15 * s, 15.5 * s), (18 * s, 12 * s)],
           fill="white", width=int(1.8 * s), joint="curve")
    return im.resize((64, 64), Image.LANCZOS)


# ------------------------------------------------------------------ the app
class App:
    def __init__(self):
        import pystray
        self.ps = pystray
        self.colour, self.line = "", "MarketLens"
        self.running = self.site = False
        self.paused: bool | None = None
        self.today: dict = {}
        self.runs: list[dict] = []
        self.site_proc: subprocess.Popen | None = None
        self._site_lock = threading.Lock()
        self._seen: dict = {}
        self._asked: str | None = None             # a run started from the menu: report its end
        self._tasks_at = 0.0
        self._quitting = threading.Event()         # ends the polling loop
        self._images = {c: make_icon(c) for c in COLOURS}
        self.icon = pystray.Icon("MarketLens", self._images["grey"], "MarketLens", menu=self._menu())

    def run(self):
        self.icon.run(setup=self._loop)

    def notify(self, title: str, text: str):
        log.info("notify: %s | %s", title, text)
        try:
            self.icon.notify(text[:250], title[:60])
        except Exception:
            log.exception("notification failed")

    # ---- polling
    def _loop(self, icon):
        # pystray runs this on a thread the interpreter waits for at exit: it has to end on Quit,
        # or the process lives on hidden, holding the single-instance mutex
        icon.visible = True
        while not self._quitting.is_set():
            try:
                self.refresh()
            except Exception:
                log.exception("refresh failed")
            self._quitting.wait(POLL_S)

    def refresh(self):
        now = datetime.now(jobs.TZ)
        st = jobs.read_status()
        was_running, self.running = self.running, job_running()
        if time.monotonic() - self._tasks_at > TASKS_POLL_S:
            self.paused, self._tasks_at = tasks_paused(), time.monotonic()
        self.site = site_up()
        self.today = _read_json(config.DATA_DIR / "web" / "today.json")
        self.runs = recent_runs(LOGS)
        if self.running and self.runs and self.runs[0]["result"] == "cut off":
            self.runs[0]["result"] = "running"
        self._notify_changes(st, was_running)
        colour, line = summarize(st, jobs.due(now), self.running, self.paused, now)
        if colour != self.colour:
            self.icon.icon = self._images[colour]
        self.icon.title = f"MarketLens · {line}"[:127]
        self.colour, self.line = colour, line
        self.icon.update_menu()

    def _notify_changes(self, st: dict, was_running: bool):
        first = not self._seen
        for job in ("daily_update", "weekly_maintenance"):
            rec = st.get(job) or {}
            key = (rec.get("started"), rec.get("finished"))
            if not first and key != self._seen.get(job) and rec.get("finished"):
                self._finished(job, rec)
            self._seen[job] = key
        if self.running and not was_running and not first and not self._asked:
            r = self.runs[0] if self.runs else None
            if r and r["catch_up"]:
                self.notify("MarketLens: catching up", f"Running the missed {JOB_NAMES[r['kind']]} now.")

    def _finished(self, job: str, rec: dict):
        name = JOB_NAMES[job]
        asked, self._asked = self._asked, None
        if not rec.get("ok"):
            err = (rec.get("detail") or {}).get("error", "unknown error")
            self.notify(f"MarketLens: {name} failed",
                        f"{err[:140]}. It retries up to 3 times, 30 minutes apart; "
                        "see Open latest log.")
            return
        sig = ((rec.get("detail") or {}).get("signals") or {})
        new = sig.get("published_to_ledger", 0)
        tonight = self.today.get("tonight") or []
        if new and tonight:
            syms = ", ".join(s["symbol"] for s in tonight)
            self.notify(f"MarketLens: {new} new signal{'s' if new > 1 else ''}",
                        f"{syms} · buy {_day(tonight[0]['entry_date'])} before 15:00. Click the "
                        "icon to open MarketLens.")
        elif asked:
            asof = data_as_of({job: rec})
            self.notify(f"MarketLens: {name} done",
                        f"Data up to {_day(asof) if asof else '?'}; no new signals.")

    # ---- menu
    def _bg(self, fn, *args):
        def safe():
            try:
                fn(*args)
            except Exception as e:
                log.exception("%s failed", getattr(fn, "__name__", fn))
                self.notify("MarketLens: something went wrong", str(e)[:200])
            finally:
                try:
                    self.refresh()
                except Exception:
                    log.exception("refresh failed")
        return lambda: threading.Thread(target=safe, daemon=True).start()

    def _menu(self):
        M, I = self.ps.Menu, self.ps.MenuItem
        return M(
            I(lambda _: self.line, None, enabled=False),
            M.SEPARATOR,
            I("Open MarketLens", self._bg(self.open_site), default=True),
            I(lambda _: "Stop website" if self.site else "Start website", self._bg(self.toggle_site)),
            I("Check scheduled jobs now", self._bg(self.check_now)),
            M.SEPARATOR,
            I("Signals", M(self._signal_items)),
            I("Recent runs", M(self._run_items)),
            I("Run evening update now", self._bg(self.run_now), enabled=lambda _: not self.running),
            I("Stop running job", self._bg(self.stop_job), enabled=lambda _: self.running),
            M.SEPARATOR,
            I("Open latest log", self._bg(self.open_latest_log)),
            I("Open data folder", self._bg(os.startfile, str(config.DATA_DIR))),
            I("Pause scheduled jobs", self._bg(self.toggle_pause),
              checked=lambda _: bool(self.paused), enabled=lambda _: self.paused is not None),
            I("Start with Windows", self._bg(self.toggle_startup), checked=lambda _: startup_enabled()),
            M.SEPARATOR,
            I("Quit (stops the website)", self.quit),
        )

    def _signal_items(self):
        I = self.ps.MenuItem
        tonight, active = self.today.get("tonight") or [], self.today.get("active") or []
        asof = self.today.get("asof")
        yield I(f"New on the evening of {_day(asof)}" if asof else "New signals", None, enabled=False)
        if not tonight:
            yield I("    none", None, enabled=False)
        for s in tonight:
            yield I(f"    {s['symbol']} · buy {_day(s['entry_date'])}, sell {_day(s['exit_date'])} at the open",
                    self._bg(self.open_site, f"/signals/{s['id']}"))
        yield self.ps.Menu.SEPARATOR
        yield I(f"Open positions ({len(active)})", None, enabled=False)
        for s in active:
            yield I(f"    {s['symbol']} · sell {_day(s['exit_date'])} at the open",
                    self._bg(self.open_site, f"/signals/{s['id']}"))

    def _run_items(self):
        I = self.ps.MenuItem
        if not self.runs:
            yield I("No runs logged yet", None, enabled=False)
        for r in self.runs:
            yield I(run_label(r), self._bg(os.startfile, str(r["log"])))

    # ---- actions
    def start_site(self) -> bool:
        """Start the website if it isn't running. True if this call started it."""
        with self._site_lock:
            if site_up():
                return False
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("Node.js isn't installed (npm not found on PATH)")
            LOGS.mkdir(parents=True, exist_ok=True)
            out = open(LOGS / "web.log", "a", encoding="utf-8")
            if build_needed():
                self.notify("MarketLens: building the website", "After a code change: about a minute.")
                if subprocess.run([npm, "run", "build"], cwd=WEB, stdout=out, stderr=subprocess.STDOUT,
                                  creationflags=NO_WINDOW).returncode:
                    raise RuntimeError("the website build failed; see data\\logs\\web.log")
            # this computer only: no firewall prompt, nothing exposed on the network
            self.site_proc = subprocess.Popen(
                [npm, "exec", "--no", "--", "next", "start", "--port", str(web_port()), "--hostname", "127.0.0.1"],
                cwd=WEB, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            for _ in range(120):
                if site_up():
                    self.site = True
                    return True
                if self.site_proc.poll() is not None:
                    raise RuntimeError("the website stopped while starting; see data\\logs\\web.log")
                time.sleep(0.5)
            raise RuntimeError("the website didn't start within a minute; see data\\logs\\web.log")

    def stop_site(self):
        with self._site_lock:
            pid = listener_pid(_run(["netstat", "-ano"]).stdout)
            if pid:
                kill_tree(pid)
            if self.site_proc and self.site_proc.poll() is None:
                kill_tree(self.site_proc.pid)
            self.site_proc = None
            for _ in range(20):
                if not site_up():
                    break
                time.sleep(0.25)
            self.site = site_up()

    def open_site(self, path: str = ""):
        self.start_site()
        webbrowser.open(web_url() + path)

    def toggle_site(self):
        if site_up():
            self.stop_site()
            self.notify("MarketLens", "Website stopped.")
        else:
            self.start_site()
            self.notify("MarketLens", f"Website running at {web_url()}. Click the icon to open it.")

    def check_now(self):
        if job_running():
            self.notify("MarketLens: a run is in progress",
                        "The data will be up to date when it ends; opening MarketLens meanwhile.")
            self.open_site()
            return
        due = jobs.due()
        if not due:
            asof = data_as_of(jobs.read_status())
            self.notify("MarketLens: nothing missed",
                        f"Data up to {_day(asof) if asof else '?'}; opening MarketLens.")
            self.open_site()
            return
        self._asked = due
        self.notify(f"MarketLens: running the missed {JOB_NAMES[due]}",
                    "This takes a few minutes (the weekly run about half an hour). "
                    "MarketLens opens when it's done.")
        start_job("-CatchUp").wait()
        self.open_site()

    def run_now(self):
        if job_running():
            self.notify("MarketLens", "A run is already in progress.")
            return
        self._asked = "update"
        start_job()
        self.notify("MarketLens: evening update started", "You'll get a notification when it ends.")

    def stop_job(self):
        if not confirm("MarketLens", "Stop the running job?\n\nIts data so far is kept. The icon "
                                     "turns amber, and \"Check scheduled jobs now\" runs it again."):
            return
        pids = job_pids()
        for pid in pids:
            kill_tree(pid)
        self._asked = None
        self.notify("MarketLens", "Stopped the running job." if pids else "No job was running.")

    def open_latest_log(self):
        logs = list(LOGS.glob("update_*.log")) + list(LOGS.glob("weekly_*.log"))
        if not logs:
            raise RuntimeError("no job logs yet")
        os.startfile(str(max(logs, key=lambda p: p.stat().st_mtime)))

    def toggle_pause(self):
        on = not self.paused
        set_paused(on)
        self.paused, self._tasks_at = tasks_paused(), time.monotonic()
        self.notify("MarketLens", "Scheduled jobs paused: nothing runs until you resume them."
                    if on else "Scheduled jobs resumed. For a run missed meanwhile, use "
                               "\"Check scheduled jobs now\".")

    def toggle_startup(self):
        set_startup(not startup_enabled())

    def quit(self):
        self._quitting.set()
        if self.site_proc:
            try:
                self.stop_site()
            except Exception:
                log.exception("stopping the website failed")
        self.icon.stop()


def _single_instance() -> bool:
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    _single_instance.handle = k32.CreateMutexW(None, False, TRAY_MUTEX)    # held for the process's life
    return k32.GetLastError() != 183                                      # ERROR_ALREADY_EXISTS


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mbf.tray", description="MarketLens system-tray app")
    ap.add_argument("--startup", choices=("on", "off"),
                    help="start the tray app when you log in to Windows (on) or not (off), then exit")
    a = ap.parse_args(argv)
    if a.startup:
        set_startup(a.startup == "on")
        print(f"Start with Windows: {a.startup}" + (f"  ({startup_command()})" if a.startup == "on" else ""))
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOGS / "tray.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)-7s %(message)s")
    if not _single_instance():
        log.info("already running")
        return
    log.info("tray started")
    App().run()
    log.info("tray stopped")
    logging.shutdown()
    # Quit means gone: nothing still running in the background (a menu action mid-way, a
    # status check stuck on a subprocess) may keep the process, and its mutex, alive.
    # A data job started from the menu is a separate process and carries on.
    os._exit(0)


if __name__ == "__main__":
    main()
