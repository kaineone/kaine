# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""The shared wetware substrate layer.

A CL1 system (and the free simulator) exposes **one** culture on a **64-channel**
multi-electrode array. Every converted KAINE module that wants biological compute
must share that single array. This package owns that sharing:

- `session`: open/own the `cl.Neurons` connection and the simulator config.
- `broker`: allocate disjoint channel blocks to modules; run the one closed
               loop; fan stim requests in and spike observations out.
- `codec`: encode module inputs → `StimDesign`/`ChannelSet` patterns and
               decode recorded spikes → scalar/vector signals.

See `openspec/changes/wetware-substrate-foundation/`.
"""
