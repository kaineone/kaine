# Vendored front-end assets

These files are committed to the repo and served from `/static/vendor/`. KAINE
is **all-local at runtime** — no CDN, no runtime network fetch. Any front-end
library the dashboard uses is vendored here and pinned to an exact version.

## uPlot

- **What:** small, fast canvas time-series charting library used by the Nexus
  diagnostics dashboard for live cycle-rate, affect (VAD), salience, and
  attribution graphs.
- **Version:** `1.6.31`
- **License:** MIT (https://github.com/leeoniya/uPlot/blob/master/LICENSE)
- **Upstream:** https://github.com/leeoniya/uPlot
- **Fetched from:** `https://cdn.jsdelivr.net/npm/uplot@1.6.31/dist/`
  (download is a one-time vendoring step, not a runtime dependency)
- **Files:**
  - `uPlot.iife.min.js` — IIFE build, exposes the global `uPlot`
  - `uPlot.min.css`

### SHA-256

```
2d27e8ad3d228164525ce213f9dc716f39b4e3aee0cc773fb3491c96cf4921a2  uPlot.iife.min.js
df630c6a8d6f8eeaff264b50f73ce5b114f646ffd9a0bb74f049b0a00135fa04  uPlot.min.css
```

### Updating

1. Download the new version's `uPlot.iife.min.js` and `uPlot.min.css` from the
   pinned jsDelivr URL above (or the GitHub release).
2. Recompute the SHA-256 sums and update them here.
3. Verify the dashboard graphs still render with no console errors.

## Ferrofluid "Presence" visualizer — `viz.js` + `vendor/`

- **What:** the Three.js ferrofluid speech/affect visualizer used by the Nexus
  **Presence** board. `viz.js` exports `class LevelMeter`; it reacts to the
  entity's affect via `setMood(valence, arousal)` and (optionally) to speech via
  an audio level.
- **License:** `viz.js` is **GPL-3.0-or-later** (its SPDX header is preserved);
  the Three.js files are **MIT**. See the repo-root `THIRD_PARTY_LICENSES.md`.
- **Files:**
  - `viz.js` — ES module, exports `LevelMeter`. Vendored verbatim from the
    `kaine-remote` companion app.
  - `vendor/three.module.js` — three.js r160 (MIT).
  - `vendor/MarchingCubes.js` — three.js r160 `examples/jsm/objects/MarchingCubes.js` (MIT).
- **Layout:** `viz.js` imports `./vendor/three.module.js` and
  `./vendor/MarchingCubes.js`, so the three.js files live in the nested
  `vendor/vendor/` directory. This mirrors `kaine-remote`'s layout exactly so the
  vendored source needs **no edits** to resolve its imports locally.

### Updating the viz

1. Re-copy `viz.js` from `kaine-remote/webapp/viz.js` and the two three.js files
   from `kaine-remote/webapp/vendor/`.
2. Preserve each file's existing license/SPDX header byte-for-byte.
3. Verify the Presence board renders with no console errors.
