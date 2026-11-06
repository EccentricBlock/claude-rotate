# Scratch and temp files

- **Never shell out to `rm` for scratch cleanup.** Use `mktemp -d` for a fresh
  unique directory, since there is nothing to delete afterwards. Or clean up
  inside the language you are already in (`tempfile.TemporaryDirectory()`,
  `shutil.rmtree`).
- Why: the `ask` rule on `Bash(rm -rf*)` is deliberate. Claude Code splits a
  compound command at `&&`, `||`, `;`, `|`, `|&`, `&` and newlines, then matches
  each part separately. An `allow` rule has to cover every part. An `ask` rule
  fires when any one part matches. So a narrower `allow` rule for a temp path
  can't cancel the `ask` on the `rm` beside it. Change the shape of the
  command, not the permission list.
- Use the session's scratch directory, or `$TMPDIR`, for anything that doesn't
  belong in the repo. Don't create `config.json`, `tokens/` or log directories
  outside a scratch copy when testing.
- **Some paths are read-only to Bash:** the memory index under
  `~/.claude/projects/`, `~/.claude/plans/*.md`, and `.git/config` (via
  `.git/config.lock`). Use Write or Edit for memory and plan files, and hand
  the rest to the operator.
- **Run `cd` as its own call, and check `pwd` before a relative path.** After a
  `cd` into a subdirectory, a later repo-relative call fails. Prefer absolute
  paths where the tool allows.
- **Write files with Write or Edit; `dcg` blocks some shell forms.** Check a
  command without running it with `dcg explain "<command>"`:
  - Blocked: a redirect to a `$VAR` path (`echo hi > $S/x`, rule
    `redirect-truncate-dynamic-path`), and `rm -rf "$TMPDIR/scratch"` (rule
    `rm-rf-general`).
  - Blocked: `git show <ref>:<path> > <path>`, because it overwrites the
    working-tree file even inside a scratch copy. Use `git archive <ref>
    <path> | tar -x -C <dir>`, or redirect to a different filename.
  - Allowed: `rm -rf /tmp/<dir>`, a redirect to a literal path, an append
    (`>>`), a single-line heredoc to a literal path, and `mkdir -p` on a fresh
    path.
  - Trust the live hook over `dcg explain` for multi-line or embedded-code
    heredocs, and don't test one inside a wrapper command.
  - `dcg` blocks `chmod +x` on a script path. Retry as a plain `chmod` on a
    literal path.
  - `dcg` blocks a compound `sed -n ... && python`. Split it into single
    commands.
  - `dcg` blocks `mkdir -p dir && cat > file`. Run `mkdir` alone, then write
    the file with Write.
  - `dcg` blocks `git branch` with a `$(...)` argument. Resolve the hash first,
    then pass it.
