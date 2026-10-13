from datetime import datetime

from mbf import config, jobs


def test_schedule_weekdays_evening_and_saturday_maintenance():
    tz = jobs.TZ
    fri_noon = datetime(2026, 10, 16, 12, 0, tzinfo=tz)            # a Friday
    nxt = jobs.next_runs(fri_noon)
    assert nxt[0] == (datetime(2026, 10, 16, 18, 30, tzinfo=tz), "daily_update")
    assert nxt[1] == (datetime(2026, 10, 17, 10, 0, tzinfo=tz), "weekly_maintenance")
    assert nxt[2] == (datetime(2026, 10, 19, 18, 30, tzinfo=tz), "daily_update")   # Monday
    sun = datetime(2026, 10, 18, 9, 0, tzinfo=tz)
    assert jobs.next_runs(sun)[0][1] == "daily_update"             # nothing on Sunday


def test_run_job_records_failure_without_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    def boom():
        raise RuntimeError("PSX unreachable")

    assert jobs.run_job("daily_update", boom) is False
    st = jobs.read_status()["daily_update"]
    assert st["ok"] is False and "PSX unreachable" in st["detail"]["error"]
    assert jobs.run_job("daily_update", lambda: {"rows": 1}) is True
    assert jobs.read_status()["daily_update"]["ok"] is True


def test_needs_bootstrap_on_empty_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert jobs.needs_bootstrap()
