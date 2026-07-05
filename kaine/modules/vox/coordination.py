# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""In-process coordination between vox and audition.

When the entity speaks aloud through the speakers, an open microphone can
capture that playback and transcribe it back as if a user had spoken —
a self-hearing feedback loop. `SpeakingGate` is a tiny shared timestamp:
vox marks a "speaking" window while a clip plays (when self-hearing
suppression is enabled), and audition drops any utterance that begins
inside that window.

The gate carries NO sensory content — only a monotonic deadline. A single
instance is created in `build_registry` and injected into both modules, so
this is plain dependency injection, not a process global.

Suppression is needed only when the mic can acoustically hear the speakers.
With an isolated input (e.g. a headset mic) vox simply never marks the
gate (`suppress_self_hearing = false`), leaving the entity full-duplex.
"""
from __future__ import annotations

import time
from typing import Callable


class SpeakingGate:
    """Shared "the entity is speaking aloud" window.

    `mark_speaking(duration_s)` opens (or extends) the window to
    `now + duration_s`. `is_speaking()` reports whether the window is open.
    `clock` is injectable for deterministic tests; it defaults to a
    monotonic clock so wall-clock changes never reopen a closed window.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._open_until: float = 0.0

    def mark_speaking(self, duration_s: float) -> None:
        if duration_s <= 0.0:
            return
        deadline = self._clock() + float(duration_s)
        if deadline > self._open_until:
            self._open_until = deadline

    def is_speaking(self) -> bool:
        return self._clock() < self._open_until
