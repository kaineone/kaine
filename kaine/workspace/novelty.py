# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
from collections import Counter, deque

from kaine.bus.schema import Event


def fingerprint(event: Event) -> str:
    body = json.dumps(
        {"source": event.source, "type": event.type, "payload": event.payload},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.blake2b(body.encode("utf-8"), digest_size=8).hexdigest()


class NoveltyTracker:
    """Short-window in-memory novelty for the salience product-form.

    A fingerprint never seen in the window scores 1.0; novelty decreases
    as the same fingerprint recurs within the window.
    """

    def __init__(self, window: int = 32) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        self._window = window
        self._fps: deque[str] = deque(maxlen=window)
        self._counts: Counter[str] = Counter()

    @property
    def window(self) -> int:
        return self._window

    def observe(self, event: Event) -> float:
        fp = fingerprint(event)
        # O(1) lookup of how many times this fingerprint already appears in the
        # window. The counter is kept in sync with the deque as items age out.
        prior_count = self._counts.get(fp, 0)
        if len(self._fps) == self._window:
            evicted = self._fps.popleft()
            self._counts[evicted] -= 1
            if self._counts[evicted] == 0:
                del self._counts[evicted]
        self._fps.append(fp)
        self._counts[fp] += 1
        novelty = max(0.0, 1.0 - prior_count / self._window)
        return novelty

    def reset(self) -> None:
        self._fps.clear()
        self._counts.clear()
