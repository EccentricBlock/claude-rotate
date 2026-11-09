#!/usr/bin/env bash
# File-based setup for claude-rotate. No database, no cloud: everything lives
# in config.json + tokens/ next to this script.
#
#   ./setup.sh                       first-time init (creates config.json, dirs)
#   ./setup.sh add-device <name>     mint a device key and register it
#   ./setup.sh add-account <name>    store a `claude setup-token` for an account
#                                    (--private-to <device>[,<device>...] reserves it
#                                    for those devices)
#   ./setup.sh onboard <user> <dev>  team flow: mint <user>-<dev> key, reload the
#                                    service, print a paste-ready welcome block
#                                    (uses config.json "public_url" when set)
set -euo pipefail
cd "$(dirname "$0")"

validate_name() {
    if [[ ! "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ ]]; then
        echo "error: names must be 1-64 ASCII letters, digits, underscores or hyphens, starting with a letter or digit" >&2
        exit 1
    fi
}

# Validate all caller-provided labels before creating or changing any files.
case "${1:-init}" in
init) ;;
add-device)
    name="${2:?usage: ./setup.sh add-device <name>}"
    validate_name "$name"
    ;;
add-account)
    name="${2:?usage: ./setup.sh add-account <name> [--private-to <device>[,<device>...]]}"
    validate_name "$name"
    priv=""
    if [ "${3:-}" = "--private-to" ]; then
        priv="${4:?missing device name after --private-to}"
        IFS=',' read -r -a priv_devices <<< "$priv"
        for d in "${priv_devices[@]}"; do validate_name "$d"; done
    elif [ -n "${3:-}" ]; then
        echo "error: unknown option: $3" >&2; exit 1
    fi
    ;;
onboard)
    user="${2:?usage: ./setup.sh onboard <username> <device>}"
    dev="${3:?usage: ./setup.sh onboard <username> <device>}"
    validate_name "$user"
    validate_name "$dev"
    name="${user}-${dev}"
    validate_name "$name"
    ;;
*) echo "unknown subcommand: $1" >&2; exit 1 ;;
esac

umask 077
mkdir -p tokens logs
chmod 700 tokens

if [ ! -f config.json ]; then
    cp config.example.json config.json
    echo "created config.json from config.example.json — edit accounts/devices or use the subcommands below"
fi
# Also protect configurations copied or restored with broader permissions.
chmod 600 config.json

case "${1:-init}" in
init)
    echo "ready. next steps:"
    echo "  ./setup.sh add-account acct-1   # paste a token from: claude setup-token"
    echo "  ./setup.sh add-device my-laptop"
    echo "  python3 rotator.py"
    ;;
add-device)
    key="dev-${name}-$(openssl rand -hex 8)"
    python3 - "$name" "$key" <<'EOF'
import json, os, sys
cfg = json.load(open("config.json"))
cfg.setdefault("devices", {})
cfg["devices"] = {k: v for k, v in cfg["devices"].items() if "REPLACE-WITH" not in v}
cfg["devices"][sys.argv[1]] = sys.argv[2]
# Write, then rename: a running proxy that notices the change must never read
# a half-written file.
path = os.path.realpath("config.json")
with open(path + ".tmp", "w") as f:
    json.dump(cfg, f, indent=2)
os.replace(path + ".tmp", path)
EOF
    url=$(python3 -c "import json; print(json.load(open('config.json')).get('public_url') or 'http://<this-host>:8484')")
    echo "device '$name' registered. On that machine set:"
    printf '  export ANTHROPIC_BASE_URL=%q\n' "$url"
    printf '  export CLAUDE_CODE_OAUTH_TOKEN=%q\n' "$key"
    ;;
