# SPDX-FileCopyrightText: 2024 KAINE developers
# SPDX-License-Identifier: MIT

"""Social‑cognition sub‑package.

Exports the public primitives for cross‑modal identity handling.
"""

from .identity import Identity, bind_identities

__all__: list[str] = ["Identity", "bind_identities"]