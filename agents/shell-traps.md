# Shell traps

The shell is zsh. These faults recur. Each line names the trap and its fix.

- `echo ===` fails: zsh's equals expansion prints `== not found`. Quote it:
  `echo '==='`.
- An unquoted glob that matches nothing is an error. zsh prints `no matches
  found` and runs nothing (for example `ls dir/*x*`, `--include=*.yml`). Quote
  the glob or use `find`.
- `.claude/hooks/zsh-options.sh`, where installed, turns both of the traps
  above off for the session's own Bash calls. Keep the quotes anyway: the hook
  may not reach subagents or every host's zsh.
- zsh does not word-split an unquoted `$var`. `for x in $v` runs once. Use an
  array, or `for x in a b c`.
- jq fails on a null field. Write `(.labels // [])[]`.
- `select(A) or (B)` never returns the record. Write `select(A or (B))`.
- jq reads a path starting with `-` as an option and dumps usage. Prefix `./`.
- In jq `A | B as $x | body`, body's input is A's output. Bind `. as $all` first
  to keep the original.
- jq `capture()` with no match yields nothing, and drops the whole object built
  from it. Write `(... // "none")`.
- jq lexes `?//` as its destructuring-alternative operator. Write `.x? // ""`
  with spaces.
- `find -exec ... '{}'` replaces a literal `{}` inside the jq program too. Seed
  with `null` instead.
- `dcg` matches a destructive command name inside quoted text: `blkdiscard` in a
  jq string or a commit message is blocked. Break the word, as in
  `blk[d]iscard`, or reword.
- `dcg` blocks a redirect to a `$VAR` path. Run the command unredirected, or
  use Write. More in `agents/scratch.md`.
- `dcg` blocks a multi-line heredoc. Use Write.
- `dcg` blocks a quoted angle bracket in a jq program, and a long inline jq
  program. Put the program in a script file or split it.
- Never pipe the test runner through `tail`: `$?` is then `tail`'s. Run it
  unpiped and quote its own exit code.
- A bare `python3` may lack the project's dependencies. Use `.venv/bin/python`.
- `git push` over SSH can authenticate as a different GitHub account from the
  one that owns the repo. Report the "Permission denied to <account>" error to
  the operator; don't try other keys or remotes.
