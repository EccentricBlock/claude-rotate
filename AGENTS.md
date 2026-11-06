# AGENTS.md

claude-rotate is a small self-hosted proxy that lets Claude Code use several
Claude subscriptions and switches accounts when one reaches its rate limit.

This file carries working conventions: how to work in this repo. It does not
carry the design. `README.md` and the code are the design.

## Document map

- **`README.md`** is the contract for users: setup, configuration keys and
  their defaults, rotation policy. Its config table is the reference for
  every key in `config.json`.
- **`SECURITY.md`** records the threat model and what the panel exposes.
- **`OPERATIONS.md`** and **`deploy/README.md`** cover running the service.
- **`ONBOARDING.md`** covers adding accounts and devices.

If a decision is not covered by these files or the code, stop and ask. Do not
invent a name, default or behaviour.

`CLAUDE.md` holds only `@AGENTS.md`, so the instructions load in a session that
cannot read this file directly. Edit this file, never that import line.

## Session start

Check for stale work before starting. Run `git fetch origin`, then
`git rev-list --count HEAD..@{u}`.

- Zero: proceed.
- Behind with a clean tree: `git pull --ff-only`, then proceed.
- Behind with uncommitted changes, diverged, or a detached HEAD: stop and say
  so. Do not pull, rebase or guess.
- Fetch fails (offline, auth): say so and ask whether to proceed on local
  state. Never proceed silently.

Read `agents/shell-traps.md` at the start of every session.

## Documentation style

These rules apply to prose written in this repo: `AGENTS.md`, `agents/`, and
new or rewritten sections of the other docs. Text that arrived from another
fork is not swept to match, so later merges stay clean.

- Prose-only rules are in `agents/documentation-style.md`.
- Avoid filler openers, padding connectors and slop-jargon. Banned words and
  phrases: delve, leverage, unlock, empower, harness, foster, streamline,
  showcase, underscore, robust, seamless, holistic, comprehensive, cutting-edge,
  meticulous, nuanced, myriad, plethora, crucial, pivotal, landscape, realm,
  journey, ecosystem, synergy, deep dive, game-changer, low-hanging fruit,
  "it's worth noting", "it's important to note", "that said", "when it comes
  to", "in conclusion", "not only X but also Y", "isn't just X, it's Y".
  - A banned word used in its literal technical sense stays.
- No em dashes. Use UK English (behaviour, licence as a noun, organise).
- Wrap lines at 80 columns in `AGENTS.md` and `agents/`. Four things stay
  unwrapped: fenced code blocks, table rows, lines that hold a URL, and a
  single token longer than the line.
- Name a commit or PR by its readable title first, with the id in brackets
  after. Never lead with an id alone.

## Implementation

- Do exactly what the change needs: no extra options, handlers or tests.
- Follow the library's official usage instead of inventing custom logic.
- Check for an existing helper before writing a new one. Put a genuinely new
  helper in the shared module, not at the call site.
- Keep the project's design constraints: one `rotator.py` until that
  genuinely hurts, and only fastapi, httpx and uvicorn as dependencies.
- Verify any claim about Anthropic behaviour against the live API, with
  `phase0_proxy.py`, before relying on it. Ask first: that uses a real account.
- Settle ambiguity up front by asking, so the work is a mechanical series of
  steps.

## Keeping the README current

A functional change updates the README in the same commit. A fix without its
README update is not finished.

- A functional change is a new or changed config key, default, endpoint,
  `/rotate/status` field, panel feature, CLI or install step, or rotation
  behaviour.
- Put a config key in the "Configuration" table, with a default that matches
  the code. Put behaviour in the section that describes it, such as "Rotation
  policy", "Analytics panel", "OpenAI-compatible endpoint" or
  "Troubleshooting".
- Add a one-line bullet under "Fork changes", "mrglrlgrlgrl/claude-rotate",
  that links the commit or PR. Docs-only, test-only and refactor commits get
  no bullet.
- A change to running or securing the service updates `OPERATIONS.md`,
  `SECURITY.md` or `deploy/README.md` too, or instead.
- New README prose follows the documentation style. Text around it is not
  rewritten to match.

## Autonomy

Commit and push without asking for low-impact changes. Each commit stays
small and coherent.

- **No need to ask.** Docs, tests, comments, config examples, and small fixes
  that tests cover, with their README update. A clean push (no force, no
  rewritten history) never needs asking.
- **Commit once the plan is approved; push when the tests pass.** Anything that
  changes rotation, auth, quota or proxy behaviour.
- **Always ask first.**
  - A force-push, rewriting pushed history, `reset --hard`, `clean -f` or
    `branch -D`.
  - Reading, moving or changing real tokens, `config.json` or `tokens/`.
  - Any call to the live Anthropic API with a real account.
  - Deploying, restarting or uninstalling the service: `install.sh`,
    `uninstall.sh`, systemd, or the admin CLI against a live install.
  - Anything posted to another repo: a PR, issue or comment.
  - Merging changes from another fork.

Commit and push mechanics are in `agents/git.md`.

## Build and test

Use a virtualenv and call tools by their full path (`.venv/bin/python`). A
bare interpreter may lack the dependencies, and tests then appear to pass
because they never ran.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`tests/` needs a fixture config. Create it once; every file below is already
git-ignored:

```
cp config.example.json config.json
mkdir -p tokens logs
echo sk-ant-oat01-ci-dummy-token > tokens/acct-1.token
echo sk-ant-oat01-ci-dummy-token > tokens/acct-2.token
./setup.sh add-device ci-runner
```

Run `.venv/bin/python tests/run_all.py` before every commit that touches code.
Run it unpiped: piping through `tail` replaces its exit code with `tail`'s.

Tests assert real outcomes: the output, the resulting state, the specific
error for a bad input. A test that only checks the code ran is close to
worthless. A fake upstream response must provide every method the code calls,
such as `aiter_bytes`.

## Secrets and output

- Never hardcode or commit an API key, token, password or private key.
- Never commit `config.json`, `tokens/`, `state.json`, usage files or logs.
  `.gitignore` covers them. Add each new runtime path to it when you
  introduce it.
- Generated output can carry secrets the code never touched, such as a
  captured header or log line. Route it to an ignored directory.

## Context after compaction

Only `CLAUDE.md` and its `@import` lines reload. `.claude/post-compact-files`
lists the files the post-compact hook pastes back, one path per line. Read
`agents/compaction.md` before editing that list or a hook.

## Files loaded on demand

Read a file when its trigger applies.

- Before committing a functional change: "Keeping the README current" above.
- Before committing or pushing: `agents/git.md`.
- Before writing prose in `AGENTS.md` or `agents/`:
  `agents/documentation-style.md`.
- Before writing scratch or temp files: `agents/scratch.md`.
- At session start: `agents/shell-traps.md`.
- Before editing `.claude/post-compact-files` or a hook:
  `agents/compaction.md`.
- Before changing a rule in this file or `agents/`:
  `agents/changing-a-convention.md`.
