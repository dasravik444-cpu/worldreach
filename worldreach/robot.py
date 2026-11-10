"""The robot: runs the jobs by itself, on a timetable ( wr on  starts it,  wr off  stops it).

    emails   every hour at :35, around the clock - but only while it is office hours somewhere we have businesses
             (replies and bounces are read, follow-ups and new e-mails sent)
    leads    once a day: the next city's businesses, then the e-mail hunt for them
    hunt     once a day: more e-mail hunting in cities searched before
    update   once a day: the newest version from GitHub (kept only if it starts cleanly)
    backup   once a day: a copy of the outreach memory (last 7 days kept)

Times are in the owner's own time zone (ROBOT_TZ in settings.txt, India by default). The lead search is placed in
the hours when no market is in its office hours (the US closes at about 6:00 India time, the UK opens at about
14:00), so e-mails and the lead search do not wait for each other. Every job can be switched off in settings.txt:
ROBOT_EMAILS=no, ROBOT_LEADS=no, ROBOT_AUTO_UPDATE=no.

A job missed while the tablet was off runs once when it is back (e-mail runs: the next hour's simply sends what
is due). One job at a time; a job that hangs is stopped at its time limit. The robot writes its heartbeat into
data/robot-status.json, which android/wr.sh reads.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import settings as S

ROOT = S.ROOT
UPDATED, ALREADY_RUNNING = 10, 75      # exit codes of  serve  that android/wr.sh understands
KEEP_BACKUPS = 7


@dataclass(frozen=True)
class Job:
    name: str
    title: str
    times: tuple[str, ...]             # HH:MM in the robot's time zone; ("hourly:35",) = every hour at :35
    timeout_min: float
    switch: str                        # the settings.txt key that turns it off with "no"
    late_hours: float = 6.0            # a missed start still runs when the robot is back within this time


JOBS = {
    "update": Job("update", "newest version", ("07:30",), 20, "ROBOT_AUTO_UPDATE"),
    "backup": Job("backup", "backup of the memory", ("07:45",), 10, "ROBOT_BACKUP", 20.0),
    "leads": Job("leads", "lead search", ("08:00",), 170, "ROBOT_LEADS"),
    "hunt": Job("hunt", "e-mail hunt", ("11:15",), 60, "ROBOT_HUNT", 2.0),
    "emails": Job("emails", "e-mail run", ("hourly:35",), 58, "ROBOT_EMAILS", 0.75),
}
PRIORITY = ["emails", "update", "backup", "leads", "hunt"]


def data() -> Path:
    return S.data_dir()


def tz_of(settings: dict):
    from leadgen.util import get_tz

    return get_tz(str(settings.get("ROBOT_TZ") or "Asia/Kolkata"))


def job_times(job: Job, settings: dict) -> tuple[str, ...]:
    own = str(settings.get(f"ROBOT_{job.name.upper()}_TIME") or "").strip()
    return (own,) if own and job.times[0][:6] != "hourly" else job.times


def slots(job: Job, settings: dict, now: float) -> list[float]:
    """The job's start times of yesterday, today and tomorrow."""
    zone = tz_of(settings)
    today = datetime.fromtimestamp(now, zone).replace(second=0, microsecond=0)
    out = []
    for offset in (-1, 0, 1):
        day = today + timedelta(days=offset)
        for t in job_times(job, settings):
            if t.startswith("hourly:"):
                out += [day.replace(hour=h, minute=int(t[7:])).timestamp() for h in range(24)]
            else:
                h, m = t.split(":")
                out.append(day.replace(hour=int(h), minute=int(m)).timestamp())
    return sorted(out)


def due_slot(job: Job, settings: dict, now: float, last_started: float | None) -> float | None:
    """The newest start time that has passed, is not too old and was not served yet."""
    passed = [s for s in slots(job, settings, now) if s <= now and now - s <= job.late_hours * 3600]
    if not passed or (last_started is not None and last_started >= passed[-1]):
        return None
    return passed[-1]


def next_slot(job: Job, settings: dict, now: float) -> float | None:
    return next((s for s in slots(job, settings, now) if s > now), None)


def switched_on(job: Job, settings: dict) -> bool:
    return S.flag(settings, job.switch, True)


