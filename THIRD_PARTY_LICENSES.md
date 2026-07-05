# Third-Party Licenses

The KAINE project itself is licensed under the **Cognitive Architecture License
(CAL) v0.2** (SPDX `LicenseRef-CAL-0.2`); see [`LICENSE.md`](LICENSE.md) and
[`NOTICE`](NOTICE).

The components listed below are **bundled (vendored) third-party assets**. They
are NOT covered by CAL — each is distributed under its own license, and its
original copyright and license headers are preserved in the vendored file. This
manifest tracks every vendored front-end asset, its license, and its origin.

The backend third-party components (DreamerV3 RSSM, OpenNARS-for-Applications)
are tracked separately in the "THIRD-PARTY COMPONENTS" section of [`NOTICE`](NOTICE).

## Front-end / Nexus console assets

| Component | Files | License (SPDX) | License text | Origin |
|---|---|---|---|---|
| **Three.js** | `kaine/nexus/static/vendor/vendor/three.module.js` | MIT | https://github.com/mrdoob/three.js/blob/r160/LICENSE | three.js r160, https://github.com/mrdoob/three.js (fetched from https://unpkg.com/three@0.160.0/) |
| **MarchingCubes** (three.js examples) | `kaine/nexus/static/vendor/vendor/MarchingCubes.js` | MIT | https://github.com/mrdoob/three.js/blob/r160/LICENSE | three.js r160 `examples/jsm/objects/MarchingCubes.js`, https://github.com/mrdoob/three.js — single `from 'three'` import rewritten to `./three.module.js` upstream; otherwise unmodified |
| **viz.js / `LevelMeter`** (ferrofluid speech/affect visualizer) | `kaine/nexus/static/vendor/viz.js` | GPL-3.0-or-later | https://www.gnu.org/licenses/gpl-3.0.html | KAINE remote-companion app (`kaine-remote`) — vendored verbatim with its SPDX header intact |
| **uPlot** (charting) | `kaine/nexus/static/vendor/uPlot.iife.min.js`, `kaine/nexus/static/vendor/uPlot.min.css` | MIT | https://github.com/leeoniya/uPlot/blob/master/LICENSE | uPlot 1.6.31, https://github.com/leeoniya/uPlot |
| **Chakra Petch** (UI font) | `kaine/nexus/static/fonts/chakra-petch-latin-{400,500,700}-normal.woff2` | SIL OFL 1.1 | https://openfontlicense.org/open-font-license-official-text/ | Google Fonts / Fontsource, latin subset |
| **Orbitron** (display font) | `kaine/nexus/static/fonts/orbitron-latin-{600,700,800}-normal.woff2` | SIL OFL 1.1 | https://openfontlicense.org/open-font-license-official-text/ | Google Fonts / Fontsource, latin subset |

### Notes

- **Vendored, not networked.** All of the above are committed to the repo and
  served from `/static/…`. KAINE is all-local at runtime — there is no CDN or
  runtime network fetch for any of these assets.
- **`viz.js` is GPL-3.0-or-later.** It is loaded as a separate ES module from
  `/static/vendor/viz.js`; its license header is preserved unchanged. The
  KAINE-authored Nexus code that instantiates it does not incorporate the
  GPL source — it imports the module at runtime in the browser.
- **Three.js import layout.** `viz.js` imports Three.js via relative paths
  (`./vendor/three.module.js`, `./vendor/MarchingCubes.js`). The
  `static/vendor/vendor/` nesting mirrors that import structure so the module
  resolves locally with no edits to the vendored source.
