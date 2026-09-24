# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""kaine_cl1: an optional KAINE plugin that runs selected modules' forward models
on Cortical Labs CL1 biological neural compute, currently through Cortical Labs'
simulator (`cl-sdk`, installed separately by the operator).

Core KAINE never imports this package. KAINE loads it through the `cl1` entry
point in the `kaine.plugins` group, and only when `[plugins].enabled` names it.
Each converted module keeps its `name`, bus subscriptions and published event
shapes; only the object behind a declared seam (`chronos.network`,
`soma.forward_model`) changes. See `plugins/kaine-cl1/README.md` and
`docs/cl1.md`.
"""

__version__ = "0.0.1"

__all__ = [
    "__version__",
]
