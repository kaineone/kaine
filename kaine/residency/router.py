# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Residency router: bridges component load/unload to the ledger and event log."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaine.residency.ledger import Ledger

log = logging.getLogger(__name__)


class ResidencyRouter:

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger
        self._load_starts: dict[str, float] = {}

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    def register(self, name: str, footprint_bytes: int = 0, ttl_seconds: int = 120) -> None:
        self._ledger.register(name, footprint_bytes, ttl_seconds)

    async def before_load(self, name: str, footprint_bytes: int = 0) -> bool:
        from kaine.residency.events import record_load_start
        from kaine.residency.ledger import Priority

        admitted = await self._ledger.try_admit(name, footprint_bytes, Priority.INTERACTIVE)
        if admitted:
            self._load_starts[name] = time.monotonic()
            record_load_start(name)
        return admitted

    def after_load(self, name: str) -> None:
        from kaine.residency.events import record_load_end

        start = self._load_starts.pop(name, None)
        duration = time.monotonic() - start if start is not None else 0.0
        self._ledger.mark_resident(name)
        record_load_end(name, duration)

    def before_unload(self, name: str) -> None:
        from kaine.residency.events import record_unload

        self._ledger.mark_unloading(name)
        record_unload(name, reason="explicit")

    def after_unload(self, name: str) -> None:
        self._ledger.mark_cold(name)

    def record_use(self, name: str) -> None:
        self._ledger.record_use(name)
