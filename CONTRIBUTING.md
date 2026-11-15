# Contributing to PockPock Agent

Thanks for helping. This page explains how changes flow into the project. Project rules for code, documentation and UI work are in [AGENTS.md](AGENTS.md); they apply to every change, by people and AI assistants alike.

## Ways to help

- **Report a bug** or **suggest a feature** with the [issue forms](../../issues/new/choose).
- **Ask a question** or share an idea in [Discussions](../../discussions).
- **Fix or build something**: look for issues labelled `good first issue` or `help wanted`, or pick a `Ready` task in [docs/TASKS.md](docs/TASKS.md). Comment on the issue first so work is not duplicated.
- **Report a security problem** privately, as described in [SECURITY.md](SECURITY.md). Never in a public issue.

## Branch strategy

PockPock uses **GitHub Flow** with short-lived branches and squash merges.

| Branch | Purpose | Rules |
|---|---|---|
| `main` | Always working and releasable. Every release is a tag on `main`. | Protected: changes only through pull requests, required checks must pass, history stays linear, no force-push or deletion. |
| `feat/<short-name>` | A new feature | Branch from `main`, open a pull request back to `main`. |
| `fix/<short-name>` | A bug fix | Same. Reference the issue (`Fixes #123`). |
| `docs/…`, `refactor/…`, `test/…`, `ci/…`, `chore/…` | Documentation, internal changes, tests, CI, maintenance | Same. |
| `release/<major>.<minor>` | Only when an older release needs a fix after `main` has moved on | Created by maintainers on demand; fixes land on `main` first and are cherry-picked. |

Releases: maintainers tag `main` with `v<major>.<minor>.<patch>` (for example `v0.2.0`). The tag starts the **Desktop installers** workflow, which builds the Windows installer and the macOS disk images. Version numbers follow [Semantic Versioning](https://semver.org/).

### Step by step

1. **Fork** the repository (maintainers may branch in the main repository instead).
2. Create a branch from the latest `main`:
   ```bash
   git switch main && git pull
   git switch -c fix/setup-ollama-path
   ```
3. Make the change, **with its documentation and tests in the same branch** (see [AGENTS.md](AGENTS.md)).
4. Run the checks locally:
   ```bash
   .venv/bin/python backend/scripts/run_tests.py      # Windows: .venv\Scripts\python.exe backend\scripts\run_tests.py
   cd desktop && npm run typecheck && npm run build
   ```
5. Commit with a clear message. We use [Conventional Commits](https://www.conventionalcommits.org/) style, because the squash-merge title becomes the commit on `main`:
   ```text
   fix(setup): find Ollama.app in ~/Applications on macOS
   feat(agent): show elapsed time on long steps
   docs: explain the final setup check
   ```
   Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `ci`, `chore`. Add `!` for a breaking change (`feat!: …`).
6. Push and open a **pull request to `main`**. Fill in the template, link the issue, and include screenshots for UI changes.
7. CI runs the backend tests on Windows, macOS and Linux and the desktop build on Windows and macOS. A maintainer reviews. Keep the branch up to date with `main` (the **Update branch** button is fine).
8. The pull request is **squash-merged** and its branch deleted automatically.

Keep pull requests small and focused on one thing; they are reviewed faster. Draft pull requests are welcome for early feedback.

## Development setup

See [Development](../../wiki/Development) in the wiki, or the "For developers" section of the [README](README.md). In short: Python 3.12, Node.js 24 and Ollama; `python backend/scripts/pockpock.py setup`; then `npm install && npm run build && npm run app` in `desktop/`.

## What reviewers look for

- The change does what the pull request says, and nothing else.
- Tests cover new behaviour; all checks pass.
- Documentation is updated in the same pull request (README for user-visible changes, `docs/` for features and architecture).
- Permission and privacy boundaries are kept: no secrets, prompts or private content in logs; agent actions still go through approval.
- UI changes follow [design-system/pockpock-desktop.md](design-system/pockpock-desktop.md) and work at 1440 px and 820 px wide, on Windows and macOS.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE), the project's license. Do not submit code you do not have the right to license that way.

## Code of conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
