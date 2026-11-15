# PockPock Agent (desktop)

Electron desktop app for PockPock: chats, the four response modes (Chat, PockPock Agent, OpenClaw, NemoClaw), plan review and approvals, skills and MCP servers, a file explorer and a terminal. It uses the local PockPock backend and starts it if needed.

```powershell
npm install
npm run build
npm run app                     # start the app
npm run dev                     # Vite with hot reload + Electron
npm run typecheck
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1   # Desktop and Start-menu shortcuts
```

Full documentation: [docs/features/desktop-app.md](../docs/features/desktop-app.md). Design tokens: [design-system/pockpock-desktop.md](../design-system/pockpock-desktop.md).
