# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Ownership of the single `cl.Neurons` connection and simulator configuration.

Exactly one session exists per process. The broker drives it; module backends
never open their own connection (they receive channel handles from the broker).

Reproducibility note (verified against the vendored simulator): the timing-driven
`neurons.loop()` path is *not* reproducible run-to-run — wall-clock tick
segmentation varies — but the frame-count-driven `neurons.read(n)` path IS
bit-identical across processes for a fixed `CL_SDK_RANDOM_SEED`. So deterministic
offline evaluation reads fixed frame blocks; `loop()` is for real-time cadence.
See `openspec/changes/wetware-substrate-foundation/`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid importing cl at module import time
    import numpy as np


@dataclass(frozen=True)
class SubstrateConfig:
    """Resolved configuration for a substrate session (mirrors the SDK env knobs)."""

    #: "simulator" (default; what we build/validate on) or "hardware" (deliberate,
    #: reviewed opt-in — a real culture is reached only by explicit choice).
    target: str = "simulator"
    #: Simulator only. Decouples the loop from wall-clock for fast offline
    #: evaluation (CL_SDK_ACCELERATED_TIME=1). Must be False on real hardware —
    #: biology runs in real time.
    accelerated_time: bool = False
    #: Optional `.clr`/HDF5 recording to replay instead of synthetic data
    #: (CL_SDK_REPLAY_PATH). None → deterministic synthetic frames from the seed.
    replay_path: str | None = None
    #: Which simulator data source to register before opening: "reference_culture"
    #: (this package's stim-responsive synthetic culture, seeded from random_seed),
    #: "sdk" (cl-sdk's own synthetic data, which ignores stimulation), "replay"
    #: (replay_path), or None to leave whatever source is already registered.
    data_source: str | None = None
    #: Deterministic seed for synthetic data (CL_SDK_RANDOM_SEED).
    random_seed: int = 42
    #: Closed-loop rate. Must be an integer multiple of the cognitive-cycle rate
    #: so substrate sub-ticks nest cleanly in one cognitive tick (broker enforces).
    ticks_per_second: int = 100


class SubstrateSession:
    """Opens and owns one `cl.open()` connection for the whole process."""

    def __init__(self, config: SubstrateConfig) -> None:
        self._config = config
        self._cm: Any = None
        self._neurons: Any = None

    @property
    def config(self) -> SubstrateConfig:
        return self._config

    @property
    def neurons(self) -> Any:
        if self._neurons is None:
            raise RuntimeError("substrate session is not open; call open() first")
        return self._neurons

    def _apply_env(self) -> None:
        cfg = self._config
        os.environ["CL_SDK_ACCELERATED_TIME"] = "1" if cfg.accelerated_time else "0"
        os.environ["CL_SDK_RANDOM_SEED"] = str(cfg.random_seed)
        # Deterministic replay start (offset 0) unless the operator overrides it.
        os.environ.setdefault("CL_SDK_REPLAY_START_OFFSET", "0")
        # The visualisation WebSocket is incompatible with accelerated time and
        # only gets in the way of headless/offline runs; disable it here.
        os.environ["CL_SDK_VISUALISATION"] = "0"
        if cfg.replay_path:
            os.environ["CL_SDK_REPLAY_PATH"] = cfg.replay_path

    def _apply_data_source(self) -> None:
        """Register or clear the simulator data source according to config."""
        if self._config.data_source is None:
            return
        import cl.sim

        source = self._config.data_source
        if source == "reference_culture":
            cl.sim.set_simulator_data_source(
                "kaine_cl1.substrate.sources:make_reference_culture",
                config={"seed": self._config.random_seed},
            )
        elif source == "sdk":
            cl.sim.clear_simulator_data_source()
            os.environ.pop("CL_SDK_REPLAY_PATH", None)
        elif source == "replay":
            cl.sim.clear_simulator_data_source()
            if not self._config.replay_path:
                raise ValueError("data_source 'replay' needs replay_path")
        else:
            raise ValueError(
                f"unknown data_source {source!r}; "
                "expected 'reference_culture', 'sdk', 'replay', or None"
            )

    def open(self) -> Any:
        """Open (and take control of) the one connection. Returns the `Neurons`."""
        import cl  # lazy: importing the SDK is a side-effecting act

        self._apply_env()
        self._apply_data_source()
        if self._config.target != "hardware" and not cl.is_simulator():
            raise RuntimeError(
                "refusing to run: target is 'simulator' but cl.is_simulator() is "
                "False (a real device is present). Set [substrate].target = "
                "'hardware' to opt in deliberately."
            )
        # cl.open() is a context manager; own it beyond a `with` block.
        self._cm = cl.open()
        self._neurons = self._cm.__enter__()
        return self._neurons

    def read_frames(self, frame_count: int) -> "np.ndarray":
        """Read a fixed block of raw frames — the reproducible, timing-independent
        path. Bit-identical across runs for a fixed seed (verified)."""
        import numpy as np

        return np.asarray(self.neurons.read(frame_count))

    def close(self) -> None:
        if self._cm is not None:
            self._cm.__exit__(None, None, None)
            self._cm = None
            self._neurons = None

    def __enter__(self) -> "SubstrateSession":
        self.open()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
