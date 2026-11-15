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

## Still to apply (hand-off)

Done in this change: app icon files, favicon, brand assets, design-system section.

Not done, for a follow-up change:

1. **Title-bar mark.** `desktop/src/components/Shell.tsx` still renders a `P` in `.brand__mark`
   (styles in `desktop/src/styles.css`, line ~65). Replace it with the inline `mark.svg` paths at 20 px,
   drop the violet gradient background, and keep the `PockPock Agent` text.
2. **macOS icon.** `desktop/package.json` `build.mac.icon` points at `public/icon.png`; `public/icon.icns` now exists
   and can be used instead.
3. **Working indicator.** The mark's bolt can pulse while the agent is thinking, planning or running a tool
   (opacity 1 → .55 and scale 1 → .86 over about 1.1 s, off under `prefers-reduced-motion`).
4. Follow `AGENTS.md`: `npm run typecheck`, `npm run build`, and a Playwright Electron check at 1440×900
   and 820 px for the UI changes.
