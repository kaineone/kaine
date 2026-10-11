# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Positive control for the information-gain measures in Appendix A.8.

The paper defines per-processor broadcast information gain as
(null_error - error) / running_mean_error, where the null context replaces
other sources by their running means. This module injects a synthetic
informative component into each processor's shadow forward model so we can
verify that the gain measure detects known information and does not pass for
a non-informative component with the same marginal distribution.

In mode "estimate_pc" the module estimates the first principal component of
the processor's inputs (Jolliffe 2002) and the input mean from a preliminary
run. In mode "ladder" it runs pilots at every SNR in SNR_LADDER. In mode
"control" it uses the principal component and planned-test settings written
by the calibration tool (paper Appendix A.8).

The control is off by default and configured only from the
[positive_control] section of a study configuration.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional, Sequence

import numpy as np

from kaine.bus.schema import validate_event
from kaine.experiment.calibration_rules import SNR_LADDER
from kaine.experiment.planned_test_settings import (
    PlannedTestSettingsError,
    load_settings_record,
)
from kaine.experiment.principal_component import (
    PC_ROOT,
    PrincipalComponent,
    PrincipalComponentError,
    PrincipalComponentEstimator,
    file_sha256,
    load_principal_component,
    principal_component_path,
    write_principal_component,
)
from kaine.experiment.run_context import get_run_context
from kaine.storage import resolve

log = logging.getLogger(__name__)

PROCESSORS: tuple[str, ...] = ("topos", "audition", "soma")
POSITIVE_CONTROL_SOURCE: str = "positive_control"
RESULT_EVENT_TYPE: str = "positive_control.result"
LADDER_EVENT_TYPE: str = "positive_control.ladder"
MODES: tuple[str, ...] = ("estimate_pc", "ladder", "control")

RESULT_FIELDS: tuple[str, ...] = (
    "processor",
    "mode",
    "n_reports",
    "ig_with",
    "ig_without",
    "ig_noise",
    "effect",
    "noise_effect",
    "min_effect",
    "min_reports",
    "snr",
    "t_learn_s",
    "settings_sha256",
    "pc_sha256",
    "detected",
    "noise_detected",
    "passed",
    "failed",
    "final",
)

LADDER_FIELDS: tuple[str, ...] = (
    "processor",
    "entity_time_s",
    "gain",
    "gain_with",
    "gain_noise",
    "snr",
    "pc_sha256",
)