onboard)
    # Team flow: a member sends you their username + device name; you run
    #   ./setup.sh onboard <username> <device>
    # and paste the printed block back to them. Mints the key as
    # <username>-<device>, reloads the service so it's live immediately.
    if python3 -c "import json,sys; sys.exit(0 if sys.argv[1] in json.load(open('config.json')).get('devices', {}) else 1)" "$name"; then
        echo "error: device '$name' already exists — revoke it first (delete from config.json) or pick another name" >&2
        exit 1
    fi
    "$0" add-device "$name" > /dev/null
    key=$(python3 -c "import json,sys; print(json.load(open('config.json'))['devices'][sys.argv[1]])" "$name")
    url=$(python3 -c "import json; print(json.load(open('config.json')).get('public_url') or 'http://<this-host>:8484')")
    if command -v systemctl > /dev/null && systemctl is-active --quiet claude-rotate 2> /dev/null; then
        # non-root operators need sudo for the reload; -n so we fail into the
        # hint instead of hanging on a password prompt (set -e must not kill
        # the block before the key is printed)
        if systemctl reload claude-rotate 2> /dev/null \
                || sudo -n systemctl reload claude-rotate 2> /dev/null; then
            echo "(reload sent to the service — key is live; if it is refused, see config.error in /rotate/status)"
        else
            echo "(key stored; the service loads it within reload_poll_s seconds, or run: sudo systemctl reload claude-rotate)"
        fi
    else
        echo "(a running rotator.py loads the key within reload_poll_s seconds, or on SIGHUP)"
    fi
    echo
    echo "──── paste this back to $user ────────────────────────────────"
    echo "Hi $user — your Claude access for '$dev' is ready."
    echo
    echo "Add these two lines to your shell profile (~/.zshrc or ~/.bashrc):"
    echo
    printf '  export ANTHROPIC_BASE_URL=%q\n' "$url"
    printf '  export CLAUDE_CODE_OAUTH_TOKEN=%q\n' "$key"
    echo
    echo "Open a new terminal and run 'claude' as usual — no login needed."
    echo "Usage dashboard: $url/rotate/panel?key=$key"
    echo "The key is personal to this device — don't share or commit it."
    echo "──────────────────────────────────────────────────────────────"
    ;;
add-account)
    for d in ${priv_devices[@]+"${priv_devices[@]}"}; do
        if ! python3 -c "import json,sys; sys.exit(0 if sys.argv[1] in json.load(open('config.json')).get('devices', {}) else 1)" "$d"; then
            echo "error: device '$d' is not registered — add it first (./setup.sh add-device $d)" >&2
            exit 1
        fi
    done
    if [ -n "$priv" ] && [ "$(printf '%s\n' "${priv_devices[@]}" | sort -u | wc -l)" -ne "${#priv_devices[@]}" ]; then
        echo "error: --private-to lists a device twice" >&2
        exit 1
    fi
    echo "Run 'claude setup-token' in a browser session logged into that account,"
    read -r -s -p "then paste the sk-ant-oat01-... token here (input hidden): " token
    echo
    case "$token" in sk-ant-oat01-*) ;; *) echo "error: token should start with sk-ant-oat01-" >&2; exit 1;; esac
    # Write, then rename: a running proxy that notices the change must never
    # read an empty or half-written token.
    tmp="tokens/.${name}.token.tmp"
    printf '%s' "$token" > "$tmp"
    chmod 600 "$tmp"
    mv -f "$tmp" "tokens/${name}.token"
    python3 - "$name" "$priv" <<'EOF'
import json, os, sys
name, priv = sys.argv[1], sys.argv[2]
cfg = json.load(open("config.json"))
acct = next((a for a in cfg["accounts"] if a["name"] == name), None)
if acct is None:
    acct = {"name": name, "token_file": f"tokens/{name}.token"}
    cfg["accounts"].append(acct)
if priv:
    owners = priv.split(",")
    acct["private_to"] = owners[0] if len(owners) == 1 else owners
    acct.setdefault("priority", 1)  # written out, so the owners spend it first
path = os.path.realpath("config.json")
with open(path + ".tmp", "w") as f:
    json.dump(cfg, f, indent=2)
os.replace(path + ".tmp", path)
EOF
    if [ -n "$priv" ]; then
        echo "account '$name' stored (private to: ${priv//,/, }). A running rotator.py loads it within reload_poll_s seconds, or on SIGHUP."
    else
        echo "account '$name' stored. A running rotator.py loads it within reload_poll_s seconds, or on SIGHUP."
    fi
    ;;
*)
    echo "unknown subcommand: $1" >&2; exit 1 ;;
esac
