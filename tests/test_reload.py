"""Hot configuration reload.

Part 1 removes an account at the await point where a request could be holding
its name, and checks the request finishes cleanly instead of raising KeyError.
Part 2 drives reload_config and the file watcher against a scratch config.
Part 3 starts real servers and reloads them with SIGHUP and by polling.
"""
import asyncio
import contextlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rotator as R

PASS = 0


def check(name, cond):
    global PASS
    print(("ok  " if cond else "FAIL") + " " + name)
    if not cond:
        sys.exit(1)
    PASS += 1


R.save_state = lambda: None
A = {"name": "a", "token": "tok-a"}
B = {"name": "b", "token": "tok-b"}


def fresh_state(**extra):
    R.ACCOUNTS = {"a": A, "b": B}
    R.STATE = {"active_account": "a", "accounts": {}, "events": [], "last_switch_ts": 0, **extra}


def unified(status="allowed"):
    now = time.time()
    return {"anthropic-ratelimit-unified-5h-utilization": "0.5",
            "anthropic-ratelimit-unified-7d-utilization": "0.2",
            "anthropic-ratelimit-unified-5h-reset": str(now + 3600),
            "anthropic-ratelimit-unified-7d-reset": str(now + 86400),
            "anthropic-ratelimit-unified-status": status}


# --- note_response: the reply arrives after the account was removed ---------
fresh_state()
R.ACCOUNTS = {"a": A}
verdict = asyncio.run(R.note_response("b", httpx.Headers(unified("rejected")), 429, device="laptop"))
check("a reply for a removed account is ignored, not a KeyError", verdict is None)
check("...and leaves no state behind for it", "b" not in R.STATE["accounts"])
check("...and does not move the active account", R.STATE["active_account"] == "a")


# --- refresh_idle_accounts: b is removed while a is being probed ------------
class DroppingClient:
    """Answers each probe, and removes b from ACCOUNTS during the first one."""

    def __init__(self):
        self.probed = []

    async def post(self, path, content=None, headers=None):
        self.probed.append(headers["authorization"])
        R.ACCOUNTS = {"a": A}
        return httpx.Response(200, headers=unified())


fresh_state()
R._REFRESH_TRIED.clear()
R.REFRESH_IDLE_S = 1
real_client, R.client = R.client, DroppingClient()
asyncio.run(R.refresh_idle_accounts())
check("idle refresh probes a", R.client.probed == ["Bearer tok-a"])
check("idle refresh skips b once it is gone", "Bearer tok-b" not in R.client.probed)
R.client = real_client


# --- send_upstream: b is removed while the request waits for the state lock -
class Upstream:
    def __init__(self):
        self.sent = []

    def __call__(self, request):
        self.sent.append(request.headers["authorization"])
        return httpx.Response(200, headers=unified())


fresh_state(device_accounts={"laptop": "b"})
dead = {"bad_status": 403, "last_bad_seen": time.time(), "bad_count": 1}
R.STATE["accounts"] = {"a": dict(dead), "b": dict(dead)}
R.BAD_RECOVER_S = 600
upstream = Upstream()
R.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream), base_url=R.UPSTREAM)


async def removed_while_waiting():
    # Both accounts are dead, so the request stays on b and takes the lock to
    # look for a working one; the reload lands while it waits.
    await R.state_lock.acquire()
    task = asyncio.create_task(R.send_upstream("POST", "/v1/messages", {}, b"{}", None, "laptop"))
    await asyncio.sleep(0.05)
    R.ACCOUNTS = {"a": A}
    R.state_lock.release()
    try:
        return await task
    except HTTPException as exc:
        return exc


outcome = asyncio.run(removed_while_waiting())
check("a request waiting on a removed account picks again and is served by a",
      not isinstance(outcome, HTTPException) and outcome[0].status_code == 200 and outcome[1] == "a")
check("...and never sends the removed account's token", upstream.sent == ["Bearer tok-a"])

