# Project contribution rules

These rules apply to every human or AI change in this repository.

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
- Run the narrowest relevant existing validation after implementation. For the frontend use `npm run build`; for Python changes use `python -m py_compile` on changed modules and relevant project validation. Run tests when requested or when a change requires a test to establish correctness; report exactly what ran and its result.
- When validation fails, fix the cause and rerun it. Never report a check as passed unless it actually passed.
- Update this document only when the user explicitly changes project-wide contribution rules.

## UI/UX workflow

- Before building UI, use the project-installed UI/UX Pro Max prompt in `.github/prompts/ui-ux-pro-max/` to settle the design system: palette, type scale, spacing, and component rules. Save the verified system in the repository under `design-system/`, with page-specific overrides only when needed.
- Build with the installed `frontend-design` skill and the project's existing React, TypeScript, and Tailwind stack. Reuse existing components. This project does not currently use shadcn/ui; use its components only if the project adopts that library. Check current library APIs with Context7.
- If a Figma link is provided, retrieve its context with the configured Figma MCP server before implementation.
- After building, open the page with Playwright at 390px mobile and 1440px desktop widths. Save screenshots, inspect the browser console for errors, and fix visible issues.
- Before finishing, run the installed `web-design-guidelines` skill and fix accessibility findings, including contrast, focus states, labels, keyboard navigation, and touch targets.
- Cover loading, empty, error, and success states in every UI workflow.