@dataclass(frozen=True)
class PositiveControlSettings:
    enabled: bool = False
    mode: Optional[str] = None
    seed: int = 0
    principal_components: Mapping[str, PrincipalComponent] = field(default_factory=dict)
    pc_sha256: Mapping[str, str] = field(default_factory=dict)
    snr: Mapping[str, float] = field(default_factory=dict)
    min_effect: Optional[float] = None
    min_reports: Optional[int] = None
    t_learn_s: Optional[float] = None
    settings_sha256: Optional[str] = None
    pc_root: Optional[str] = None

    def __post_init__(self) -> None:
        if self.pc_root is None:
            object.__setattr__(self, "pc_root", str(resolve(PC_ROOT)))

    @classmethod
    def from_config(
        cls,
        section: Optional[Mapping[str, Any]],
        *,
        pc_root: Optional[Path] = None,
    ) -> "PositiveControlSettings":
        pc_root_path = Path(pc_root) if pc_root is not None else resolve(PC_ROOT)
        pc_root_str = str(pc_root_path)

        if not section:
            return cls(pc_root=pc_root_str)

        allowed = {
            "enabled",
            "mode",
            "seed",
            "principal_components_run",
            "settings_record",
            "snr",
            "min_effect",
            "min_reports",
        }
        unknown = set(section) - allowed
        if unknown:
            raise ValueError(
                f"unknown keys in [positive_control]: {sorted(unknown)}"
            )

        for legacy_key in ("snr", "min_effect", "min_reports"):
            if legacy_key in section:
                raise ValueError(
                    f"[positive_control].{legacy_key} is not a configuration key: "
                    "it comes from the planned-test settings record (paper Appendix A.8)"
                )

        enabled = section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"[positive_control].enabled must be a bool, got {enabled!r}"
            )

        seed = section.get("seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(
                f"[positive_control].seed must be an int, got {seed!r}"
            )

        if not enabled:
            return cls(enabled=False, seed=int(seed), pc_root=pc_root_str)

        mode = section.get("mode")
        if mode not in MODES:
            raise ValueError(
                f"[positive_control].mode must be one of {MODES}, got {mode!r}"
            )

        if mode == "estimate_pc":
            if "principal_components_run" in section:
                raise ValueError(
                    "[positive_control].principal_components_run must be absent in estimate_pc mode"
                )
            if "settings_record" in section:
                raise ValueError(
                    "[positive_control].settings_record must be absent in estimate_pc mode"
                )
            return cls(
                enabled=True,
                mode="estimate_pc",
                seed=int(seed),
                pc_root=pc_root_str,
            )

        if mode == "ladder":
            if "settings_record" in section:
                raise ValueError(
                    "[positive_control].settings_record must be absent in ladder mode"
                )
            run_id = section.get("principal_components_run")
            if not isinstance(run_id, str) or not run_id:
                raise ValueError(
                    "the ladder needs [positive_control].principal_components_run, "
                    "the preliminary run whose principal components the pilots use"
                )

            principal_components: dict[str, PrincipalComponent] = {}
            pc_sha256: dict[str, str] = {}
            for processor in PROCESSORS:
                path = principal_component_path(pc_root_path, run_id, processor)
                try:
                    pc = load_principal_component(path)
                except PrincipalComponentError as exc:
                    raise ValueError(
                        f"failed to load principal component for {processor} from {path}: {exc}"
                    ) from exc
                if pc.processor != processor:
                    raise ValueError(
                        f"principal component in {path} is for {pc.processor!r}, expected {processor!r}"
                    )
                principal_components[processor] = pc
                pc_sha256[processor] = file_sha256(path)

            return cls(
                enabled=True,
                mode="ladder",
                seed=int(seed),
                pc_root=pc_root_str,
                principal_components=principal_components,
                pc_sha256=pc_sha256,
            )

        # control mode
        if "principal_components_run" in section:
            raise ValueError(
                "[positive_control].principal_components_run must be absent in control mode"
            )
        record_path = section.get("settings_record")
        if not isinstance(record_path, str) or not record_path:
            raise ValueError(
                "the positive control needs [positive_control].settings_record"
            )

        try:
            record = load_settings_record(record_path)
        except PlannedTestSettingsError as exc:
            raise ValueError(
                "the positive control cannot start without a valid planned-test settings record: "
                f"{exc}"
            ) from exc

        record_pcs: dict[str, PrincipalComponent] = {}
        record_sha256s: dict[str, str] = {}
        for processor, ref in record.principal_components.items():
            pc_path = resolve(ref.path)
            try:
                pc = load_principal_component(pc_path, expected_sha256=ref.sha256)
            except PrincipalComponentError as exc:
                raise ValueError(
                    f"failed to load principal component for {processor} from {pc_path}: {exc}"
                ) from exc
            record_pcs[processor] = pc
            record_sha256s[processor] = ref.sha256

        return cls(
            enabled=True,
            mode="control",
            seed=int(seed),
            pc_root=pc_root_str,
            principal_components=record_pcs,
            pc_sha256=record_sha256s,
            snr=dict(record.snr),
            min_effect=record.min_effect,
            min_reports=record.min_reports,
            t_learn_s=record.t_learn_s,
            settings_sha256=record.record_sha256,
        )


