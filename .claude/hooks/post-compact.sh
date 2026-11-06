#!/usr/bin/env bash
# SessionStart hook, matcher "compact". Restores the files named in
# .claude/post-compact-files, which compaction drops from context. Stdout
# from this hook is added to the session's context.
set -euo pipefail

root="${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR is not set}"
list="$root/.claude/post-compact-files"
max_lines=100
max_bytes=6000

[[ -f "$list" ]] || exit 0

while IFS= read -r path || [[ -n "$path" ]]; do
  path="${path%%#*}"
  path="${path#"${path%%[![:space:]]*}"}"
  path="${path%"${path##*[![:space:]]}"}"
  # A trailing "tail" word marks the file: paste its tail whatever its length.
  tailed=0
  if [[ "$path" == *[[:space:]]tail ]]; then
    tailed=1
    path="${path%tail}"
    path="${path%"${path##*[![:space:]]}"}"
  fi
  [[ -n "$path" && -f "$root/$path" ]] || continue
  if (( tailed || $(wc -l < "$root/$path") <= max_lines )); then
    if (( $(wc -c < "$root/$path") <= max_bytes )); then
      printf -- '--- %s ---\n' "$path"
      cat "$root/$path"
      printf '\n'
    else
      # Keep the newest lines: logs append, so the tail is the recent part.
      printf -- '--- %s (last lines; re-read for the rest) ---\n' "$path"
      tail -c "$max_bytes" "$root/$path" | tail -n +2
      printf '\n'
    fi
  else
    printf 'Re-read %s before continuing: it is too long to restore here.\n' "$path"
  fi
done < "$list"
