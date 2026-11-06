"""Offline tests for private accounts.

A private account carries `private_to: <device>` and is only ever served to that
device — no one else's requests may be routed to it. The owner still rides the
shared pool first (their private account is their reserve), and rotates onto it
when the shared pool is spent.

  python3 tests/test_private.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rotator as R

R.save_state = lambda: None
PASS = 0


def check(name, cond, extra=""):
    global PASS
    print(("ok  " if cond else "FAIL") + " " + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        sys.exit(1)
    PASS += 1


class H(dict):
    """httpx.Headers stand-in (case-insensitive get)."""
    def get(self, k, default=None):
        return super().get(k.lower(), default)


def headers(**kw):
    h = H()
    if "u5" in kw: h["anthropic-ratelimit-unified-5h-utilization"] = str(kw["u5"])
    if "u7" in kw: h["anthropic-ratelimit-unified-7d-utilization"] = str(kw["u7"])
    if "status" in kw: h["anthropic-ratelimit-unified-status"] = kw["status"]
    return h


now = time.time()
R.THRESHOLD, R.THRESHOLD_7D = 0.8, 0.98
R.STRATEGY, R.COOLDOWN_S, R.SWITCH_MARGIN, R.CF_MARGIN_S = "consume-first", 300, 0.05, 3600
R.HOLD_MAX_S = 0

# One shared pool account + one private account each for pam and dave.
R.ACCOUNTS = {
    "shared": {"name": "shared", "token": "tok-shared"},
    "pam":    {"name": "pam", "token": "tok-pam", "private_to": "pam-mac"},
    "dave":   {"name": "dave", "token": "tok-dave", "private_to": "dave-mac"},
}
R.DEVICE_BY_KEY = {
    "devkey-pam": "pam-mac", "devkey-dave": "dave-mac", "devkey-other": "other-mac",
}
TOKEN_TO_ACCT = {v["token"]: k for k, v in R.ACCOUNTS.items()}


def fresh_state(active="shared"):
    R.STATE = {"active_account": active, "accounts": {}, "events": [],
               "last_switch_ts": 0, "device_accounts": {}}


# --- 1. helpers -------------------------------------------------------------
check("owners reads the owner", R.owners("pam") == ["pam-mac"])
check("owners is empty when shared", R.owners("shared") == [])
check("shared available to any device", R.available_to("shared", "other-mac"))
check("private available to its owner", R.available_to("pam", "pam-mac"))
check("private NOT available to a stranger", not R.available_to("pam", "other-mac"))
R.ACCOUNTS["pam"]["private_to"] = ["pam-mac", "pam-linux"]
check("every device in a list owns the account", R.available_to("pam", "pam-mac")
      and R.available_to("pam", "pam-linux"))
check("a device outside the list does not", not R.available_to("pam", "other-mac"))
R.ACCOUNTS["pam"]["private_to"] = "pam-mac"
check("device=None means no scoping (tests / single-user)", R.available_to("pam", None))


# --- 2. pick_account filters the pool per device ----------------------------
fresh_state()
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.3, "util_7d": 0.2, "reset_7d": now + 200000},
    "pam":    {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},  # soonest, pam's
    "dave":   {"util_5h": 0.2, "util_7d": 0.1, "reset_7d": now + 50000},   # soonest, dave's
}
check("owner's device may pick its private account", R.pick_account("pam-mac") == "pam")
check("dave's device may pick its private account", R.pick_account("dave-mac") == "dave")
check("stranger's pool is shared-only", R.pick_account("other-mac") == "shared")
check("device-less sees every account", R.pick_account(None) == "dave")

# A stranger whose only shared account is spent must NOT jump onto pam's or
# dave's private account just because it has room.
fresh_state()
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.95, "util_7d": 0.5, "reset_5h": now + 1000},
    "pam":    {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},
    "dave":   {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 50000},
}
check("stranger stays on a spent shared account rather than leak a private one",
      R.pick_account("other-mac") == "shared")


# --- 3. note_response rotates a device within its own pool ------------------
fresh_state()
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.4, "util_7d": 0.2, "reset_7d": now + 500000},
    "pam":    {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},
}
R.STATE["device_accounts"]["pam-mac"] = "shared"
# pam's device is riding the shared pool; the shared account gets rejected →
# pam rotates onto its own private account (the only other one it may use).
v = asyncio.run(R.note_response("shared", headers(u5=1.0, status="rejected"), 429, device="pam-mac"))
check("owner rotates onto its private account when shared is spent",
      v == "switched" and R.STATE["device_accounts"]["pam-mac"] == "pam")
check("that rotation does not clobber a stranger's pointer",
      "other-mac" not in R.STATE["device_accounts"])

# A stranger riding the shared pool, shared rejected → its pool has NO other
# account, so it reports exhausted (never bounces onto pam's or dave's).
fresh_state()
R.STATE["accounts"] = {
    "shared": {"util_5h": 1.0, "util_7d": 0.5, "reset_5h": now + 1000},
    "pam":    {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},
    "dave":   {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 50000},
}
R.STATE["device_accounts"]["other-mac"] = "shared"
v = asyncio.run(R.note_response("shared", headers(u5=1.0, status="rejected"), 429, device="other-mac"))
check("stranger goes exhausted, never bounces onto a private account",
      v == "exhausted" and R.STATE["device_accounts"]["other-mac"] == "shared")


# --- 4. end-to-end over ASGI: a private account is served only to its owner --
R.client = httpx.AsyncClient(
    transport=httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"usage": {"input_tokens": 1, "output_tokens": 1}}, headers={})
    ),
    base_url=R.UPSTREAM, timeout=60.0,
)


async def hit(device_key):
    fresh_state(active="pam")  # force the 'active' account to be pam's private one
    R.STATE["accounts"] = {
        "shared": {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 300000},
        "pam":    {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 100000},
        "dave":   {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 400000},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=R.app),
                                 base_url="http://proxy", timeout=60.0) as ac:
        return await ac.post("/v1/messages",
                             content=json.dumps({"model": "claude-opus-5", "messages": []}),
                             headers={"authorization": "Bearer " + device_key})


r = asyncio.run(hit("devkey-pam"))
check("owner request 200", r.status_code == 200)
check("owner IS served from its private account", r.headers.get("x-rotate-account") == "pam")

r = asyncio.run(hit("devkey-other"))
check("stranger request 200", r.status_code == 200)
check("stranger is NOT served from a private account",
      r.headers.get("x-rotate-account") == "shared")

print(f"\nall {PASS} checks passed")