class ComponentSource:
    """The seeded synthetic context component for one processor.

    Both values scale their noise by the standard deviation of the earlier
    projections only. The informative value is the projection of the current
    input plus scaled noise. The non-informative value is the mean of previous
    projections plus scaled noise, so it has the same marginal distribution
    but no dependence on the current input.
    """

    def __init__(
        self,
        *,
        informative: bool,
        snr: float,
        seed: int,
        processor: str,
        slot: int,
        pc: PrincipalComponent,
        run_seed: int = 0,
    ) -> None:
        if processor not in PROCESSORS:
            raise ValueError(
                f"processor must be one of {PROCESSORS}, got {processor}"
            )
        if pc.processor != processor:
            raise ValueError(
                f"principal component is for {pc.processor!r}, expected {processor!r}"
            )
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
            raise ValueError(
                f"slot must be a non-negative int, got {slot!r}"
            )

        snr_float = float(snr)
        if not math.isfinite(snr_float) or snr_float <= 0.0:
            raise ValueError(
                f"snr must be finite and positive, got {snr}"
            )

        self._informative = bool(informative)
        self._snr = snr_float
        self._processor = processor
        self._slot = slot
        self._pc = pc

        idx = PROCESSORS.index(processor)
        # Independent noise streams per run, processor, rung or control slot, and
        # component. The modulo keeps a negative run seed valid.
        self._noise_rng = np.random.default_rng(
            [seed, run_seed % 2**63, idx, slot, 1 if informative else 2]
        )
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0

    def next(self, x: Sequence[float]) -> float:
        p = self._pc.project(x)
        prev_mean = self._mean
        prev_s = math.sqrt(self._m2 / (self._count - 1)) if self._count >= 2 else 0.0

        self._count += 1
        delta = p - self._mean
        self._mean += delta / self._count
        delta2 = p - self._mean
        self._m2 += delta * delta2

        noise = float(self._noise_rng.standard_normal(1)[0])
        if self._informative:
            return p + (prev_s / math.sqrt(self._snr)) * noise
        return prev_mean + prev_s * math.sqrt(1.0 + 1.0 / self._snr) * noise


class ShadowProbe:
    """Shadow forward model that tracks the raw error drop from one synthetic component."""

    def __init__(self, source: ComponentSource) -> None:
        self._source = source
        self._shadow: Any = None
        self._prev_context: Optional[list[float]] = None
        self._prev_null_context: Optional[list[float]] = None
        self._component_sum = 0.0
        self._component_count = 0
        # The first call only stores the baseline contexts.
        self._started = False

    def prepare(self, live_model: Any) -> None:
        """Build the shadow on the calling thread if it has not been built yet."""
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError("live model lacks widened_copy or hindsight_step")
        if self._shadow is None:
            self._shadow = live_model.widened_copy(1)

    def step(
        self,
        live_model: Any,
        x: Sequence[float],
        context: Optional[Sequence[float]],
        null_context: Optional[Sequence[float]],
        *,
        timespan: Optional[float] = None,
        suspended: Optional[bool] = None,
    ) -> Optional[float]:
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError("live model lacks widened_copy or hindsight_step")

        # First call: create the shadow if still absent and record the baseline.
        if not self._started:
            if self._shadow is None:
                self._shadow = live_model.widened_copy(1)
            self._prev_context = list(context) if context is not None else None
            self._prev_null_context = (
                list(null_context) if null_context is not None else None
            )
            self._started = True
            return None

        full_width = getattr(self._shadow, "context_dim", None)
        if full_width is None:
            full_width = getattr(self._shadow, "_context_dim")
        width = int(full_width) - 1

        if suspended is None:
            self._shadow.suspended = bool(getattr(live_model, "suspended", False))
        else:
            self._shadow.suspended = bool(suspended)

        prev = self._prev_context if self._prev_context is not None else [0.0] * width
        prev_null = self._prev_null_context
        x_list = list(x)

        kwargs: dict[str, Any] = {}
        if timespan is not None:
            kwargs["timespan"] = timespan

        if any(not math.isfinite(v) for v in x_list):
            self._shadow.hindsight_step(x_list, prev + [0.0], None, **kwargs)
            self._prev_context = list(context) if context is not None else None
            self._prev_null_context = (
                list(null_context) if null_context is not None else None
            )
            return None

        c = self._source.next(x_list)
        # The null context must use the running mean of earlier components only.
        c_mean = (
            self._component_sum / self._component_count if self._component_count else 0.0
        )
        self._component_sum += c
        self._component_count += 1

        ctx = prev + [c]
        null_ctx = (prev_null + [c_mean]) if prev_null is not None else None
        error, null_error = self._shadow.hindsight_step(
            x_list, ctx, null_ctx, **kwargs
        )

        had_context = self._prev_context is not None
        self._prev_context = list(context) if context is not None else None
        self._prev_null_context = (
            list(null_context) if null_context is not None else None
        )

        if error is None or null_error is None:
            return None

        raw = null_error - error
        if had_context and math.isfinite(raw):
            return raw
        return None


