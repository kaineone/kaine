# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The per-boot stimulus-control object.

Built by the cycle's composition root only when ``[stimulus_control].enabled``
is true; with it off nothing here is constructed. It owns the welfare tally
from the start of the boot, builds the programme clock and the controller when
boot builds a playlist feed, and hands the stimulus effector, the stage-M act
source's inputs and the affect credit observer to the wiring.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from kaine.modules.effectors.stimulus.config import (
    StimulusControlConfig,
    StimulusControlError,
)
from kaine.modules.effectors.stimulus.controller import StimulusController
from kaine.modules.effectors.stimulus.programme import (
    Programme,
    ProgrammeClock,
    load_programme,
    probe_durations,
)
from kaine.modules.effectors.stimulus.records import StimulusTally

log = logging.getLogger(__name__)


class StimulusControlRuntime:
    def __init__(
        self,
        config: StimulusControlConfig,
        *,
        now: Callable[[], float],
        seed: int = 0,
    ) -> None:
        self.config = config
        self.seed = int(seed)
        self.tally = StimulusTally(config)
        self._now = now
        self.controller: StimulusController | None = None
        self.programme: Programme | None = None
        self._effector: Any = None

    @classmethod
    def from_config(
        cls, kaine_config: Mapping[str, Any], *, now: Callable[[], float], seed: int = 0
    ) -> "StimulusControlRuntime | None":
        """The runtime when stimulus control is enabled, else None (nothing built)."""
        config = StimulusControlConfig.from_section(kaine_config.get("stimulus_control"))
        if not config.enabled:
            return None
        return cls(config, now=now, seed=seed)

    def set_clock(self, now: Callable[[], float]) -> None:
        """Use the boot's entity clock once it exists (before any controller is built)."""
        if self.controller is not None:
            raise RuntimeError("the controller already reads a clock")
        self._now = now

    def now(self) -> float:
        return self._now()

    def install_programme(
        self,
        manifest_path: str,
        *,
        probe: Callable[[Any], float | None] | None = None,
        start: bool = True,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> ProgrammeClock:
        """Build the programme, its clock and the controller; return the shared clock.

        ``monotonic`` is the playlist clock's real-time source (injectable for
        tests); the controller's own timing reads the entity clock.
        """
        try:
            programme = load_programme(manifest_path, self.config.channels)
        except Exception as exc:
            # The exception type only: its text can carry a path, so a title.
            raise StimulusControlError(
                f"stimulus control cannot load the programme channels ({type(exc).__name__})"
            ) from None  # the cause's text can carry a path
        # Verify every item, every channel's, BEFORE the probe opens any media:
        # a changed file must stop the boot before a demuxer parses it.
        try:
            programme.manifest.verify_against(Path(programme.manifest.manifest_path).parent)
        except Exception as exc:
            raise StimulusControlError(
                f"stimulus control: a programme item failed verification ({type(exc).__name__})"
            ) from None  # the cause's text carries the path
        clock = ProgrammeClock(
            len(programme.manifest.items), segments=programme.segments, clock=monotonic
        )
        probe_durations(programme.manifest, clock, probe=probe)
        self.programme = programme
        self.controller = StimulusController(
            clock, programme, self.config, now=self._now, tally=self.tally
        )
        if start:
            self.controller.start()
        log.warning(
            "stimulus control enabled at stage %s: %d programme channel(s), actions %s",
            self.config.stage,
            programme.channel_count,
            ", ".join(self.config.declared_actions()),
        )
        return clock

    def effector(self) -> Any:
        """The stimulus effector, built once; None without a programme."""
        if self.controller is None:
            return None
        if self._effector is None:
            from kaine.modules.effectors.stimulus.effector import StimulusEffector

            self._effector = StimulusEffector(
                self.controller, self.config, clock=self._now, tally=self.tally
            )
        return self._effector

    def allowed_actions(self) -> list[str]:
        effector = self.effector()
        return [] if effector is None else effector.allowed_actions()

    def observe_affect(self, dt: float, **values: Any) -> None:
        """The affect module's credit-window sample, with the awake flag added."""
        awake = self.controller.is_awake() if self.controller is not None else True
        self.tally.observe_affect(dt, awake=awake, **values)

    def descriptor(self) -> dict[str, Any]:
        """The run-manifest record (only written when stimulus control is on)."""
        return self.config.descriptor()

    def close(self) -> None:
        if self.controller is not None:
            self.controller.close()


__all__ = ["StimulusControlRuntime"]
