# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The language organ's server, as the runtime drives it.

``served`` names the published organ and checks what a running server serves;
``lifecycle`` launches, supervises and stops the model server; ``device_map``
places the organ and the cycle on the host's accelerators. Install-time
download and the setup wizard live in ``kaine.setup``, which imports these.
"""