def office_hours_somewhere(now: float) -> bool:
    """Is it office hours, now or within the coming hour, in any market's time zone? (No e-mail run is worth
    starting otherwise: it would read the Sheet and send nothing.)"""
    from leadgen.util import get_tz

    from .outreach import config as C

    try:
        o = C.load(settings=S.load())
        zones = {tz for code in o["markets"] for _, tz in C.load_market(code).cities.values()}
    except Exception:  # noqa: BLE001 - a broken config: let the run itself say so
        return True
    e = o["email"]
    for name in zones:
        for ahead in (0, 3000):
            local = datetime.fromtimestamp(now + ahead, get_tz(name))
            if C.DAY_NAMES[local.weekday()] in e["days"] and \
                    C.minutes(e["window_start"]) <= local.hour * 60 + local.minute < C.minutes(e["window_end"]):
                return True
    return False


def pick_due(now: float, status: dict, settings: dict) -> tuple[Job, float] | None:
    for name in PRIORITY:
        job = JOBS[name]
        if not switched_on(job, settings):
            continue
        slot = due_slot(job, settings, now, (status.get("jobs") or {}).get(name, {}).get("slot"))
        if slot is not None:
            return job, slot
    return None


# ------------------------------------------------------------------ status file and log
def status_path() -> Path:
    return data() / "robot-status.json"


def load_status() -> dict:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_status(st: dict) -> None:
    data().mkdir(parents=True, exist_ok=True)
    tmp = status_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, status_path())


def beat(st: dict) -> None:
    st["heartbeat"] = int(time.time())
    st["pid"] = os.getpid()
    save_status(st)


def log_path(now: float | None = None) -> Path:
    folder = data() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{datetime.fromtimestamp(now or time.time()):%Y-%m-%d}.log"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with log_path().open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def prune_logs(keep_days: int = 30) -> None:
    for f in sorted((data() / "logs").glob("*.log"))[:-keep_days]:
        f.unlink(missing_ok=True)


def should_stop() -> bool:
    return (data() / "robot.stop").exists()


# ------------------------------------------------------------------ the jobs
def internet_ok() -> bool:
    for host in ("www.google.com", "www.cloudflare.com", "github.com"):
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


def wait_for_internet(max_seconds: float, st: dict, check=None, sleep=time.sleep) -> bool:
    check = check or internet_ok
    end = time.monotonic() + max_seconds
    told = False
    while not check():
        if should_stop() or time.monotonic() >= end:
            return False
        if not told:
            log(f"no internet connection - waiting up to {max_seconds / 60:.0f} minutes")
            told = True
        beat(st)
        sleep(30)
    return True


