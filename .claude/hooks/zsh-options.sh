#!/usr/bin/env bash
# SessionStart hook, no matcher. Appends a line to the session's env file, which
# Claude Code runs as shell code before each Bash command. In zsh, it turns off
# equals expansion (`echo ===` fails) and nomatch errors (an unmatched glob
# aborts the command). The ZSH_VERSION guard keeps a bash shell from failing on
# `setopt`; the `if` form exits 0 where `[ ... ] && setopt` exits 1.
set -euo pipefail

[[ -n "${CLAUDE_ENV_FILE:-}" ]] || exit 0

line='if [ -n "${ZSH_VERSION:-}" ]; then setopt no_equals no_nomatch; fi'
printf '%s\n' "$line" >> "$CLAUDE_ENV_FILE"
