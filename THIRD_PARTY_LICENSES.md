# Third-Party Licenses

The KAINE project itself is licensed under the **Cognitive Architecture License
(CAL) v0.5** (SPDX `LicenseRef-CAL-0.5`); see [`LICENSE.md`](LICENSE.md) and
[`NOTICE`](NOTICE).

The components listed below are **bundled (vendored) third-party assets**. They
are NOT covered by CAL — each is distributed under its own license, and its
original copyright and license headers are preserved in the vendored file. This
manifest tracks every vendored front-end asset, its license, and its origin.

The backend third-party components (DreamerV3 RSSM, OpenNARS-for-Applications)
are tracked separately in the "THIRD-PARTY COMPONENTS" section of [`NOTICE`](NOTICE).

## Maternal-voice audio (developmental stimulus)

The takes in `kaine/modules/audition/maternal_voice_data/*.flac` were rendered by KAINE with Chatterbox TTS 0.1.6 (Resemble AI, MIT licence, https://github.com/resemble-ai/chatterbox), which embeds its Perth watermark in every output. The texts are original to KAINE. The voice is conditioned on utterances of the CMU ARCTIC speaker `slt` (Kominek and Black 2003, http://www.festvox.org/cmu_arctic/); no CMU ARCTIC audio ships with KAINE, and its notice is kept here as its licence asks:

```
This voice is free for use for any purpose (commercial or otherwise)
subject to the pretty light restrictions detailed below.

############################################################################
###                                                                       ##
###                     Carnegie Mellon University                        ##
###                         Copyright (c) 2003                            ##
###                        All Rights Reserved.                           ##
###                                                                       ##
###  Permission to use, copy, modify,  and licence this software and its  ##
###  documentation for any purpose, is hereby granted without fee,        ##
###  subject to the following conditions:                                 ##
###   1. The code must retain the above copyright notice, this list of    ##
###      conditions and the following disclaimer.                         ##
###   2. Any modifications must be clearly marked as such.                ##
###   3. Original authors' names are not deleted.                         ##
###                                                                       ##
###  THE AUTHORS OF THIS WORK DISCLAIM ALL WARRANTIES WITH REGARD TO      ##
###  THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY   ##
###  AND FITNESS, IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY         ##
###  SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES            ##
###  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN   ##
###  AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,          ##
###  ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF       ##
###  THIS SOFTWARE.                                                       ##
###                                                                       ##
############################################################################
###                                                                       ##
###  See http://www.festvox.org/cmu_arctic/ for more details              ##
###                                                                       ##
############################################################################
```

## Front-end / Nexus console assets

| Component | Files | License (SPDX) | License text | Origin |
|---|---|---|---|---|
| **Three.js** | `kaine/dashboard/static/vendor/vendor/three.module.js` | MIT | https://github.com/mrdoob/three.js/blob/r160/LICENSE | three.js r160, https://github.com/mrdoob/three.js (fetched from https://unpkg.com/three@0.160.0/) |
| **MarchingCubes** (three.js examples) | `kaine/dashboard/static/vendor/vendor/MarchingCubes.js` | MIT | https://github.com/mrdoob/three.js/blob/r160/LICENSE | three.js r160 `examples/jsm/objects/MarchingCubes.js`, https://github.com/mrdoob/three.js — single `from 'three'` import rewritten to `./three.module.js` upstream; otherwise unmodified |
| **viz.js / `LevelMeter`** (ferrofluid speech/affect visualizer) | `kaine/dashboard/static/vendor/viz.js` | GPL-3.0-or-later | https://www.gnu.org/licenses/gpl-3.0.html | Fieldtrip companion app — vendored verbatim with its SPDX header intact |
| **uPlot** (charting) | `kaine/dashboard/static/vendor/uPlot.iife.min.js`, `kaine/dashboard/static/vendor/uPlot.min.css` | MIT | https://github.com/leeoniya/uPlot/blob/master/LICENSE | uPlot 1.6.31, https://github.com/leeoniya/uPlot |
| **Inter** 4.001 (UI and body font) | `kaine/dashboard/static/fonts/inter-latin-{400,500,600}-normal.woff2` | SIL OFL 1.1 | `kaine/dashboard/static/fonts/OFL-Inter.txt` ("Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter)") | https://github.com/rsms/inter (licence file `LICENSE.txt` at tag v4.1); latin subset from Fontsource, a Modified Version under the OFL; no Reserved Font Name |
| **JetBrains Mono** 2.211 (metadata and data font) | `kaine/dashboard/static/fonts/jetbrains-mono-latin-{400,500}-normal.woff2` | SIL OFL 1.1 | `kaine/dashboard/static/fonts/OFL-JetBrainsMono.txt` ("Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)") | https://github.com/JetBrains/JetBrainsMono (licence file `OFL.txt` at tag v2.210); latin subset from Fontsource, a Modified Version under the OFL; no Reserved Font Name |
| **Zen Dots** 1.000 (display font) | `kaine/dashboard/static/fonts/zen-dots-latin-400-normal.woff2` | SIL OFL 1.1 | `kaine/dashboard/static/fonts/OFL-ZenDots.txt` ("Copyright 2021 The Dots Project Authors (https://github.com/googlefonts/zen-dots)") | https://github.com/googlefonts/zen-dots (licence file `OFL.txt`), designed by Yoshimichi Ohira; latin subset made locally, a Modified Version under the OFL; no Reserved Font Name |

### Notes

- **Font licences ship with the fonts.** Each font family's licence file in
  `kaine/dashboard/static/fonts/` is a byte copy of that family's upstream
  licence file: its copyright notice followed by the full SIL Open Font License
  1.1 text, as OFL condition 2 requires for every redistributed copy.
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
