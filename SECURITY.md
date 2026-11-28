# Security policy

PockPock Agent runs AI agents that can read files, run commands and operate a browser on the user's computer, so security reports matter a lot to us.

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub: go to the **Security** tab → **Report a vulnerability** ([direct link](../../security/advisories/new)).

Please include:

- what is affected (component, version or commit, Windows/macOS);
- how to reproduce it, step by step;
- what an attacker could achieve;
- any suggested fix.

We aim to acknowledge reports within 7 days, agree on a fix and disclosure date with you, and credit you in the advisory unless you prefer otherwise.

## Supported versions

Security fixes go into `main` and the next release. Older releases are not patched unless a maintainer opens a `release/<major>.<minor>` branch for a serious issue.

## What counts

Examples of issues we want to hear about:

- an agent acting without the approval its permission mode requires;
- escaping the task folder or the open folder;
- the local API or internal services accepting requests from another computer or another local origin;
- secrets, prompts or private content written to logs or telemetry;
- installer or setup steps that run unverified downloads or can be hijacked.

Third-party skills and MCP servers are code the user chooses to install. PockPock shows their source and asks before installing, but does not review them; a malicious skill is not a PockPock vulnerability unless it gets past that approval.
