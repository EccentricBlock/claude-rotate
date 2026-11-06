"""A configuration reload replaces ACCOUNTS while requests are in flight.

Each case removes an account at the await point where a request could be
holding its name, and checks the request finishes cleanly instead of raising
KeyError.
"""
import asyncio
import sys
import time
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

print(f"\nall {PASS} checks passed")
