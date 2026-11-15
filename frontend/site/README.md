# YourBrand marketing site and workspace demo

This is a standalone Next.js App Router project alongside the existing Vite local-router interface. The landing page is at `/`; the interactive sample workspace is at `/app`. It is a visual product demo with in-memory state and mock analytics, not a connection to PockPock AI or a production automation API.

## Run locally

Requirements: Node.js 20.9 or newer and npm.

```powershell
cd .\frontend\site
npm install
npm run dev
```

Open `http://localhost:3000`. To check a production build, run `npm run typecheck`, `npm run build`, then `npm start`.

## Project map

- `app/page.tsx` and `app/app/page.tsx` define the landing page and workspace demo routes.
- `components/` contains the navigation, hero, workflow diagram, ROI calculator, pricing, marketing sections, and dashboard.
- `data/mock-data.ts` supplies dashboard chart, workflow, and activity examples.
- `app/globals.css` contains responsive presentation and CSS design tokens. `tailwind.config.ts` exposes matching colors, fonts, radii, and shadow tokens.

The ROI calculator responds to its range inputs. The pricing period switch changes displayed prices, workflow nodes highlight related paths, dashboard search filters workflows, switches pause or resume sample rows, the activity timeline expands, and the New workflow form adds a local sample row. Refreshing resets these sample interactions. Metrics, outcomes, brands, and testimonials on the marketing page are illustrative content and should be replaced with verified company material before publication.

Motion uses Framer Motion and CSS transitions, and respects `prefers-reduced-motion`. Icons come from Lucide. The black-hole background plate is a local image at `public/images/black-hole-reference.jpg`; its camera drift and atmospheric glow are animated with CSS. Google Fonts load through Next.js font optimization at build time.

## Commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the local development server |
| `npm run typecheck` | Run TypeScript checks |
| `npm run build` | Create the production build |
| `npm start` | Serve the production build |
