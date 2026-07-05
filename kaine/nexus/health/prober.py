# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""``HealthProber`` — caching, timeout-bounded orchestration over the health
board's dependency probes and per-block snapshot builders.

Answers the operator's first question during bring-up: *what is running,
degraded, down, or simply not configured?* — without reading logs.

Design constraints (see openspec/changes/nexus-dashboard-polish):

  * Probes run **concurrently** with a bounded **per-probe timeout**, so a
    hung dependency never blocks the page or the other probes.
  * Results are **cached briefly** (short TTL) so polling the page does not
    flood the dependencies with health checks.
  * A dependency whose owning module is **disabled** in ``[modules]`` reports
    ``not_configured`` (neutral), never ``down``.
  * Health/metric data is **non-content** — statuses, counts, timestamps — so
    it is shown regardless of ``dev_content_override`` and contains no
    sensory or private text.

The prober only *reads* dependencies (Redis PING, HTTP GETs, a file stat /
``os.access`` check). It never starts, stops, or mutates a service.

The actual per-dependency probes live in :mod:`.probes`; the per-block
snapshot builders (spot, preservation, cycle pacing, ...) live in
:mod:`.blocks`. This module is the caching/scheduling orchestrator that ties
them to instance config and exposes the single :meth:`HealthProber.snapshot`
entrypoint the diagnostics route calls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import blocks
from .probes import (
    DEFAULT_CACHE_TTL_S,
    DEFAULT_PROBE_TIMEOUT_S,
    DOWN,
    NOT_CONFIGURED,
    _now_iso,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DependencySpec:
    """One external dependency the dashboard tracks.

    ``module`` is the key in ``[modules]`` whose enablement gates this
    dependency. When that module is disabled the dependency is reported as
    ``not_configured`` and the probe is skipped entirely.
    """

    name: str
    role: str
    module: str | None
    probe: Callable[[], Awaitable[tuple[str, str]]]


@dataclass
class HealthProber:
    """Builds the dependency specs from loaded config and runs them on demand.

    Construct via :meth:`from_config`. Call :meth:`snapshot` to get a cached,
    timeout-bounded view of every dependency plus per-module live state.
    """

    modules_enabled: dict[str, bool]
    dependencies: list[DependencySpec]
    research_submission_cfg: dict[str, Any] = field(default_factory=dict)
    # Unified deterministic perception-feed descriptor for the perception panel
    # (unified-perception-feed): the active top-level [perception_feed] section.
    # Non-content: mode + seed + video/audio schedule (seeded) or manifest digest
    # (playlist) — covers BOTH the vision and the hearing surface.
    perception_feed_cfg: dict[str, Any] = field(default_factory=dict)
    # Topos frame geometry (capture_width/height), needed to render the seeded
    # video schedule descriptor exactly as the run will generate it.
    topos_capture_geometry: tuple[int, int] = (640, 480)
    # Audition capture geometry (capture_sample_rate/channels), needed to render
    # the seeded audio schedule descriptor exactly as the run will generate it.
    audition_capture_geometry: tuple[int, int] = (16000, 1)
    # Model-server (language-organ) service surface for the diagnostics panel:
    # the configured chat_url + served alias + the bearer key (presence only).
    model_server_cfg: dict[str, Any] = field(default_factory=dict)
    # Graded consolidation-divergence thresholds for the entity-care block's
    # divergence assessment (rate, magnitude). Defaults to None → the
    # assess_divergence shipped conservative defaults.
    consolidation_thresholds: tuple[float, float] | None = None
    cycle_runtime_path: Path = Path("state/cycle/runtime.json")
    # Autonomous safety-net incident-log dir (preservation/welfare-protective
    # records) and the run-manifest root, for the preservation + admissibility
    # blocks. Defaults match the canonical paths the cycle writes.
    preservation_incident_path: Path = Path("state/cycle/preservation")
    runs_manifest_root: Path = Path("data/evaluation/runs")
    evaluation_logs_path: Path = Path("data/evaluation")
    # Spot state files — default to the canonical paths Spot writes.
    spot_control_path: Path = Path("state/cycle/control.json")
    spot_escalation_path: Path = Path("state/cycle/escalation.json")
    gpu_preflight_path: Path = Path("state/cycle/gpu_preflight.json")
    probe_timeout_s: float = DEFAULT_PROBE_TIMEOUT_S
    cache_ttl_s: float = DEFAULT_CACHE_TTL_S
    _cache: dict[str, Any] | None = field(default=None, repr=False)
    _cache_at: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # Allowlist of NON-CONTENT fields surfaced from the preservation incident
    # log + bus events — kept as a class attribute here (not just in
    # blocks.py) because tests and the preservation-panel privacy guard
    # reference it as `HealthProber._PRESERVATION_ALLOWED_FIELDS`.
    _PRESERVATION_ALLOWED_FIELDS = blocks.PRESERVATION_ALLOWED_FIELDS

    # ---- public API ----------------------------------------------------

    async def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        """Return ``{dependencies: [...], modules: [...], checked_at}``.

        Cached for ``cache_ttl_s`` seconds. Concurrent callers share one
        refresh. Never raises: a probe error becomes a ``down`` row.
        """
        now = time.monotonic()
        if (
            not force
            and self._cache is not None
            and (now - self._cache_at) < self.cache_ttl_s
        ):
            return self._cache

        async with self._lock:
            # Re-check inside the lock in case another waiter just refreshed.
            now = time.monotonic()
            if (
                not force
                and self._cache is not None
                and (now - self._cache_at) < self.cache_ttl_s
            ):
                return self._cache
            result = await self._probe_all()
            self._cache = result
            self._cache_at = time.monotonic()
            return result

    # ---- internals -----------------------------------------------------

    def _module_enabled(self, module: str | None) -> bool:
        if module is None:
            return True
        return bool(self.modules_enabled.get(module, False))

    async def _probe_all(self) -> dict[str, Any]:
        async def run_one(spec: DependencySpec) -> dict[str, Any]:
            if not self._module_enabled(spec.module):
                return {
                    "name": spec.name,
                    "role": spec.role,
                    "module": spec.module,
                    "status": NOT_CONFIGURED,
                    "detail": (
                        f"module '{spec.module}' disabled"
                        if spec.module
                        else "not configured"
                    ),
                    "checked_at": _now_iso(),
                }
            status, detail = await self._run_probe(spec)
            return {
                "name": spec.name,
                "role": spec.role,
                "module": spec.module,
                "status": status,
                "detail": detail,
                "checked_at": _now_iso(),
            }

        dep_rows = await asyncio.gather(
            *(run_one(spec) for spec in self.dependencies)
        )
        return {
            "dependencies": list(dep_rows),
            "modules": self._module_states(),
            "spot": self._spot_block(),
            "cycle_pacing": self._cycle_pacing_block(),
            "entity_care": self._entity_care_block(),
            "research": self._research_block(),
            "perception_feed": self._perception_feed_block(),
            "model_server": await self._model_server_block(),
            "voice_alignment_window": self._voice_alignment_window_block(),
            "gpu_preflight": self._gpu_preflight_block(),
            "preservation": self._preservation_block(),
            "welfare": self._welfare_block(),
            "admissibility": self._admissibility_block(),
            "checked_at": _now_iso(),
        }

    # ---- per-block snapshot builders ------------------------------------
    # Thin delegators to kaine.nexus.health.blocks, passing this instance's
    # config/paths explicitly. Kept as methods (rather than inlining the
    # blocks.* calls at call sites) so existing call sites/tests that invoke
    # `prober._xxx_block()` directly keep working unchanged.

    def _preservation_block(self, *, limit: int = 20) -> dict[str, Any]:
        return blocks.preservation_block(
            self.preservation_incident_path,
            self._PRESERVATION_ALLOWED_FIELDS,
            limit=limit,
        )

    def _welfare_block(self) -> dict[str, Any]:
        return blocks.welfare_block(self.evaluation_logs_path)

    def _admissibility_block(self) -> dict[str, Any]:
        return blocks.admissibility_block(
            self.cycle_runtime_path, self.runs_manifest_root
        )

    def _cycle_pacing_block(self) -> dict[str, Any]:
        return blocks.cycle_pacing_block(self.cycle_runtime_path)

    def _entity_care_block(self) -> dict[str, Any]:
        return blocks.entity_care_block(self.consolidation_thresholds)

    def _research_block(self) -> dict[str, Any]:
        return blocks.research_block(self.research_submission_cfg)

    def _voice_alignment_window_block(self) -> dict[str, Any]:
        return blocks.voice_alignment_window_block()

    def _perception_feed_block(self) -> dict[str, Any]:
        return blocks.perception_feed_block(
            self.perception_feed_cfg,
            self.topos_capture_geometry,
            self.audition_capture_geometry,
        )

    async def _model_server_block(self) -> dict[str, Any]:
        return await blocks.model_server_block(
            self.model_server_cfg,
            lingua_enabled=self._module_enabled("lingua"),
        )

    def _gpu_preflight_block(self) -> dict[str, Any]:
        return blocks.gpu_preflight_block(self.gpu_preflight_path)

    def _spot_block(self) -> dict[str, Any]:
        return blocks.spot_block(self.spot_control_path, self.spot_escalation_path)

    def _module_states(self) -> list[dict[str, Any]]:
        return blocks.module_states(self.cycle_runtime_path, self.modules_enabled)

    # ---- probe scheduling -------------------------------------------------

    async def _run_probe(self, spec: DependencySpec) -> tuple[str, str]:
        try:
            return await asyncio.wait_for(spec.probe(), timeout=self.probe_timeout_s)
        except asyncio.TimeoutError:
            return DOWN, f"probe timed out after {self.probe_timeout_s:.0f}s"
        except Exception as exc:  # never let a probe break the board
            log.debug("health probe %s raised", spec.name, exc_info=True)
            return DOWN, f"probe error: {type(exc).__name__}: {exc}"
