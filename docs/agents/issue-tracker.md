# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Auto-closing issues from PR bodies

GitHub closes issues referenced by auto-close keywords (`Closes`, `Fixes`, `Resolves`) in a **merged** PR's title or body. Two gotchas to avoid:

- **One keyword per issue, on its own line or clearly separated.** The comma-list form — `Closes #2, #3` — closes **only the first** issue; the rest are silently ignored. Write each on its own line:
  ```
  Closes #2
  Closes #3
  ```
- **Only merge the PR once the auto-close set is correct.** Editing the body after merge does **not** retroactively open/close issues. If a PR wrongly auto-closes an issue (e.g. a fix shipped opt-in, not by default), reopen it with `gh issue reopen <n> --comment "..."` and explain why; if it fails to auto-close one that should be (comma-list bug, typo), close it manually with `gh issue close <n> --comment "..."`.

Before merging a PR that auto-closes issues, verify the keyword list against the intended close set and confirm each referenced issue is actually resolved **in the default configuration**, not behind an opt-in toggle.