class PositiveControl:
    """Runs the positive control for one processor and reports the verdict."""

    def __init__(
        self,
        processor: str,
        settings: PositiveControlSettings,
    ) -> None:
        if processor not in PROCESSORS:
            raise ValueError(
                f"processor must be one of {PROCESSORS}, got {processor}"
            )
        if not settings.enabled:
            raise ValueError("positive control is disabled in [positive_control]")
        if settings.mode not in MODES:
            raise ValueError(
                f"positive control mode must be one of {MODES}, got {settings.mode!r}"
            )

        # The paper's noise eps_t is independent Gaussian noise, and the pilots
        # estimate the control's run-to-run variance, so each run draws its own
        # noise: the streams are seeded from the run's seed as well.
        run_ctx = get_run_context()
        run_seed = int(run_ctx.seed) if run_ctx is not None else 0
        self._run_seed = run_seed

        self._processor = processor
        self._settings = settings
        self._mode = settings.mode
        self._probes: list[ShadowProbe] = []
        self._estimator: Optional[PrincipalComponentEstimator] = None
        self._ladder_n = 0
        self._sum_with = 0.0
        self._sum_without = 0.0
        self._sum_noise = 0.0
        self._n = 0

        if self._mode == "estimate_pc":
            self._estimator = PrincipalComponentEstimator()
        elif self._mode == "ladder":
            pc = settings.principal_components.get(processor)
            if pc is None:
                raise ValueError(
                    f"ladder mode needs a principal component for {processor}"
                )
            for i, snr in enumerate(SNR_LADDER):
                slot = i + 1
                self._probes.append(
                    ShadowProbe(
                        ComponentSource(
                            informative=True,
                            snr=snr,
                            seed=settings.seed,
                            processor=processor,
                            slot=slot,
                            pc=pc,
                            run_seed=run_seed,
                        )
                    )
                )
                self._probes.append(
                    ShadowProbe(
                        ComponentSource(
                            informative=False,
                            snr=snr,
                            seed=settings.seed,
                            processor=processor,
                            slot=slot,
                            pc=pc,
                            run_seed=run_seed,
                        )
                    )
                )
        else:  # control
            pc = settings.principal_components.get(processor)
            if pc is None:
                raise ValueError(
                    f"control mode needs a principal component for {processor}"
                )
            snr = settings.snr.get(processor)
            if snr is None:
                raise ValueError(
                    f"control mode needs snr for {processor}"
                )
            if not math.isfinite(snr) or snr <= 0.0:
                raise ValueError(
                    f"snr for {processor} must be finite and positive, got {snr}"
                )
            if settings.min_effect is None:
                raise ValueError(
                    f"control mode needs min_effect for {processor}"
                )
            if not math.isfinite(settings.min_effect) or settings.min_effect <= 0.0:
                raise ValueError(
                    f"min_effect for {processor} must be finite and positive, got {settings.min_effect}"
                )
            if settings.min_reports is None:
                raise ValueError(
                    f"control mode needs min_reports for {processor}"
                )
            if isinstance(settings.min_reports, bool) or not isinstance(settings.min_reports, int) or settings.min_reports < 1:
                raise ValueError(
                    f"min_reports for {processor} must be an int >= 1, got {settings.min_reports}"
                )
            if settings.t_learn_s is None:
                raise ValueError(
                    f"control mode needs t_learn_s for {processor}"
                )
            if not math.isfinite(settings.t_learn_s) or settings.t_learn_s < 0.0:
                raise ValueError(
                    f"t_learn_s for {processor} must be finite and non-negative, got {settings.t_learn_s}"
                )

            self._probes = [
                ShadowProbe(
                    ComponentSource(
                        informative=True,
                        snr=snr,
                        seed=settings.seed,
                        processor=processor,
                        slot=0,
                        pc=pc,
                        run_seed=run_seed,
                    )
                ),
                ShadowProbe(
                    ComponentSource(
                        informative=False,
                        snr=snr,
                        seed=settings.seed,
                        processor=processor,
                        slot=0,
                        pc=pc,
                        run_seed=run_seed,
                    )
                ),
            ]

    def prepare(self, live_model: Any) -> None:
        """Build the shadows on the calling thread.

        The modules call it on the event-loop thread before stepping the
        control in a worker thread.
        """
        if self._mode == "estimate_pc":
            return

        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError(
                f"live model for {self._processor} lacks widened_copy or hindsight_step"
            )

        for probe in self._probes:
            probe.prepare(live_model)

    def after_report(
        self,
        live_model: Any,
        x: Sequence[float],
        context: Optional[Sequence[float]],
        null_context: Optional[Sequence[float]],
        live_gain: Optional[float],
        live_mean_error: Optional[float],
        *,
        awake: bool,
        entity_time_s: float,
        timespan: Optional[float] = None,
        suspended: Optional[bool] = None,
    ) -> Optional[dict[str, Any]]:
        if self._mode != "estimate_pc":
            if not hasattr(live_model, "widened_copy") or not hasattr(
                live_model, "hindsight_step"
            ):
                raise TypeError(
                    f"live model for {self._processor} lacks widened_copy or hindsight_step"
                )

        if self._mode == "estimate_pc":
            if awake:
                arr = np.asarray(x, dtype=float)
                if arr.size > 0 and np.all(np.isfinite(arr)):
                    self._estimator.add(x)
            return None

        if self._mode == "ladder":
            deltas: list[Optional[float]] = []
            for probe in self._probes:
                d = probe.step(
                    live_model,
                    x,
                    context,
                    null_context,
                    timespan=timespan,
                    suspended=suspended,
                )
                deltas.append(d)

            if (
                awake
                and live_gain is not None
                and live_mean_error is not None
                and math.isfinite(live_gain)
                and math.isfinite(live_mean_error)
                and live_mean_error > 0.0
                and all(d is not None and math.isfinite(d) for d in deltas)
            ):
                self._ladder_n += 1
                return {
                    "record": "ladder",
                    "processor": self._processor,
                    "entity_time_s": entity_time_s,
                    "gain": live_gain,
                    "gain_with": [d / live_mean_error for d in deltas[0::2]],
                    "gain_noise": [d / live_mean_error for d in deltas[1::2]],
                    "snr": list(SNR_LADDER),
                    "pc_sha256": self._settings.pc_sha256.get(self._processor),
                }
            return None

        # control mode
        d_with = self._probes[0].step(
            live_model, x, context, null_context, timespan=timespan,
            suspended=suspended,
        )
        d_noise = self._probes[1].step(
            live_model, x, context, null_context, timespan=timespan,
            suspended=suspended,
        )

        if (
            awake
            and entity_time_s > self._settings.t_learn_s
            and live_gain is not None
            and live_mean_error is not None
            and d_with is not None
            and d_noise is not None
            and math.isfinite(live_gain)
            and math.isfinite(live_mean_error)
            and live_mean_error > 0.0
            and math.isfinite(d_with)
            and math.isfinite(d_noise)
        ):
            self._sum_with += d_with / live_mean_error
            self._sum_without += live_gain
            self._sum_noise += d_noise / live_mean_error
            self._n += 1
            return self.result()
        return None

    def result(self) -> dict[str, Any]:
        pc_sha256 = self._settings.pc_sha256.get(self._processor)

        if self._mode == "control":
            n = self._n
            ig_with = self._sum_with / n if n else None
            ig_without = self._sum_without / n if n else None
            ig_noise = self._sum_noise / n if n else None
            effect = (ig_with - ig_without) if n else None
            noise_effect = (ig_noise - ig_without) if n else None

            if n == 0:
                detected = noise_detected = passed = None
            else:
                detected = bool(effect >= self._settings.min_effect)
                noise_detected = bool(noise_effect >= self._settings.min_effect)
                passed = bool(
                    n >= self._settings.min_reports
                    and detected
                    and not noise_detected
                )

            return {
                "record": "result",
                "processor": self._processor,
                "mode": "control",
                "n_reports": n,
                "ig_with": ig_with,
                "ig_without": ig_without,
                "ig_noise": ig_noise,
                "effect": effect,
                "noise_effect": noise_effect,
                "min_effect": self._settings.min_effect,
                "min_reports": self._settings.min_reports,
                "snr": self._settings.snr[self._processor],
                "t_learn_s": self._settings.t_learn_s,
                "settings_sha256": self._settings.settings_sha256,
                "pc_sha256": pc_sha256,
                "detected": detected,
                "noise_detected": noise_detected,
                "passed": passed,
                "failed": False,
                "final": False,
            }

        if self._mode == "ladder":
            return {
                "record": "result",
                "processor": self._processor,
                "mode": "ladder",
                "n_reports": self._ladder_n,
                "ig_with": None,
                "ig_without": None,
                "ig_noise": None,
                "effect": None,
                "noise_effect": None,
                "min_effect": None,
                "min_reports": None,
                "snr": None,
                "t_learn_s": None,
                "settings_sha256": None,
                "pc_sha256": pc_sha256,
                "detected": None,
                "noise_detected": None,
                "passed": None,
                "failed": False,
                "final": False,
            }

        # estimate_pc mode
        return {
            "record": "result",
            "processor": self._processor,
            "mode": "estimate_pc",
            "n_reports": self._estimator.n,
            "ig_with": None,
            "ig_without": None,
            "ig_noise": None,
            "effect": None,
            "noise_effect": None,
            "min_effect": None,
            "min_reports": None,
            "snr": None,
            "t_learn_s": None,
            "settings_sha256": None,
            "pc_sha256": pc_sha256,
            "detected": None,
            "noise_detected": None,
            "passed": None,
            "failed": False,
            "final": False,
        }

    def final_result(self) -> dict[str, Any]:
        """The current result marked as the run's terminal record for this processor;
        published at a clean shutdown.
        """
        if self._mode == "estimate_pc":
            run_context = get_run_context()
            if run_context is None:
                raise PrincipalComponentError(
                    "no run context: the preliminary run cannot record its principal component"
                )
            pc = self._estimator.result(
                processor=self._processor, run_id=run_context.run_id
            )
            pc_root = (
                Path(self._settings.pc_root)
                if self._settings.pc_root is not None
                else resolve(PC_ROOT)
            )
            path = principal_component_path(pc_root, run_context.run_id, self._processor)
            sha = write_principal_component(pc, path)
            result = self.result()
            result["pc_sha256"] = sha
            result["final"] = True
            return result

        result = self.result()
        result["final"] = True
        return result

    def failure_result(self) -> dict[str, Any]:
        """The current result marked as failed, so a run whose control stopped cannot pass."""
        result = self.result()
        result["failed"] = True
        result["passed"] = False
        result["final"] = True
        return result


