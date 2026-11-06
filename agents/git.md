# Git workflow

- **Commit early, commit often.** Split work into small commits, each a single
  coherent change. Don't batch everything into one commit at the end.
- **Verify before committing.** Each commit leaves the project working. Run it,
  exercise the changed logic, and re-run the tests before committing, not
  after.
- **Sequence edits to match commit boundaries. Don't backtrack to create them.**
  Write and commit one part's changes before starting the next part's. Don't
  write several commits' worth of changes into the tree, then hand-revert
  pieces to split them apart: that relies on exact transcription, and it is an
  easy way to lose a line. If a file already has unrelated uncommitted changes,
  set them aside first with `git stash push -- <path>`, then `git stash pop`.
- **Commit message standard:**
  - A conventional prefix: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`,
    `test:`.
  - A concise imperative subject ("add X", not "added X" or "adds X").
  - A body that explains *why*, whenever the subject alone doesn't.
  - No tool-attribution trailers.
- **Push when the work is complete, not after each commit.** A local commit is
  cheap to amend, reorder or drop. A pushed one is not. Keep the branch local
  while the task is moving, then push the series once it is finished and
  verified. Push mid-task only when something else needs it: another machine
  or a CI run.
- **Never end a session with finished work unpushed.** Push before stopping. If
  something must stay local, say so and say why. If the push is refused (for
  example a credentials error), report the exact error and leave the commits
  local. Don't try other remotes or credentials.
- **Autonomous commits and pushes.** Unless told otherwise, stage and commit as
  you go, and push the finished series, without asking each time. See
  "Autonomy" in `AGENTS.md` for what needs approval first. None of these
  apply:
  - `--no-verify` or another hook-skipping flag.
  - A force-push.
  - Amending a commit that has already been pushed.
  - Another destructive operation (`reset --hard`, `clean -f`, `branch -D`)
    without explicit permission.
  - `git add` by anything other than a named file (no `-A`, no `.`).
- **Merging another fork's work.** Use a true merge (`git merge --no-ff`) so the
  original commits and their authorship stay in history. Resolve conflicts in
  favour of keeping both sides' behaviour, run the full test suite, and name
  the source in the merge commit subject.
- **Never stage a sandbox placeholder.** The sandbox mounts `/dev/null` over
  paths a command must not write. Each appears as a character device or an
  empty read-only file. Find them with
  `find . -type c -o \( -type f -size 0 -perm 444 \)`.
  - The set includes these names, and is never limited to them. Root
    dotfiles: `.bash_profile`, `.bashrc`, `.profile`, `.zprofile`, `.zshrc`,
    `.gitconfig`, `.gitmodules`, `.ripgreprc`, `.mcp.json`, `.idea`,
    `.vscode`. Under `.claude/`: `agents`, `commands`, `hooks`,
    `launch.json`, `loop.md`, `output-styles`, `routines`,
    `scheduled_tasks.json`, `settings.json`, `settings.local.json`, `skills`,
    `workflows`. Also `.git/config.lock`.
  - Never stage, delete or `git add` a directory over one. Before each commit,
    check `git status` for a staged `.claude/*` or `.mcp.json` path.
  - `.git/config.lock` is a character device, not a stale lock. Git fails with
    "File exists" when it writes `.git/config`, for example when adding a
    remote. Ask the operator to run that command with the `!` prefix.
  - `.gitignore` lists each name. `.claude/settings.json` and `.claude/hooks`
    are real files in this repo, so they are re-included with `!/`. Never list
    `.claude/` wholesale.
