# Project contribution rules

These rules apply to every human or AI change in this repository.

## Branches and pull requests

- Follow the branch strategy in [`CONTRIBUTING.md`](CONTRIBUTING.md): `main` is protected and always releasable; work on a short-lived `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, `ci/` or `chore/` branch from `main` and merge it with a squash-merged pull request whose title follows Conventional Commits.
- Never push directly to `main`, force-push it, or rewrite its history. Releases are `v<major>.<minor>.<patch>` tags on `main`, created by maintainers.

## Roadmap task handoff

- When continuing the agent capability roadmap, read [`docs/TASKS.md`](docs/TASKS.md) and [`docs/ROADMAP.md`](docs/ROADMAP.md) before implementation.
- Put agent-invokable tool schemas, implementations, permission metadata, and focused tests under [`backend/projects/agent_tools/`](backend/projects/agent_tools/). Follow that project's README when adding or extending a tool.
- Select the highest-priority task marked `Ready` whose dependencies are complete. Claim it in the tracker before substantial edits, and do not take an `In progress` task owned by another agent without coordination.
- Update the task status and completion log in the same change as implementation. Mark `Done` only after its acceptance checks, documentation, and verification are complete. See `docs/TASKS.md` for the full handoff protocol.

## Keep documentation current

- Read the relevant pages under `docs/` and the matching README section before changing behavior.
- Update documentation in the same change as every new feature, user-visible behavior change, API change, permission change, or operational change. Do not leave documentation as a later follow-up.
- Document a feature in enough detail that another developer can operate and maintain it without reading the implementation first. Include its purpose, user flow, modules involved, data and control flow, API or tool contract, persistence effects, configuration, permission/security boundaries, failure states, and verification steps where applicable.
- Update `README.md` when setup, normal usage, supported behavior, permissions, or troubleshooting changes. Keep it a user guide; link to detailed feature docs instead of duplicating them.
- Update `docs/ARCHITECTURE.md` whenever modules, ownership boundaries, runtime components, persistence, or integration contracts change. Record important structural decisions and their tradeoffs there.
- Add or update a focused page under `docs/features/` for each substantial feature. Link it from `docs/FEATURES.md` so features have a discoverable index.
- Describe only behavior that exists and has been verified. Label planned architecture as planned; do not imply it is already implemented.
- Before finishing, check that documentation links and names match the implementation and that no older paragraph now contradicts the change.

## Implementation and verification

- Prefer cohesive modules with explicit ownership over a larger server, UI component, or tool file. Preserve the local-first deployment model unless the user asks to change it.
- Keep secrets, credentials, prompts, and private user content out of logs and telemetry. Preserve workspace and permission boundaries.
- Run the narrowest relevant existing validation after implementation. For the desktop app run `npm run typecheck` and `npm run build` in `desktop/`; for Python changes run `python -m py_compile` on changed modules and `backend/scripts/run_tests.py` (or the affected project's suite). Run tests when requested or when a change requires a test to establish correctness; report exactly what ran and its result.
- When validation fails, fix the cause and rerun it. Never report a check as passed unless it actually passed.
- Update this document only when the user explicitly changes project-wide contribution rules.

## UI/UX workflow

The user interface is the Electron desktop app in `desktop/` (React, TypeScript, Vite, plain CSS with tokens in `desktop/src/styles.css`). There is no web frontend.

- Follow [`design-system/pockpock-desktop.md`](design-system/pockpock-desktop.md) for tokens, layout and component rules. Use the project prompts in `.github/prompts/ui-ux-pro-max/` and the `frontend-design` skill when designing new screens, and update the design-system file when a rule changes.
- Reuse the existing components (`desktop/src/components/`) and page frame. Check current library APIs with Context7. If a Figma link is provided, read it with the configured Figma MCP server first.
- Keep privileged work in the main process (`desktop/electron/`). The renderer is sandboxed and reaches it only through named calls in `preload.cjs`; every new handler must check the caller with `handle()` and validate its arguments.
- After building, run the real app with Playwright's Electron driver (`_electron`), using `POCKPOCK_DESKTOP_USER_DATA` pointed at a temporary folder so real chats are untouched. Check a 1440×900 window and a narrow 820 px window, save screenshots, and fix console errors and visible issues.
- Before finishing, run the `web-design-guidelines` skill and fix accessibility findings: contrast, focus states, labels, keyboard navigation, and control sizes.
- Cover loading, empty, error and success states in every screen.
- Do not run tests that load models or restart the gateway or OpenClaw while the user may be using them; check `ollama ps` and recent Ollama requests first.
