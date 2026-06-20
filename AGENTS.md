## Agent skills

### Issue tracker

Issues live as GitHub issues; all operations use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles map 1:1 to labels of the same name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## AI-generated content

Mark output you produce as an AI agent with the robot emoji and an "AI-generated" note, so humans can tell at a glance what came from an agent.

- **Issues, PR descriptions, comments** — lead with `🤖 AI-generated —`. (The `review` skill already follows this spirit with its `🤖 AI review` prefix.)
- **Commit messages** — prefix the subject line with `🤖 ` (e.g. `🤖 fix: ...`) so the marker shows in `git log --oneline`.

Do **not** mark code, code comments, or committed files (`CONTEXT.md`, source, tests, docs) — those are reviewed via PRs and emojis in source are noise.
