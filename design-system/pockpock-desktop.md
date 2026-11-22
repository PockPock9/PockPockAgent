# PockPock Agent desktop design system

**Updated:** 2026-11-21 (Agent Studio shell: rail, task list, run bar, inspector, command palette)
**Scope:** The Electron desktop app in `desktop/`, the only PockPock interface.

The desktop app is a work tool used for long sessions, so it uses flat, quiet surfaces in the style of code-editor agents instead of glass effects or animated backgrounds. PockPock's violet stays the single accent.

## Tokens (`desktop/src/styles.css`)

Every colour in the interface is a custom property. Components use only tokens, never literal colours (the exceptions are theme previews in the picker, `src/lib/theme.ts`, and the terminal's ANSI palettes there). All colour tokens are themed: `:root` holds **PockPock Dark**, the default, and each `:root[data-theme="…"]` block overrides them (see [Themes](#themes)). Radius and fonts are not themed.

PockPock Dark keeps violet `#8b6cff` as its accent. Its values:

| Role | Value | Variable |
|---|---|---|
| Canvas | `#0d1014` | `--bg` |
| Sidebar and side panels | `#111419` | `--bg-side` |
| Cards inside the thread | `#10141a` | `--bg-panel` |
| Raised controls, composer | `#171c24` | `--bg-raise` |
| Hover / selected | `#1c222b` / `#232a35` | `--bg-hover` / `--bg-active` |
| Popovers / code, diffs, logs | `#161b22` / `#0a0d11` | `--bg-popover` / `--bg-code` |
| Borders | `#222933`, strong `#2e3744`, hover `#3b4554` | `--border`, `--border-strong`, `--border-hover` |
| Input, composer and switch borders | `#5c6878` | `--control-border` |
| Text | `#e6ebf1`, secondary `#aeb8c6`, tertiary `#8892a1` | `--text`, `--text-2`, `--text-3` |
| Code and log text | `#d3dbe6`, `#c9d2de` | `--code-text`, `--log-text` |
| Accent | `#8b6cff`, strong `#a78bfa`, tint `rgba(139,108,255,.14)` | `--accent`, `--accent-strong`, `--accent-bg` |
| Filled accent controls | `#6f52f0`, hover `#6342e6`, text `#fff` | `--accent-fill`, `--accent-fill-hover`, `--on-accent` |
| Waiting card border and ring | `--accent`, `rgba(139,108,255,.1)` | `--accent-border`, `--accent-ring` |
| Focus ring | `--accent-strong` | `--focus` |
| Status (dots, icons) | ok `#3fb68b`, warning `#e5a83b`, error `#f07470`, info `#5aaaf5` | `--ok`, `--warn`, `--err`, `--info` |
| Status text and tints | `#7fdcb8`, `#f2cd8a`, `#ffb4b1` on 8–14 % tints | `--ok-text`, `--warn-text`, `--err-text`, `--ok-bg`, `--warn-bg`, `--warn-bg-strong`, `--warn-border`, `--err-bg`, `--err-border`, `--off-bg` |
| Controls | switch `#1f252e` / knob `#9aa5b4`, disabled send `#2d3440`, stop hover `#fff`, off dot `#5b6472`, chat bullet `#3a4350`, folder icon `#d7b56d`, scrollbar `#2a313c` / `#38414f` | `--switch-bg`, `--switch-knob`, `--send-disabled`, `--stop-hover`, `--dot-off`, `--bullet`, `--tree-folder`, `--scrollbar`, `--scrollbar-hover` |
| Shadows and overlay backdrop | `rgba(0,0,0,.5)`, `rgba(0,0,0,.4)` | `--shadow`, `--backdrop` |
| Brand mark | toes `#fff4d6`, bolt `#ffd60a`, gap = the surface behind it | `--mark-toe`, `--mark-bolt`, `--mark-gap` |
| Terminal | `#0d1014`, text `#d6dde6`, cursor `#a78bfa`, selection `#3a3f5a` | `--term-bg`, `--term-fg`, `--term-cursor`, `--term-selection` |

Three PockPock Dark values changed when themes were added, because the old ones failed WCAG AA: filled buttons used `#8b6cff` with white text (3.69:1, now `--accent-fill` `#6f52f0`, 5.07:1); inputs, the composer and switches used `#2e3744` borders (1.42–1.59:1, now `--control-border`, 3.02:1 or more); and the border of a card waiting for you was a 55 % violet tint (2.35:1, now solid `--accent`). Focus on the composer and search box now uses the shared `--focus` colour. Everything else is unchanged.

Type: Segoe UI Variable (Windows UI font) at 13.5 px body, 26 px welcome heading, 22 px page headings; Cascadia Code for code, paths and the terminal. Radius 8 px for controls and cards, 12 px for the composer, full for chips and the send button.

## Brand mark and app icon

The mark is a chicken foot whose centre toe is a lightning bolt. Files and generation: [`brand/README.md`](brand/README.md).

| Colour | Value | Use |
|---|---|---|
| Volt | `#FFD60A` | The bolt. Accent of the Volt theme, always with ink text on it. Never text on a light surface (1.4:1 on Feather). |
| Ink | `#14111C` | The icon tile, text on volt, surfaces of Volt and Storm, text of Feather |
| Feather | `#FFF4D6` | The toes on dark surfaces, text of Volt |
| Storm | `#5B4BF0` | Accent of Storm and Feather |
| Comb | `#FF4B3E` | Errors and warnings only (the error colour of Volt) |

- **Title bar:** the mark at 20 px (`src/components/Mark.tsx`), no tile behind it, followed by the words "PockPock Agent"; the mark is `aria-hidden`.
- **Theme colours:** toes `--mark-toe`, bolt `--mark-bolt`, and `--mark-gap`, the surface the mark sits on, painted as a 12-unit stroke around the bolt to separate it from the toes (like the ink gap on the app icon). Containers on another surface set `--mark-gap` locally (`.steps` and `.card` use `--bg-panel`). On the light Feather theme the toes are ink and the bolt is storm violet.
- **App icon:** the mark on a rounded ink tile: `public/icon.ico` (Windows), `public/icon.icns` (macOS), `public/icon.png` (Linux and the window icon), `public/favicon.svg`.
- **Working indicator:** the run bar above every task. While a turn works, the mark's bolt pulses next to the status text (opacity 1 → .55 and scale 1 → .86, 1.1 s, ease-in-out) and a 2 px bar sweeps along the bar's bottom edge (`--accent-strong` over `--border`). Waiting for the user: the bolt is still and the 2 px bar is solid `--accent-strong`. Slow (no event for 10 s): the sweep turns `--warn` and a note explains it. Failed: a solid `--err` bar. Under `prefers-reduced-motion` the bolt stays still and the bar is solid; the status text and elapsed time are always shown.

## Layout

- Grid: title bar 38 px and status bar 24 px; columns: icon rail 56 px, task list or Workshop navigation 252 px, the task or page, inspector 320 px. The terminal (260 px high) sits at the bottom of the main column, under the composer.
- Title bar is the window drag area: the mark and "**PockPock** Agent Studio" on the left, the command palette's search box in the middle, and 150 px reserved on the right for the native caption buttons (Windows title-bar overlay).
- A task has a 56 px header (title, engine and folder, the engine switch, **Inspector**), then the run bar, then the thread and composer. The thread and every page use one centred column, `min(820px, 100% - 48px)`.
- Below 1100 px the inspector, and below 860 px the rail with the task list (from the menu button in the title bar), open as overlays with a backdrop; Escape closes them.

## Components

- **Rail:** 40 px icon buttons with a tooltip and an accessible name; the active section is `--bg-active` with an `--accent-strong` icon. A dot on the Tasks icon (`--accent-strong`) means a task needs the user; on Services (`--warn`) that not every installed service runs.
- **Task list:** a filled **New task** button (`--accent-fill`), search, and grouped rows: a status dot (busy, warning, error, done, off; never colour alone, the second line says it in words), the title, and one line of status.
- **Workshop navigation:** groups **Capabilities** (Skills, MCP servers, Connectors, Browser recipes, Research), **Models** (Local models, Cloud models), **Knowledge** (Memory) and **System** (Services, Maintenance, Activity), each row with a count where one exists.
- **Run bar:** numbered phase markers joined by a line (`--ok` once done), the bolt and one line of status, **Signal**, elapsed time with tabular figures, then **Review** and **Stop**; on a narrow bar the time and buttons wrap together to a second line, right-aligned. Notes (slow, failed) sit under it on `--warn-bg` or `--err-bg`.
- **Inspector:** a `role="tablist"` of text tabs with an accent underline (arrow keys move), then sections with an uppercase label and label–value rows; **Context used** is a 6 px `role="meter"` bar.
- **Command palette:** a 620 px dialog near the top with a search box (`role="combobox"`) and grouped results (`role="listbox"`); the active result is `--accent-bg`.
- **Engine switch:** a segmented control (`role="radiogroup"`) in the task header; engines that are not installed are disabled with the reason as a tooltip.
- **Composer:** context chips above it (This PC, open folder, mode with a status dot), then the input, then a bar with + (attach and navigate), mode, permission and model pickers, and the send/stop button.
- **Pickers** open as popovers above their button with a title and one-line explanation per option; the selected option is tinted and checked. Risky choices (Full access) use the warning colour in the picker and on the chip.
- **Cards** in the thread (plan review, approval, skill/MCP install, sources, failed step) share one style: a header with an icon, the title, a secondary line and a status badge on the right (accent "Waiting for you", ok "Approved" or "Allowed for this task"). A card waiting for the user has an accent border and ring; a plan replaced after an answer has a dashed border; a failed step sits on `--err-bg`. Primary action is filled, the others outlined; **Deny** sits at the end of the row.
- **Plan card:** "Plan checked" badges (ok or warning, the detail as a tooltip; warnings also listed in words), label–value rows (Delivers, Workspace, Task folder, Reviewer; paths in the code font), questions on `--warn-bg` with answer buttons and a text box, numbered steps in 22 px circles, success checks with a check mark. Editing turns rows into inputs with move up, move down and remove (32 px icon buttons) and **Add a step** links.
- **Notes** while a run works: dashed rows under the reply with their status (waiting, given to the agent, not sent).
- **Steps** collapse to one summary line ("Worked through 7 steps" or the running step) and expand to the full list with status icons.
- **Tabs** (Connectors): a row of text buttons with a count badge; the active one has an accent underline; they use `role="tablist"`, `role="tab"` and `aria-selected`.
- **Connector cards and rows** (Connectors): a neutral icon tile (a pictogram, never an app's logo), name, one-line description, and a pill action (**Connect**, or the account name when connected). Featured connectors are cards in an auto-fit grid; the rest are rows grouped by a section title.
- **Searchable choice list** (Cloud models): a search field above a bordered, scrolling list of checkbox rows, each with a title and a secondary line; the count and any limit are announced below it.
- **Rows** on Customize pages: icon, title, secondary line, optional description, then a switch and/or a remove button.

## States and accessibility

- Every list and page covers loading (spinner and text), empty (what to do next), error (banner with the reason) and success.
- Status never relies on colour alone: dots are paired with text, steps with icons and words.
- Visible focus ring (2 px `--accent-strong`), keyboard shortcuts for all panels, menus close with Escape, switches use `role="switch"`.
- Controls are at least 32 px high and wide (icon buttons 32 px, rail buttons 40 px, primary actions 32–36 px); the desktop app targets mouse and keyboard.
- `prefers-reduced-motion` turns off animation, including the pulsing bolt and the run bar's sweep, which is shown solid.

## Themes

Five themes, chosen in **Settings → Theme**. The choice is saved in `settings.json` (`theme`) and applied before the first paint. PockPock Dark is the default and keeps the violet accent.

| Theme | id | Surfaces | Text | Accent | Notes |
|---|---|---|---|---|---|
| PockPock Dark | `pockpock-dark` | `#0d1014` → `#232a35` | `#e6ebf1` | violet `#8b6cff` (fills `#6f52f0`, white text) | The default; `:root` |
| Volt | `volt` | ink `#14111c` canvas, `#1b1726` side, `#231d33` raised | feather `#fff4d6`, `#ddd2b8`, `#b3a991` | volt `#ffd60a` with ink text on fills | Warning is orange `#ff9f43` so it is not confused with the accent; error is comb `#ff4b3e` |
| Storm | `storm` | the Volt ink surfaces | `#f4f1ff`, `#cdc6e6`, `#a59dc0` | storm `#5b4bf0` (white text), `#a69dff` as text | |
| Feather | `feather` | warm near-white `#fffaf0`, side `#f7efdf`, raised `#ffffff` | ink `#14111c`, `#433c4f`, `#5f576b` | storm `#5b4bf0` (white text), `#4535d6` as text | Light (`color-scheme: light`). Mark: ink toes, storm bolt. Status colours are darkened for light surfaces |
| System | `system` | Feather or PockPock Dark | | | Follows the operating system's light or dark mode, also while the app runs |

The full per-theme token values are the `:root[data-theme="…"]` blocks at the top of `desktop/src/styles.css`.

**Contrast (WCAG 2.2 AA).** Measured with `npm run check:contrast` (`desktop/scripts/check_contrast.mjs`), which reads the theme blocks, blends translucent tokens over the surface they sit on, and checks 80 pairs per theme (68 before the Agent Studio shell; the run bar, rail, palette and inspector added 12). All four themes pass all 80. Lowest ratio per group:

| Check (minimum) | PockPock Dark | Volt | Storm | Feather |
|---|---|---|---|---|
| Body text `--text` on canvas (4.5) | 15.91 | 17.01 | 16.75 | 17.91 |
| Lowest secondary or tertiary text, any surface (4.5) | 4.59 | 5.75 | 5.23 | 5.18 |
| Text on filled accent controls (4.5) | 5.07 | 13.20 | 5.66 | 5.66 |
| Accent as text, `--accent-strong` (4.5) | 5.35 | 9.76 | 5.86 | 6.66 |
| Selected option or chat on `--accent-bg` (4.5) | 12.15 | 11.62 | 12.44 | 14.21 |
| Code, diffs and logs (4.5) | 12.75 | 13.59 | 12.98 | 12.82 |
| Terminal text and selection (4.5) | 7.53 | 8.68 | 8.84 | 12.94 |
| Status text on tinted backgrounds (4.5) | 9.10 | 8.31 | 8.57 | 6.04 |
| Status bar text (4.5) | 5.86 | 7.52 | 6.84 | 6.00 |
| Focus ring, any surface (3) | 5.31 | 10.29 | 5.68 | 5.81 |
| Input, composer and switch borders (3) | 3.02 | 3.47 | 3.47 | 3.70 |
| Switch knob and track (3) | 3.69 | 6.37 | 3.20 | 4.99 |
| Status dots ok, warn, err, info, off (3) | 3.09 | 3.76 | 3.76 | 3.37 |
| Border of a card waiting for you (3) | 5.16 | 13.20 | 3.29 | 5.44 |

The design canvas named three tokens the app already had under other names: its `--pop` is `--bg-popover`, and `--warn-text`, `--warn-bg` and `--shadow` exist in every theme. The shell added no colour tokens.

The terminal's ANSI colours (`src/lib/theme.ts`) are at least 5.9:1 on the dark terminal backgrounds and 5.5:1 on Feather's; xterm's defaults put red, blue and magenta at 3.6–4.2:1 on dark.

**How the theme is applied.** The main process reads the saved theme when it opens the window, sets the window background and the Windows caption-button colours (`electron/themes.cjs`), and loads the page with `?theme=<id>` ("system" already resolved). `public/theme-boot.js` (a file, because the Content-Security-Policy allows no inline script) sets `data-theme` on `<html>` before the app renders, so there is no flash. Once settings load, `useTheme` (`src/lib/theme.ts`) applies the saved choice, calls `window.pockpock.theme.set(id)` so the main process updates `nativeTheme.themeSource` and the window chrome, and for "system" listens to `prefers-color-scheme`. Code that reads tokens in JavaScript (the terminal) listens for the `pockpock:theme` event.

**Adding a theme.**

1. Add a `:root[data-theme="<id>"] { … }` block to `desktop/src/styles.css` that sets every colour token in `:root` (copy the closest theme) and `color-scheme`.
2. Add the id with its window `bg` (= `--bg`) and caption `symbol` (= `--text-2`) to `THEMES` in `desktop/electron/themes.cjs`, and to the allowed list in `desktop/public/theme-boot.js`.
3. Add a picker entry with four preview swatches (canvas, panel, accent, text) to `THEMES` in `desktop/src/lib/theme.ts`; if it is light, give it the light ANSI palette there.
4. Run `npm run check:contrast` and adjust until every pair passes; add a pair to `check_contrast.mjs` if the theme combines tokens in a new way.
5. Check it in the running app at 1440×900 and 820 px (chat, cards, Customize pages, Settings, terminal) and add its column to the contrast table above.
