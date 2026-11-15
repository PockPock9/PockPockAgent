# PockPock brand assets

The mark is a chicken foot whose centre toe is a lightning bolt. Palette and rules are in
[`../pockpock-desktop.md`](../pockpock-desktop.md#brand-mark-and-app-icon).

| File | Use |
|---|---|
| `app-icon.svg` | Mark on the rounded ink tile. Same file as `desktop/public/favicon.svg`. |
| `mark.svg` | Full-colour mark, transparent background. Works on dark and mid backgrounds. |
| `mark-ink.svg` | One-colour ink mark for light backgrounds. |
| `mark-feather.svg` | One-colour cream mark for dark backgrounds. |
| `png/pockpock-icon-{16…1024}.png` | App icon rasters. |
| `tokens.css` | Brand colour variables. |

The raster icons and `desktop/public/icon.{png,ico,icns}` are generated: edit the geometry in
`desktop/scripts/make_icon.py` (and the SVGs to match), then run `python scripts/make_icon.py` from `desktop/`.
Needs only Pillow.

## Applied in the app

- [x] App icon files, favicon, brand assets and the design-system section.
- [x] **Title-bar mark.** `desktop/src/components/Mark.tsx` renders the `mark.svg` paths at 20 px in the title bar
  (no tile behind it, next to the "PockPock Agent" text). Its colours are theme tokens: `--mark-toe`, `--mark-bolt`
  and `--mark-gap`, so the mark works on every theme (ink toes and a storm bolt on the light Feather theme).
- [x] **macOS icon.** `desktop/package.json` `build.mac.icon` is `public/icon.icns`; Windows keeps `public/icon.ico`.
- [x] **Working indicator.** The bolt pulses while the agent is thinking, planning or running a tool (opacity 1 → .55
  and scale 1 → .86, 1.1 s, ease-in-out), with a sweeping bar in the composer; both stop under `prefers-reduced-motion`.
- [x] Checked with `npm run typecheck`, `npm run build`, `npm run check:contrast` and Playwright at 1440×900 and 820 px
  in every theme. See [themes](../../docs/features/themes.md).
