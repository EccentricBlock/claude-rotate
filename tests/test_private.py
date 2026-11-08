"""Offline tests for private accounts.

A private account carries `private_to: <device>` (or a list of devices) and is
only ever served to those devices — no one else's requests may be routed to it.
Its owners use it before any shared account, whatever the shared priorities, and
rotate onto the shared pool only once it is spent.

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


# --- 2b. priority tiers still rule; owners come first within a tier --------
# The CLIs write "priority": 1 for a new private account; the code defaults nothing.
fresh_state()
R.ACCOUNTS["pam"]["priority"] = R.ACCOUNTS["dave"]["priority"] = 1
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},
    "pam":    {"util_5h": 0.5, "util_7d": 0.5, "reset_7d": now + 900000},
    "dave":   {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 100000},
}
check("a private account with no priority is in the default tier",
      "priority" not in R.ACCOUNTS["shared"] and R.priority("shared") == 100)
check("owner uses its priority 1 private account before the shared pool",
      R.pick_account("pam-mac") == "pam")
check("a stranger takes the shared account", R.pick_account("other-mac") == "shared")
R.ACCOUNTS["shared"]["priority"] = 1
check("owner takes its private account ahead of an equal-priority shared one",
      R.pick_account("pam-mac") == "pam")
check("a stranger and a device-less pick still go by strategy within the tier",
      R.pick_account("other-mac") == "shared" and R.pick_account(None) == "shared")
R.ACCOUNTS["pam"]["priority"] = 2
check("a private p2 draws after a shared p1", R.pick_account("pam-mac") == "shared")
R.ACCOUNTS["shared"]["priority"] = 2
check("a private p2 draws before a shared p2", R.pick_account("pam-mac") == "pam")
del R.ACCOUNTS["shared"]["priority"]
R.ACCOUNTS["pam"]["priority"] = 1
check("a shared account at the default priority is behind a private p1",
      R.pick_account("pam-mac") == "pam")
del R.ACCOUNTS["pam"]["priority"]
check("a private account with no priority draws with the default tier, owner first",
      R.pick_account("pam-mac") == "pam")
R.ACCOUNTS["pam"]["priority"] = 1
R.STATE["accounts"]["pam"]["util_5h"] = 0.9  # over the 0.8 threshold
check("owner moves to the shared pool once its private account is spent",
      R.pick_account("pam-mac") == "shared")

# Riding shared while the private account has room again: pulled back after the cooldown.
fresh_state()
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 100000},
    "pam":    {"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 900000},
}
R.STATE["device_accounts"]["pam-mac"] = "shared"
asyncio.run(R.note_response("shared", headers(u5=0.2, u7=0.2), 200, device="pam-mac"))
check("owner returns to its private account when it has room",
      R.STATE["device_accounts"]["pam-mac"] == "pam"
      and R.STATE["events"][-1]["reason"] == "priority_recovery")

# A first-time device that owns an account starts on it, not on the global active one.
fresh_state(active="shared")
R.STATE["accounts"] = {
    "shared": {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 100000},
    "pam":    {"util_5h": 0.2, "util_7d": 0.2, "reset_7d": now + 900000},
}
check("first-time owner starts on its private account", R.device_current("pam-mac") == "pam")
check("first-time stranger inherits the global active account",
      R.device_current("other-mac") == "shared")


# --- 2c. a private account drains to its limits; several balance by strategy -
# Owners use their private accounts up to the thresholds and the weekly cap before
# moving on, and several private accounts for one device are ordered by `strategy`.
for n, tok in (("pam2", "tok-pam2"), ("pam3", "tok-pam3")):
    R.ACCOUNTS[n] = {"name": n, "token": tok, "private_to": "pam-mac", "priority": 1}
R.ACCOUNTS["pam"]["priority"] = 1


def roomy(**kw):
    return dict({"util_5h": 0.1, "util_7d": 0.1, "reset_7d": now + 500000}, **kw)


def pool(**per_account):
    fresh_state()
    R.STATE["accounts"] = {n: roomy(**per_account.get(n, {})) for n in R.ACCOUNTS}


pool()
check("a private account is used while it is under its limits",
      R.pick_account("pam-mac") in ("pam", "pam2", "pam3"))
pool(pam={"util_5h": 0.85}, pam2={"util_5h": 0.85}, pam3={"util_5h": 0.85})
check("owner leaves private accounts only once every one is past the 5h threshold",
      R.pick_account("pam-mac") == "shared")
pool(pam={"util_7d": 0.99}, pam2={"util_5h": 0.9}, pam3={"util_5h": 0.2})
check("a private account past a threshold is skipped for another private one",
      R.pick_account("pam-mac") == "pam3")
for n in ("pam", "pam2", "pam3"):
    R.ACCOUNTS[n]["weekly_cap"] = 0.05
pool(pam={"util_7d": 0.5}, pam2={"util_7d": 0.5}, pam3={"util_7d": 0.5})
check("owner leaves private accounts that are over their weekly cap",
      R.pick_account("pam-mac") == "shared")
R.ACCOUNTS["pam2"].pop("weekly_cap")
check("a private account under no cap is still used when the others are over theirs",
      R.pick_account("pam-mac") == "pam2")
for n in ("pam", "pam3"):
    R.ACCOUNTS[n].pop("weekly_cap")

# Several private accounts balance in line with the strategy.
def picks(strategy, **per_account):
    R.STRATEGY = strategy
    pool(**per_account)
    return R.pick_account("pam-mac")


check("consume-first drains the private account whose week resets soonest",
      picks("consume-first", pam={"reset_7d": now + 300000}, pam2={"reset_7d": now + 100000},
            pam3={"reset_7d": now + 200000}) == "pam2")
check("least-used picks the private account with the lowest 5h use",
      picks("least-used", pam={"util_5h": 0.5}, pam2={"util_5h": 0.3}, pam3={"util_5h": 0.1}) == "pam3")
check("most-weekly-left picks the private account with the lowest weekly use",
      picks("most-weekly-left", pam={"util_7d": 0.6}, pam2={"util_7d": 0.1}, pam3={"util_7d": 0.4}) == "pam2")
check("weekly-pace picks the private account whose weekly quota is likeliest to expire",
      picks("weekly-pace", pam={"reset_7d": now + 400000}, pam2={"reset_7d": now + 50000},
            pam3={"reset_7d": now + 300000}) == "pam2")
R.STRATEGY = "consume-first"

# Riding one private account when it reaches the threshold: the next private one, not shared.
pool(pam={"util_5h": 0.85})
R.STATE["device_accounts"]["pam-mac"] = "pam"
v = asyncio.run(R.note_response("pam", headers(u5=0.85, u7=0.1), 200, device="pam-mac"))
check("owner rotates to another private account before the shared pool",
      v == "switched" and R.STATE["device_accounts"]["pam-mac"] in ("pam2", "pam3"))

for n in ("pam2", "pam3"):
    del R.ACCOUNTS[n]
del R.ACCOUNTS["pam"]["priority"]


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

# earliest_relief is scoped to the requesting device: pam's private account
# resets in 3 days, dave's in 1 hour, everything is spent.
saved_accts, saved_state = R.ACCOUNTS, R.STATE
R.ACCOUNTS = {
    "pam":  {"name": "pam", "token": "tok-pam", "private_to": "pam-mac"},
    "dave": {"name": "dave", "token": "tok-dave", "private_to": "dave-mac"},
}
spent = {"util_5h": 1.0, "util_7d": 1.0, "status": "rejected", "last_seen": now - 10}
R.STATE = {"active_account": "pam", "events": [], "last_switch_ts": 0, "accounts": {
    "pam":  dict(spent, reset_5h=now + 3 * 86400, reset_7d=now + 3 * 86400),
    "dave": dict(spent, reset_5h=now + 3600, reset_7d=now + 3600),
}}
check("earliest_relief(pam-mac) waits for pam's own reset, not dave's",
      abs(R.earliest_relief("pam-mac") - (now + 3 * 86400)) < 60)
check("earliest_relief(dave-mac) is dave's reset",
      abs(R.earliest_relief("dave-mac") - (now + 3600)) < 60)
check("earliest_relief(None) keeps the global minimum",
      abs(R.earliest_relief(None) - (now + 3600)) < 60)
R.ACCOUNTS, R.STATE = saved_accts, saved_state

print(f"\nall {PASS} checks passed")
