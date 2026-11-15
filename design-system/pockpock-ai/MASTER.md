# PockPock AI design system

**Updated:** 2026-11-12  
**Scope:** Local AI router, conversations, model inventory, browser workflows, and research settings.

This system adapts the YourBrand dashboard template to PockPock's existing local-first product. The product's local execution, approval boundaries, telemetry, and navigation remain explicit. The template's violet glass visual language replaces the earlier mixed violet/teal treatment.

## Tokens

| Role | Value | CSS variable |
| --- | --- | --- |
| Canvas | `#05030f` | `--background` |
| Primary text | `#f4f2ff` | `--ink` |
| Muted text | `#a29bc4` | `--muted` |
| Dim text | `#77708f` | `--dim` |
| Glass surface | `rgba(255,255,255,.04)` | `--surface` |
| Violet accent | `#7c5cff` | `--accent` / legacy `--lime` alias |
| Lavender glow and focus | `#a78bfa` | `--glow` |
| Blue highlight | `#4aa3ff` | `--highlight` |
| Success status | `#3fb68b` | `--success` |
| Default border | `rgba(167,139,250,.18)` | `--line` |

Cards use a 12px radius, pills use a full radius, and glass surfaces use blur with a restrained violet edge. Headings use Space Grotesk when available with a system fallback; body text uses Inter with a system fallback; technical labels use JetBrains Mono with local monospace fallbacks. The app remains usable without downloading fonts.

## Layout and components

- Keep the local-status header compact and glassy; retain clear Ollama and router state.
- Use a persistent 236px workspace rail on desktop. Keep active navigation obvious and maintain direct access to local router control and conversation history.
- Give overview metrics, routing flow, request history, model health, and tool forms the same near-black translucent surfaces and lavender borders.
- Use violet for selected controls and primary actions, blue for secondary information, green for healthy/success status, and red/orange for failures and approvals that need attention.
- In Conversations, make the empty state an intentional welcome surface and keep the composer anchored at the bottom. Plan approvals, execution traces, and tool events remain distinct and readable.
- At 700px and below, use the existing slide-out workspace navigation, stack multi-column content, and keep the composer and form controls within the viewport.

## Motion and accessibility

Use short transform, opacity, border, and shadow transitions. Honor `prefers-reduced-motion`. Keep visible lavender focus rings, semantic state labels, keyboard access, readable contrast, and touch-sized controls. Status must not rely on color alone.

## Product constraints

PockPock remains local-first. Preserve existing API calls, persisted conversations and settings, Ollama controls, browser recipe permissions and approvals, and research network safeguards. Do not add cloud execution, account/login flows, prompt telemetry, or decorative fake product metrics.
