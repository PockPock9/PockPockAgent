# Agent Studio design (redesign of the desktop app)

**Status:** design proposal, not implemented. Created 2026-11-22.
**Canvas (private to the author, share from claude.ai if others need it):** https://claude.ai/artifact/ERsUX2uGAskAGXhojCmv9E
**Source files:** `design/agent-studio/v1/boards/` (21 `.dc.html` boards plus `canvas.json`); see `v1/VERSION.md`.

## Direction
Evolve the current dark violet look and the claw-and-bolt mark. Chat-first layout stays; Customize becomes a Workshop with one sub-nav. The app must never look hung: a run bar with phases, elapsed time, heartbeat and Stop sits above every conversation.

## Layout
56 px icon rail (Tasks, Workshop, Activity; Services and Settings at the bottom), 252 px task panel, centre conversation, optional 320 px inspector (Context, Files, Terminal). Below 1100 px the inspector is an overlay; below 860 px the rail and task panel collapse behind a menu.

## Boards
| Group | Boards |
|---|---|
| Core | Studio agent run, Workshop skills, Narrow 820 px, Working states |
| Thread, overlays, panels | Plan review, Thread cards, Pickers and menus, Files and terminal, Dialogs and toasts, First-run setup |
| Workshop pages | Local models, Cloud models, Connectors, MCP servers, Browser recipes, Research, Memory, Activity (live), Services, Maintenance, Settings |

## Working states
Starting, Planning, Running a tool, Slow (no output for 10 s), Waiting for you, Failed. Waiting and failing look different from working on purpose.

## Not verified / sample content
- Nothing here has been built or tested in the Electron app.
- All numbers, task titles, model sizes, connector names and report text are invented.
- Volt and Feather token values are guesses beside the swatches in `src/lib/theme.ts`; use the real tokens.
- Elements with no known data source (heartbeat "Signal 1 s ago", "Plan checked" chips) need existing run events or should be dropped.

## Implementation
Use the Claude Code prompt from the pull request that added this folder. Suggested split: (1) tokens, shell, run bar; (2) plan card, thread cards, pickers; (3) Workshop pages; (4) Settings, Setup, dialogs, themes.
