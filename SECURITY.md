# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's "Report a vulnerability" button on this repository
(Security tab), not in a public issue. You should get a first answer within five working days. Include the version
or commit, what you did, what happened and, if you can, a minimal way to reproduce it.

## What depgate can do in your repository

depgate acts with the token you give it. With the permissions in the example workflow it can:

| Permission | Used for |
|---|---|
| `pull-requests: write` | labels, the summary comment, review requests and the approving review |
| `contents: write` | enabling auto-merge on a pull request |
| `statuses: write` | the `depgate` commit status |
| `checks: read` | reading your CI result |

It never pushes code, never merges directly (it turns on GitHub's auto-merge, which still waits for your required
checks and branch protection) and only acts on single-package Dependabot or Renovate pull requests. Auto-merge
can be turned off per repository (`auto_merge.enabled: false`), and `dry_run: true` makes it comment in the job
log only.

The example workflow runs on `workflow_run`, which executes the workflow file from your default branch. No code
from the update pull request is checked out or run by depgate.

## Data handling

For each update pull request, depgate builds one small JSON "state" and sends it to the decision backend:

| Sent | Not sent |
|---|---|
| Package name, ecosystem, old and new version | Your source files |
| Public release notes between the versions (trimmed to about 5,000 characters) | Your secrets or environment variables |
| Public security advisories for the package | The pull request diff |
| The CI result (`success`, `failure`, `pending`) | Commit history, authors or other pull requests |
| Up to 25 short `file:line: code` lines where your code imports or calls the package |  |

- **Where it goes.** With the `jev` backend the state goes to the TypeSafe AI API (`api.typesafe.ai`). With the
  `llm` backend it goes to the OpenAI-compatible endpoint you configure. The `rules` backend sends nothing.
- **Redaction.** Before anything is sent, every usage line and the release notes pass through a redactor that
  replaces likely secrets with `[REDACTED]`: private key blocks, common token formats, `password=`/`token=`/
  `api_key=`-style assignments, `Bearer` and `Basic` credentials, and credentials inside URLs. References such as
  `process.env.X`, `os.environ[...]` and `${{ secrets.X }}` are kept. The comment notes how many values were
  redacted. Redaction is a safety net, not a guarantee: keep secrets out of source code.
- **Public lookups.** Release notes and advisories come from public endpoints (npm registry, PyPI, GitHub REST)
  and are cached on disk in `.depgate/cache/`.
- **Audit log.** Every decision is appended to a JSONL audit log (`.depgate/audit.jsonl` by default; `/data/audit.jsonl`
  in the container): package, versions, answers, confidence, action taken, latency, tokens and cost. It contains
  no source code beyond the usage lines' file names. Rotate or ship it like any other application log.
- **Secrets depgate needs.** `TYPESAFE_API_KEY` (or `AI_API_KEY`), the GitHub token, optionally
  `DEPGATE_WEBHOOK_SECRET` and chat webhook URLs. Store them as repository, organisation or Dependabot secrets
  (Actions) or in your secret manager (container). depgate never logs or prints them.

## Webhook service

The self-hosted service rejects every webhook without a valid `X-Hub-Signature-256` signature for
`DEPGATE_WEBHOOK_SECRET`, and refuses to start without that secret. Run it behind HTTPS. The container runs as an
unprivileged user and writes only to `/data`.
