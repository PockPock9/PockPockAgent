# PockPock Agent desktop design system

**Updated:** 2026-11-15
**Scope:** The Electron desktop app in `desktop/`. The web dashboard keeps [pockpock-ai](pockpock-ai/MASTER.md).

The desktop app is a work tool used for long sessions, so it uses flat, quiet surfaces in the style of code-editor agents instead of the web dashboard's glass and animated background. PockPock's violet stays the single accent.

## Tokens (`desktop/src/styles.css`, `:root`)

| Role | Value | Variable |
|---|---|---|
| Canvas | `#0d1014` | `--bg` |
| Sidebar and side panels | `#111419` | `--bg-side` |
| Cards inside the thread | `#10141a` | `--bg-panel` |
| Raised controls, composer | `#171c24` | `--bg-raise` |
| Hover / selected | `#1c222b` / `#232a35` | `--bg-hover` / `--bg-active` |
| Borders | `#222933`, strong `#2e3744` | `--border`, `--border-strong` |
| Text | `#e6ebf1`, secondary `#aeb8c6`, tertiary `#8892a1` | `--text`, `--text-2`, `--text-3` |
| Accent | `#8b6cff`, strong `#a78bfa`, tint `rgba(139,108,255,.14)` | `--accent`, `--accent-strong`, `--accent-bg` |
| Status | ok `#3fb68b`, warning `#e5a83b`, error `#f07470`, info `#5aaaf5` | `--ok`, `--warn`, `--err`, `--info` |

Type: Segoe UI Variable (Windows UI font) at 13.5 px body, 26 px welcome heading, 22 px page headings; Cascadia Code for code, paths and the terminal. Radius 8 px for controls and cards, 12 px for the composer, full for chips and the send button.

## Layout

- Grid: title bar 38 px, status bar 24 px; sidebar 252 px, files 272 px, terminal 260 px high.
- Title bar is the window drag area. Native caption buttons sit on the right (Windows title-bar overlay); 150 px is reserved for them.
- The conversation and every Customize page use one centred column, `min(820px, 100% - 48px)`.
- Below 1100 px the files panel, and below 860 px the sidebar, open as overlays with a backdrop.

## Components

- **Composer:** context chips above it (This PC, open folder, mode with a status dot), then the input, then a bar with + (attach and navigate), mode, permission and model pickers, and the send/stop button.
- **Pickers** open as popovers above their button with a title and one-line explanation per option; the selected option is tinted and checked. Risky choices (Full access) use the warning colour in the picker and on the chip.
- **Cards** in the thread (plan review, approval, skill/MCP install) share one style; a card waiting for the user has an accent border and ring. Primary action is filled violet, the others outlined.
- **Steps** collapse to one summary line ("Worked through 7 steps" or the running step) and expand to the full list with status icons.
- **Rows** on Customize pages: icon, title, secondary line, optional description, then a switch and/or a remove button.

## States and accessibility

- Every list and page covers loading (spinner and text), empty (what to do next), error (banner with the reason) and success.
- Status never relies on colour alone: dots are paired with text, steps with icons and words.
- Visible focus ring (2 px `--accent-strong`), keyboard shortcuts for all panels, menus close with Escape, switches use `role="switch"`.
- Controls are at least 30 px high (32–36 px for primary actions); the desktop app targets mouse and keyboard.
- `prefers-reduced-motion` turns off animation.
