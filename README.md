# sec-team

Agent skills for the Omen Security team. Each skill is a folder under
[`skills/`](skills/) with a `SKILL.md` that Claude Code (and other agents
that read the `SKILL.md` format) loads on demand.

## Skills

| Skill | What it does |
|---|---|
| [`security-board-breakdown`](skills/security-board-breakdown/SKILL.md) | Start-of-day breakdown of the SECT and RISK Linear boards, read-only towards Linear, GitLab and Slack. For every In Progress or In Review ticket it lists what is left to close it and who has to act, the linked MRs with status grouped by owning team, recorded contact with each owner, and what changed since the last run. |

## Install

Link each skill into your user skills folder, so it is available in every
session:

```bash
git clone git@gitlab.com:omen-trade/llm/agent-skills/sec-team.git ~/Work/projects/sec-team
mkdir -p ~/.claude/skills
ln -s ~/Work/projects/sec-team/skills/security-board-breakdown ~/.claude/skills/security-board-breakdown
```

Because it is a symlink, `git pull` here updates the skill. If a newly
linked skill does not appear, restart Claude Code.

## Requirements

`security-board-breakdown` needs:

- **Linear MCP server**, connected with read access to the boards.
- **Harness checkout** for `registry/org.yml` and `scripts/registry.py`.
  It looks in `$OMEN_HARNESS`, then `~/Work/projects/harness`.
- **`python3`** to run the registry script.
- **`glab`, logged in** (`glab auth login`), and **`jq`**, for live MR
  state. Without them the skill falls back to the newest Linear comment and
  says so.
- Optional: **Slack MCP server**, so contact evidence covers Slack as well
  as Linear.

## Usage

In Claude Code, from any directory:

```text
/security-board-breakdown
```

Or ask in plain words, for example "give me the security breakdown for
today". To change the scope, name it: "run the security breakdown for SECT
only" or "include Todo tickets".

The run is read-only towards Linear, GitLab and Slack. It writes one file
for the default scope: a snapshot under
`${XDG_STATE_HOME:-$HOME/.local/state}/sec-team/board-breakdown/<date>.json`,
created readable only by you. The next run compares against it to report
what changed. Runs with another scope do not write or compare. The snapshot
holds ticket keys, statuses and remaining items, so keep it on your own
machine. The output describes unfixed vulnerabilities: do not paste it into
shared channels.

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description`
   frontmatter. The description says what the skill does and when to use
   it, since agents choose skills by it.
2. Keep skills read-only unless the skill's purpose is to change something,
   and then list every write in the skill.
3. Add a row to the table above and open an MR.