class ControlQueue:
    """Runs a processor's positive-control steps one at a time, in submission order, off the report path."""

    def __init__(self, *, max_pending: int = 256) -> None:
        self._max_pending = max_pending
        self._queue: asyncio.Queue[Callable[[], Awaitable[None]]] = asyncio.Queue(
            maxsize=max_pending
        )
        self._worker: Optional[asyncio.Task[None]] = None

    def submit(self, job: Callable[[], Awaitable[None]]) -> bool:
        """Enqueue a job; start the single worker task on the running loop if needed."""
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            return False
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run())
        return True

    async def drain(self) -> None:
        """Return when every submitted job has finished."""
        await self._queue.join()

    async def close(self) -> None:
        """Drain, then cancel and await the worker task; submit after close restarts it."""
        await self.drain()
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            finally:
                self._worker = None
        else:
            self._worker = None

    async def _run(self) -> None:
        """Worker loop that awaits each job in order and logs exceptions."""
        while True:
            job = await self._queue.get()
            try:
                await job()
            except Exception:
                log.exception("Positive-control job failed.")
            finally:
                self._queue.task_done()


async def publish_result(bus: Any, result: Mapping[str, Any]) -> str:
    event_type = (
        LADDER_EVENT_TYPE if result.get("record") == "ladder" else RESULT_EVENT_TYPE
    )
    payload = {k: v for k, v in result.items() if k != "record"}
    event = validate_event(
        source=POSITIVE_CONTROL_SOURCE,
        type=event_type,
        payload=payload,
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    return await bus.publish(event)


async def finish_positive_controls(modules: Iterable[Any]) -> None:
    """Publish every module's positive-control terminal record.

    The cycle calls this during shutdown before it stops the research log, so
    the terminal records reach the log. A module without a control is skipped.
    """
    for module in modules:
        finish = getattr(module, "finish_positive_control", None)
        if finish is None:
            continue
        try:
            await finish()
        except Exception:
            log.error(
                "%s: finishing the positive control failed",
                getattr(module, "name", module),
                exc_info=True,
            )
