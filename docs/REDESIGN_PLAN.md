# PockPock AI UI/UX Redesign Plan

## Goal

Make the local-first AI workspace easier to understand and operate on desktop and mobile. Preserve existing workflows and data while applying the violet glass visual language from the YourBrand dashboard template. Login is out of scope; the earlier login page was a toolchain smoke test, not a product feature.

## Product context

- React 19, TypeScript, Vite, Tailwind 3, custom CSS; no shadcn/ui.
- Main areas: Overview (router and model health), Conversations (chat, plans and approvals), Models, Browser recipes, and Research settings.
- The UI is currently composed in `frontend/app/src/App.tsx`, with styles in `frontend/app/src/App.css` and global tokens in `frontend/app/src/index.css`.
- Preserve local-only operation and existing API and permission behavior.

## Design direction

Use `design-system/pockpock-ai/MASTER.md` as the visual source of truth: near-black navy canvas, translucent glass panels, violet/lavender interaction accents, blue secondary information, green healthy status, Space Grotesk/Inter-style product text with local fallbacks, and JetBrains Mono for technical details. Keep interaction feedback visible, controls comfortable to tap, and motion reduced when requested. Do not add an authentication experience.

## Staged work

1. **Navigation and foundation (in progress):** make section names recognizable, make active navigation state semantic, improve type and control sizing, and establish responsive layout behavior.
2. **Overview:** prioritize connection state, router control, actionable model health, and explain empty/offline states in plain language.
3. **Conversations:** simplify starting/resuming work, distinguish plan approval from run activity, and improve composer and attachment affordances.
4. **Models and settings:** clarify availability, model actions, and research configuration with safer feedback and helpful defaults.
5. **Accessibility and polish:** review keyboard flow, focus, contrast, labels, touch targets, loading/empty/error/success feedback, and layouts at 390px and 1440px.

## Acceptance checks

- Existing workflows and permission gates continue to work.
- Navigation is understandable without relying on numbered shortcuts or technical jargon.
- Controls remain usable at narrow mobile widths with no horizontal page overflow.
- Async actions expose pending, success, and error feedback; empty areas explain the next useful action.
- No login or credential collection is introduced.

## Progress

- [x] Inspect application context and existing UI toolchain setup.
- [x] Review and retain the repository's established design system.
- [x] Document redesign scope and stages.
- [x] Improve navigation and shared interface sizing.
- [x] Improve overview copy and explain the request flow in plain language.
- [x] Review responsive behavior at 390px and 1440px; no horizontal overflow found.
- [x] Apply the shared violet glass system to overview, conversations, model inventory, browser workflows, and research settings.
- [x] Review primary layouts at 390px, 820px, and 1440px and check for browser errors and horizontal overflow.
- [ ] Complete accessibility review across all workflows and states.
