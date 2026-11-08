import json
import os
from datetime import datetime

import pytest

from mbf import jobs, tray

TZ = jobs.TZ
SAT_NIGHT = datetime(2026, 11, 7, 23, 0, tzinfo=TZ)


def _rec(started, ok=True, last_session="2026-11-06"):
    return {"ok": ok, "started": started, "finished": started,
            "detail": {"last_session": last_session} if ok else {"error": "PSX unreachable"}}


@pytest.mark.parametrize("due,running,paused,failed,colour,starts", [
    (None, False, False, False, "green", "Up to date · data up to Fri 6 Nov · next run Mon 9 Nov 18:30"),
    ("weekly", False, False, False, "amber", "Missed weekly run"),
    (None, True, False, False, "blue", "Updating"),
    (None, False, False, True, "red", "Last run failed"),
    ("weekly", True, True, True, "grey", "Scheduled jobs paused"),        # paused outranks the rest
])
def test_icon_colour_and_status_line(due, running, paused, failed, colour, starts):
    st = {"daily_update": _rec("2026-11-06T18:30:08+05:00")}
    if failed:
        st["weekly_maintenance"] = _rec("2026-11-07T10:00:05+05:00", ok=False)
    c, line = tray.summarize(st, due, running, paused, SAT_NIGHT)
    assert c == colour and line.startswith(starts)
    assert "data up to Fri 6 Nov" in line                      # from the last successful run


def test_recent_runs_reads_starts_exits_and_cut_off_runs(tmp_path):
    (tmp_path / "update_2026-11-05.log").write_text(
        "﻿=== 2026-11-05T10:55:53 update start\nlines\n=== 2026-11-05T11:08:23 update exit 0\n"
        "=== 2026-11-05T18:30:01 update start\n18:32:28 INFO    prices: 4/4\n", encoding="utf-8")
    (tmp_path / "weekly_2026-11-08.log").write_text(
        "=== 2026-11-08T23:13:29 weekly start (catch-up)\n=== 2026-11-08T23:58:38 weekly exit 1\n",
        encoding="utf-8")
    runs = tray.recent_runs(tmp_path)
    assert [(r["kind"], r["result"], r["catch_up"]) for r in runs] == [
        ("weekly", "failed", True), ("update", "cut off", False), ("update", "ok", False)]
    assert tray.run_label(runs[1]) == "⚠  Thu 5 Nov 18:30 · evening update — cut off"
    assert tray.run_label(runs[0]) == "✗  Sun 8 Nov 23:13 · weekly run (catch-up) — failed"


def test_rebuild_when_web_code_is_newer_than_the_build(tmp_path):
    (tmp_path / "src").mkdir()
    page = tmp_path / "src" / "page.tsx"
    page.write_text("x")
    assert tray.build_needed(tmp_path)                           # never built
    (tmp_path / ".next").mkdir()
    bid = tmp_path / ".next" / "BUILD_ID"
    bid.write_text("abc")
    os.utime(page, (1_000, 1_000))
    os.utime(bid, (2_000, 2_000))
    assert not tray.build_needed(tmp_path)
    os.utime(page, (3_000, 3_000))
    assert tray.build_needed(tmp_path)


def test_listener_pid_from_netstat():
    out = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1200
  TCP    127.0.0.1:3200         127.0.0.1:52011        ESTABLISHED     8800
  TCP    127.0.0.1:3200         0.0.0.0:0              ABHÖREN         8800
  TCP    [::]:32000             [::]:0                 LISTENING       9100
"""
    assert tray.listener_pid(out, 3200) == 8800                  # localized state word, right port
    assert tray.listener_pid(out, 3201) is None


@pytest.mark.parametrize("start,expected", [
    ("next start --port 3200", 3200),
    ("next start -p 4100", 4100),
    ("next start --port=3300 --hostname 0.0.0.0", 3300),
    ("next start", 3000),                                        # Next's own default
])
def test_port_comes_from_package_json(tmp_path, start, expected):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": start}}), encoding="utf-8")
    assert tray.web_port(tmp_path) == expected


def test_listener_pid_follows_the_port_in_package_json(monkeypatch):
    # a default bound at import would keep finding (and stopping) whatever is on 3200
    out = "  TCP    127.0.0.1:3200   0.0.0.0:0   LISTENING   8800\n  TCP    127.0.0.1:3299   0.0.0.0:0   LISTENING   4242\n"
    monkeypatch.setattr(tray, "web_port", lambda: 3299)
    assert tray.listener_pid(out) == 4242
