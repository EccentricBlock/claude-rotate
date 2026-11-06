# Context after compaction

Compaction summarises the conversation and drops files read mid-session. Only
`CLAUDE.md` and its `@import` lines reload on their own.

- Anything needed in every session belongs in `AGENTS.md`, which `CLAUDE.md`
  imports.
- Everything else goes in `.claude/post-compact-files`, one path per line,
  relative to the project root. This list is the project's own to edit.
- A `SessionStart` hook with matcher `compact` runs
  `.claude/hooks/post-compact.sh`. It prints each listed file under a
  `--- <path> ---` header, so the text returns to context.
- A listed file over 100 lines is not pasted. The hook tells the session to
  re-read it instead. A file of 100 lines or fewer but over 6,000 bytes pastes
  only its last whole lines that fit in 6,000 bytes, under a `--- <path> (last
  lines; re-read for the rest) ---` header. A missing file is skipped silently.
- A path followed by the word `tail` is a log whose recent part is its end. The
  hook pastes it whatever its line count: whole if it fits in 6,000 bytes, else
  the last whole lines that fit.
- Don't add a `PreCompact` hook by default. No script can refresh a state file
  without the session's input.
