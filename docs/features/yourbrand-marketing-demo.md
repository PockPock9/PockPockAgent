# YourBrand marketing site and workspace demo

## Purpose and routes

`frontend/site/` is a standalone Next.js App Router project that provides a polished marketing-page concept and a small interactive workspace demo. It is intentionally separate from the existing Vite and FastAPI product so it does not change local inference, agent execution, persisted data, API routes, or the existing desktop startup flow.

- `/` presents the responsive YourBrand marketing concept, including hero, workflow visualization, ROI estimate, services, illustrative work, pricing, testimonials, articles, contact CTA, and footer.
- `/app` presents a sample automation dashboard with overview KPIs, charts, searchable and filterable workflows, local pause/resume switches, an accessible create-workflow dialog, and expandable activity details.

The dashboard and marketing metrics are mock data. UI interactions live in React state and reset on refresh. The site makes no automation API requests and persists no user or workflow information. Replace sample metrics, testimonials, case studies, pricing, and workspace values with reviewed company data before publication.

## Modules and flow

- `app/layout.tsx` configures shared fonts, metadata, and global CSS.
- `components/MarketingSite.tsx` composes the landing page from `Nav`, `Hero`, `WorkflowDiagram`, `RoiCalculator`, `Pricing`, and `MarketingSections` modules.
- `components/CosmicBackground.tsx` layers a realistic black-hole image plate with a slowly drifting camera, subtle blue corona, nebula, and sparse starfield behind both routes; `components/CosmicMotionToggle.tsx` exposes pause/resume controls in the marketing navigation and dashboard top bar.
- `components/Dashboard.tsx` owns dashboard controls and composes mock workflow, timeline, and Recharts views using `data/mock-data.ts`.
- `app/globals.css` defines the blue tokens, translucent glass panels, responsive breakpoints, dashboard components, focus styles, and reduced-motion behavior. `tailwind.config.ts` maps the CSS token values for Tailwind utilities.

The ROI amount is an illustrative estimate derived from team size, time saved, hourly cost, 52 weeks, and a 75% realization factor. Pricing buttons switch between the supplied monthly and annual sample values. Dashboard workflow toggles, search, active-only filtering, expandable activity, and creation act on local component state only. The create dialog supports Escape and focus trapping, adds a paused sample workflow row, and does not invoke a backend.

## Security, privacy, and failure states

The demo has no authentication, backend, telemetry, external action execution, or persistence. Data shown is bundled sample data. Next serves both routes; UI states are local. A dashboard search with no matches shows an empty table message. The create form requires a non-empty name and limits its length. Users can dismiss the modal or mobile sidebar, pause or resume the decorative background, and keyboard focus uses visible blue outlines. The background combines a local photographic image with CSS motion, stops under `prefers-reduced-motion`, and has an explicit pause control.

The local dev server requires Node.js 20.9+ and npm. Run `npm run typecheck` and `npm run build` from `frontend/site/` to validate the project. See its [README](../../frontend/site/README.md) for developer commands and module map.