# =============================================================================
# Part 2: reload_config and the file watcher, against a scratch config
# =============================================================================
ROOT = Path(__file__).resolve().parent.parent
root = Path(tempfile.mkdtemp())
(root / "tokens").mkdir()
R.CONFIG_PATH = root / "config.json"
R.AUDIT_PATH = root / "audit.jsonl"
R.AUDIT_PATH.write_text("")
R.BIND, R.PORT = "127.0.0.1", 8484
DEVS = {"d1": "key-d1-aaaa", "d2": "key-d2-bbbb"}


def put(path, text):
    """Replace a file the way an editor or the admin does: new inode, same name."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def token(name, value):
    put(root / "tokens" / f"{name}.token", value)


def config(accounts=("a",), devices=DEVS, **extra):
    put(R.CONFIG_PATH, json.dumps(
        {"accounts": [{"name": n, "token_file": f"tokens/{n}.token"} for n in accounts],
         "devices": devices, **extra}))


def reload(reason="test"):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        R.reload_config(reason)
    return err.getvalue()


def status(key):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=R.app),
                                     base_url="http://proxy") as ac:
            return await ac.get("/rotate/status", headers={"authorization": f"Bearer {key}"})
    return asyncio.run(go())


# --- a valid reload swaps accounts, devices and settings ---------------------
token("a", "tok-a1")
token("b", "tok-b1")
config(("a",))
reload("setup")
check("the setup reload loads account a", set(R.ACCOUNTS) == {"a"}
      and R.ACCOUNTS["a"]["token"] == "tok-a1")
R.STATE = {"active_account": "a", "accounts": {}, "events": [], "last_switch_ts": 0}
loaded_before = R.CONFIG_STATUS["loaded_at"]
config(("a", "b"), switch_threshold=0.7, refresh_idle_model="model-x")
log = reload()
check("a reload adds the new account with its token",
      set(R.ACCOUNTS) == {"a", "b"} and R.ACCOUNTS["b"]["token"] == "tok-b1")
check("a reload adds the new device key", R.DEVICE_BY_KEY == {"key-d1-aaaa": "d1", "key-d2-bbbb": "d2"})
check("a reload applies thresholds", R.THRESHOLD == 0.7)
check("a reload rebuilds the idle-refresh body",
      json.loads(R.REFRESH_BODY)["model"] == "model-x")
check("a reload is logged with its counts", "config reloaded (test): 2 accounts, 2 devices" in log)
check("a reload clears the error and moves loaded_at",
      R.CONFIG_STATUS["error"] is None and R.CONFIG_STATUS["loaded_at"] >= loaded_before
      and R.CONFIG_STATUS["last_reload"] is not None)
check("an account with no state entry yet can be picked", R.pick_account() in ("a", "b"))
check("...and the weekly snapshot waits for its first reading", "b" not in R.weekly_snapshot())
r = status("key-d2-bbbb")
check("the new device key opens /rotate/status, which lists b and the config state",
      r.status_code == 200 and "b" in r.json()["accounts"] and r.json()["config"]["error"] is None)
config(("a", "b"), switch_threshold=0.7, pace_lookahead="2d")
reload()
check("a reload changing the top-level pace_lookahead applies without a restart",
      R.PACE_LOOKAHEAD_S == 172800 and "pace_lookahead" not in R.CONFIG_STATUS["restart_needed"])
config(("a", "b"), switch_threshold=0.7, refresh_idle_model="model-x")
reload()
before = R.PACE_LOOKAHEAD_S
config(("a", "b"), switch_threshold=0.7, refresh_idle_model="model-x", cap_lookahead="12h")
reload()
check("a reload adding the renamed cap_lookahead keeps the running pace_lookahead and reports it",
      R.PACE_LOOKAHEAD_S == before and "pace_lookahead" in (R.CONFIG_STATUS["error"] or ""))
config(("a", "b"), switch_threshold=0.7, refresh_idle_model="model-x")
reload()

# --- an invalid reload keeps the running config -------------------------------
accts, devs = R.ACCOUNTS, R.DEVICE_BY_KEY
one = [{"name": "a", "token_file": "tokens/a.token"}]
for label, text, expect in (
        ("truncated JSON", '{"accounts": [', "JSONDecodeError"),
        ("weight 0", json.dumps({"accounts": [dict(one[0], weight=0)], "devices": DEVS}), "weight"),
        ("placeholder key", json.dumps({"accounts": one, "devices": {"d1": "dev-x-REPLACE-WITH-RANDOM"}}),
         "placeholder"),
        ("accounts not a list", json.dumps({"accounts": 5, "devices": DEVS}), "TypeError"),
        ("no devices", json.dumps({"accounts": one}), "devices")):
    put(R.CONFIG_PATH, text)
    log = reload()
    check(f"{label}: the running accounts, devices and thresholds are kept",
          R.ACCOUNTS is accts and R.DEVICE_BY_KEY is devs and R.THRESHOLD == 0.7)
    check(f"{label}: the error names the problem",
          expect in (R.CONFIG_STATUS["error"] or "") and "keeping the running config" in log)
put(R.CONFIG_PATH, json.dumps({"accounts": [dict(one[0], weight=0)], "devices": DEVS}))
reload()
r = status("key-d2-bbbb")
check("/rotate/status shows the failed reload", r.status_code == 200
      and "weight" in r.json()["config"]["error"])
config(("a", "b"), switch_threshold=0.7)
reload()
check("a corrected config clears the error", R.CONFIG_STATUS["error"] is None)

# --- restart-only settings are reported, not applied --------------------------
old_limit = R.MAX_CONCURRENT_REQUESTS
config(("a", "b"), switch_threshold=0.6, port=9999, max_concurrent_requests=old_limit + 3)
log = reload()
check("a reload still applies reloadable settings next to restart-only ones", R.THRESHOLD == 0.6)
check("...and leaves the port and concurrency limit alone",
      R.PORT == 8484 and R.MAX_CONCURRENT_REQUESTS == old_limit)
check("...and reports them", R.CONFIG_STATUS["restart_needed"] == ["port", "max_concurrent_requests"]
      and "restart to apply: port, max_concurrent_requests" in log)
with unittest.mock.patch.dict(os.environ, {"CLAUDE_ROTATE_MAX_REQUEST_BYTES": str(R.MAX_REQUEST_BYTES)}):
    config(("a", "b"), max_request_bytes=R.MAX_REQUEST_BYTES + 1)
    reload()
check("a limit pinned by an environment variable is not reported",
      "max_request_bytes" not in R.CONFIG_STATUS["restart_needed"])
config(("a", "b"), switch_threshold=0.7)
reload()

# --- panel_tailnet is checked against the address actually listened on --------
R.BIND = "0.0.0.0"
config(("a", "b"), panel_tailnet=True, bind="127.0.0.1")
reload()
check("panel_tailnet is refused while the process listens off loopback",
      R.PANEL_TAILNET is False and "panel_tailnet" in R.CONFIG_STATUS["error"])
R.BIND = "127.0.0.1"
reload()
check("...and accepted once it listens on loopback", R.PANEL_TAILNET is True)
config(("a", "b"))
reload()

# --- the watcher notices what changed on disk ---------------------------------
def changed():
    return R.watched_files() != R.CONFIG_FILES


check("untouched files are not a change", not changed())
R.RELOAD_POLL_S = 0.05


async def watch_briefly():
    task = asyncio.create_task(R.watch_config())
    await asyncio.sleep(0.4)
    task.cancel()


token("a", "tok-a2")
with contextlib.redirect_stderr(io.StringIO()):
    asyncio.run(watch_briefly())
check("watch_config reloads a replaced token file", R.ACCOUNTS["a"]["token"] == "tok-a2")
R.RELOAD_POLL_S = 5

secret = root / "secret"
for v in ("v1", "v2"):
    (secret / v).mkdir(parents=True)
    (secret / v / "tok").write_text(f"k8s-{v}")
os.symlink("v1", secret / "..data")
os.symlink("..data/tok", secret / "tok")
put(R.CONFIG_PATH, json.dumps({
    "accounts": [{"name": "a", "token_file": "tokens/a.token"},
                 {"name": "k", "token_file": str(secret / "tok")}], "devices": DEVS}))
reload()
check("an absolute token_file is read where it is", R.ACCOUNTS["k"]["token"] == "k8s-v1")
check("...and is not a change until the Secret volume swaps its link", not changed())
swap = secret / "..data_new"
os.symlink("v2", swap)
os.replace(swap, secret / "..data")
check("repointing the Secret volume's ..data link is a change", changed())
reload()
check("...and the new token is loaded", R.ACCOUNTS["k"]["token"] == "k8s-v2")

put(R.CONFIG_PATH, json.dumps({
    "accounts": [{"name": "a", "token_file": "tokens/a.token"},
                 {"name": "late", "token_file": "tokens/late.token"}], "devices": DEVS}))
reload()
check("an account whose token file is missing is skipped", set(R.ACCOUNTS) == {"a"})
token("late", "tok-late")
check("...the token file appearing is a change", changed())
reload()
check("...and the account joins", set(R.ACCOUNTS) == {"a", "late"})

put(R.CONFIG_PATH, "not json")
reload()
check("a failed reload is not retried while nothing changes", not changed())
config(("a",))
check("...but the next edit is picked up", changed())
reload()
check("...and loads", R.CONFIG_STATUS["error"] is None and set(R.ACCOUNTS) == {"a"})


# =============================================================================
# Part 3: real servers reloaded by SIGHUP and by polling
# =============================================================================
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_status(port, key):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/rotate/status",
                                 headers={"authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return None


def wait_for(fn, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.1)
    return False


def serve_and_reload(entry, poll, send_sighup):
    """Start a server, add a device to its config, and return what happened."""
    d = Path(tempfile.mkdtemp())
    (d / "tokens").mkdir()
    (d / "tokens" / "a.token").write_text("tok-a")
    port = free_port()
    # bind names an address this host cannot listen on, so the server only
    # starts if CLAUDE_ROTATE_BIND really overrides it.
    base = {"accounts": [{"name": "a", "token_file": "tokens/a.token"}], "port": port,
            "bind": "192.0.2.1", "refresh_idle_s": 0, "reload_poll_s": poll}
    put(d / "config.json", json.dumps({**base, "devices": {"one": "key-one-aaaa"}}))
    env = {**os.environ, "CLAUDE_ROTATE_CONFIG": str(d / "config.json"),
           "CLAUDE_ROTATE_STATE": str(d / "state.json"),
           "CLAUDE_ROTATE_AUDIT": str(d / "audit.jsonl"),
           "CLAUDE_ROTATE_BIND": "127.0.0.1", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, str(entry)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        up = wait_for(lambda: http_status(port, "key-one-aaaa") == 200)
        before = http_status(port, "key-two-bbbb")
        put(d / "config.json", json.dumps(
            {**base, "devices": {"one": "key-one-aaaa", "two": "key-two-bbbb"}}))
        if send_sighup:
            proc.send_signal(signal.SIGHUP)
        reloaded = wait_for(lambda: http_status(port, "key-two-bbbb") == 200)
        alive = proc.poll() is None
    finally:
        proc.terminate()
        try:
            _, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, err = proc.communicate()
    return up, before, reloaded, alive, err


for name, entry in (("python rotator.py", ROOT / "rotator.py"),
                    ("the systemd runner", ROOT / "deploy" / "systemd_runner.py")):
    up, before, reloaded, alive, err = serve_and_reload(entry, poll=0, send_sighup=True)
    check(f"{name} starts on CLAUDE_ROTATE_BIND, not the unlistenable bind in the file", up)
    check(f"{name}: a device added to the file is refused until SIGHUP", before == 401)
    check(f"{name}: SIGHUP loads it without a restart", reloaded and alive)
    check(f"{name}: SIGHUP is logged", "config reloaded (SIGHUP)" in err)

up, before, reloaded, alive, err = serve_and_reload(ROOT / "rotator.py", poll=1, send_sighup=False)
check("with reload_poll_s 1 a config edit is loaded with no signal", up and before == 401 and reloaded)
check("...and logged as a file change", alive and "config reloaded (file change)" in err)

print(f"\nall {PASS} checks passed")
