# PockPock AI frontend

This directory contains the React, TypeScript, and Vite application. Product setup, API operation, permissions, and the user-facing agent workflow are documented in the [repository README](../README.md). Module ownership and the growth plan are in [Architecture](../docs/ARCHITECTURE.md).

## Development

From this directory:

```powershell
npm install
npm run dev
```

The Vite development server runs at `http://127.0.0.1:5173` and proxies `/api` requests to the local FastAPI service at port `8766`. Start that API with `../../backend/scripts/start_frog_ai.ps1` or use the combined launcher described in the repository README.

## Verification

```powershell
npm run build
npm run lint
```

Build output is generated in `dist/`. The production API can serve this directory after a build; it is not source code and should not be edited by hand.

## Documentation rule

Before changing frontend behavior, read the relevant feature page and follow the repository [AI contribution rules](../AGENTS.md). Document user-visible behavior, API calls, persistence, permissions, and verification steps in the same change. The frontend implementation is currently composed in `src/App.tsx`; split new or substantially changed areas by feature rather than growing that composition file further.

## Animated background

`src/blackhole/` renders a real-time, ray-traced black hole (raw WebGL, no extra dependencies) behind the whole app via `<BlackHoleBackground palette="blue" />` in `App.tsx` (the `blue` palette matches the app's blue theme; the marketing site uses the default `cosmic` palette). Light rays are bent by Schwarzschild gravity, so lensing, the photon ring, and Doppler beaming of the accretion disk are computed, not painted. It adapts render resolution to hold frame rate, pauses when the tab is hidden, renders a single still frame under `prefers-reduced-motion`, and falls back to `public/images/black-hole-reference.jpg` when WebGL is unavailable. The marketing site (`site/lib/blackhole/`) uses a copy of the same renderer; keep the two in sync.
