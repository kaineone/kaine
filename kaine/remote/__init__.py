# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Remote operation over the operator's tailnet — entity-side seam.

The cycle-layer remote perception bridge lives here. Client apps (the PWA,
the playlist feeder) live in the operator's private companion repo and speak
to this bridge over WebSocket.
"""

from kaine.remote.bridge import RemoteBridge, RemoteBridgeConfig

__all__ = ["RemoteBridge", "RemoteBridgeConfig"]