def run_command(args: list[str], timeout_min: float, st: dict) -> int:
    """Run one job as its own process, its output into today's log; stop it at its time limit or on  wr off ."""
    env = {**os.environ, "WR_ROBOT_JOB": "1", "PYTHONUNBUFFERED": "1"}
    with log_path().open("a", encoding="utf-8") as fh:
        proc = subprocess.Popen(args, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        deadline = time.monotonic() + timeout_min * 60
        while proc.poll() is None:
            beat(st)
            if time.monotonic() > deadline or should_stop():
                why = "its time limit" if time.monotonic() > deadline else "wr off"
                log(f"stopping the job ({why}); it saves its work first")
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    proc.wait(timeout=150)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
                break
            time.sleep(5)
        return proc.wait()


def git(*args: str, timeout: float = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)


def starts_cleanly() -> bool:
    """The version in the folder starts: what it needs is installed, and its own text check passes."""
    try:
        r = subprocess.run(["bash", "scripts/run.sh", "preview", "gym"], cwd=str(ROOT), capture_output=True, text=True,
                           timeout=900)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def do_update() -> tuple[str, bool]:
    """git pull; the new version is kept only if it starts cleanly. Returns (result, updated)."""
    old = git("rev-parse", "--short", "HEAD").stdout.strip()
    pull = git("pull", "--ff-only")
    if pull.returncode != 0:
        return f"failed: git pull: {(pull.stderr or pull.stdout).strip()[-200:]}", False
    new = git("rev-parse", "--short", "HEAD").stdout.strip()
    if new == old:
        return "ok: already the newest version", False
    if starts_cleanly():
        return f"ok: updated {old} -> {new}", True
    git("reset", "--hard", old)
    starts_cleanly()                    # back to the old version's requirements
    return f"failed: version {new} did not start cleanly - kept {old}", False


def do_backup(now: float) -> str:
    src = data() / "outreach.sqlite"
    if not src.exists():
        return "ok: nothing to back up yet"
    from .outreach.store import Store

    stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    done = []
    for folder in (Path("/sdcard/Documents/worldreach-backup"), data() / "backups"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f"outreach-{stamp}.sqlite"
            store = Store(str(src))
            try:
                store.backup_to(str(dest))
            finally:
                store.close()
            settings_file = ROOT / "settings.txt"
            if settings_file.exists() and folder.parts[1:2] != ("sdcard",):
                shutil.copyfile(settings_file, folder / "settings.txt")     # only inside Termux: it holds passwords
            for old in sorted(folder.glob("outreach-*.sqlite"))[:-KEEP_BACKUPS]:
                old.unlink(missing_ok=True)
            done.append(str(folder))
        except OSError:
            continue
    return f"ok: copied to {', '.join(done)}" if done else "failed: no folder could be written"


def command(job: Job, settings: dict) -> list[str]:
    run = ["bash", "scripts/run.sh"]
    if job.name == "leads":
        minutes = str(settings.get("ROBOT_LEAD_MINUTES") or 110)
        return [*run, "leads", "--minutes", minutes, "--hunt-minutes", "30"]
    if job.name == "hunt":
        return [*run, "hunt", "--minutes", "45"]
    return [*run, "emails"]


def run_job(job: Job, slot: float, settings: dict, st: dict) -> bool:
    """Run one job and record it. True when the robot should restart (an update came in)."""
    st.setdefault("jobs", {})[job.name] = {**st.get("jobs", {}).get(job.name, {}), "slot": slot, "started": time.time(),
                                           "result": "running"}
    st["current"] = job.name
    beat(st)
    updated = False
    if job.name == "emails" and not office_hours_somewhere(time.time()):
        result = "ok: no office hours anywhere now - nothing to do"
    elif job.name == "backup":
        result = do_backup(time.time())
    elif not wait_for_internet(600, st):
        result = "failed: no internet connection"
    elif job.name == "update":
        result, updated = do_update()
    else:
        log(f"--- {job.title} starts")
        code = run_command(command(job, settings), job.timeout_min, st)
        result = {0: "ok", 2: "ok, with a problem to look at (wr log)", 3: "skipped: another job was running"}.get(
            code, f"failed (exit code {code})")
    log(f"--- {job.title}: {result}")
    st["jobs"][job.name].update(result=result, finished=time.time())
    st["current"] = ""
    beat(st)
    return updated


def serve() -> int:
    """Run the timetable until  wr off  (data/robot.stop). One copy at a time."""
    data().mkdir(parents=True, exist_ok=True)
    lock = open(data() / "robot.lock", "a+")
    try:
        import fcntl

        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass
    except OSError:
        return ALREADY_RUNNING
    st = load_status()
    st["started"] = time.time()
    log("robot started")
    prune_logs()
    while not should_stop():
        settings = S.load()
        beat(st)
        due = pick_due(time.time(), st, settings)
        if due and run_job(due[0], due[1], settings, st):
            log("robot restarts with the new version")
            return UPDATED
        if not due:
            time.sleep(20)
    log("robot stopped (wr off)")
    st["heartbeat"] = 0
    save_status(st)
    return 0


# ------------------------------------------------------------------ status / log
def fmt(ts: float | None, settings: dict) -> str:
    return datetime.fromtimestamp(ts, tz_of(settings)).strftime("%a %H:%M") if ts else "-"


def timetable_text(now: float | None = None) -> str:
    now = now or time.time()
    settings = S.load()
    st = load_status()
    alive = int(st.get("heartbeat") or 0) > now - 180
    lines = [f"Robot: {'RUNNING' if alive else 'not running'}"
             + (f" - working on: {JOBS[st['current']].title}" if alive and st.get("current") in JOBS else ""),
             f"Times are {settings.get('ROBOT_TZ') or 'Asia/Kolkata'} time.", ""]
    for name in ("emails", "leads", "hunt", "update", "backup"):
        job = JOBS[name]
        rec = (st.get("jobs") or {}).get(name, {})
        on = switched_on(job, settings)
        lines.append(f"  {job.title:<22} last: {fmt(rec.get('started'), settings):<10} {str(rec.get('result') or '-')[:60]:<62}"
                     + (f" next: {fmt(next_slot(job, settings, now), settings)}" if on else " SWITCHED OFF in the settings"))
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = list(argv or [])
    cmd = argv[0] if argv else "status"
    if cmd == "serve":
        return serve()
    if cmd == "status":
        from .cli import status_text

        print(timetable_text())
        print()
        print(status_text())
        return 0
    if cmd == "log":
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 40
        path = log_path()
        print("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]) if path.exists()
              else "Nothing in today's log yet.")
        return 0
    if cmd == "run" and len(argv) > 1 and argv[1] in JOBS:
        st = load_status()
        run_job(JOBS[argv[1]], time.time(), S.load(), st)
        print(st["jobs"][argv[1]]["result"])
        return 0
    print("usage: wr robot serve | status | log [LINES] | run emails|leads|hunt|update|backup")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
