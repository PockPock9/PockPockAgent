# YourBrand visual system

This applied design system follows the supplied product brief. The UI UX Pro Max operations pattern is a structural reference; the brief's palette and typography take precedence over generated recommendations.

## Foundation

- Canvas: `#030916`, with a local photographic black-hole and accretion-disk image, subtle blue atmospheric glow, and sparse drifting stars.
- Text: `#f2f8ff`; secondary text: `#a4bad3`.
- Accent: `#2476ff`; glow: `#76c5ff`; highlight: `#4aa3ff`; success: `#3fb68b`.
- Surfaces: translucent navy (`rgba(9,24,46,.34)`) with backdrop blur so the cosmic animation remains visible; default border `rgba(95,174,255,.2)`, interactive border `rgba(112,190,255,.48)`.
- Corners: 12px cards and 999px pills. Content width: 1200px.
- Headings: Space Grotesk, light to regular weight, tight tracking. Body: Inter. Labels and figures: JetBrains Mono.

The CSS variables live in `web/site/app/globals.css`; matching Tailwind color, font, radius, and shadow tokens live in `web/site/tailwind.config.ts`.

## Composition

Use a full-screen, fixed cosmic layer behind both routes. A realistic black-hole image provides the main visual; animate it with a very slow camera drift and restrained corona light variation instead of rotating the image or drawing synthetic rings. Stars drift slowly and the nebula shifts gently. Keep motion subdued behind content; glass navigation, cards, and the dashboard sidebar use translucent navy rather than opaque fills. Preserve readable text and blue focus rings. The signature workflow panel pairs compact input and output nodes with a luminous central hub. The dashboard keeps its compact metrics, activity chart, workflow table, and timeline.

## Interaction

Use 150–200ms transform, opacity, border, and shadow transitions. Reveal sections gently on scroll. Respect reduced motion, keep focus rings visible in bright blue, label icon-only controls, and ensure keyboard access to menus, controls, and dialogs. At narrow widths, collapse navigation and stack the workflow diagram and dashboard columns.

## Product content

The `/` and `/app` routes are illustrative product demonstrations. Metrics, customer names, testimonials, case studies, and workflow history are mock content and must be replaced with verified company material before publication.
