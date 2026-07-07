# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-inference engine for Eidolon.

Populates ``SelfModel.behavioral_norms``, ``personality_baseline``,
``values``, and ``capability_map`` from observed signals already present
in the cognitive loop.

Privacy boundary (load-bearing):
- RAW speech text from ``lingua.out`` events is NEVER persisted.  Only
  counts of utterance *types* (derived from payload metadata, never from
  text content) are accumulated.  ``behavioral_norms`` entries are
  categorical labels, not transcript excerpts.
- VAD values from ``thymos.report`` / ``thymos.drive`` are aggregated
  into rolling mean/variance.  Individual samples are not stored.
- Nous EFE policy labels and counts are stored; raw policy payloads are
  discarded after the numeric summary is extracted.

The engine is disabled by default (``enabled = false`` in config).  When
disabled all methods are no-ops and the SelfModel fields are not touched.

Seed (operator first-boot fallback):
- If ``seed_path`` is configured, the seed JSONL is loaded once on
  ``initialize()``.  Each line must be a JSON object with one or more of
  the four target keys.  The seed is applied as the initial state; later
  observation-driven updates write on top of it.  The seed is applied
  only once — never on subsequent restarts.
"""
from __future__ import annotations

import json
import logging
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional

from kaine.modules.eidolon.capability_map import CapabilityMapBuilder
from kaine.modules.eidolon.document import SelfModel

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal type aliases
# ---------------------------------------------------------------------------

# Rolling window entry for a single VAD sample: (valence, arousal, dominance)
_VADSample = tuple[float, float, float]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Internal-speech type labels Eidolon tracks.  The label is the ``type``
# field of the bus event (e.g. "internal.thought", "speak.internal"), not
# the text content.  We count occurrences of each label; when a label
# accumulates >= speech_pattern_min_count observations it graduates into a
# behavioral norm candidate.
_INTERNAL_SPEECH_TYPES = frozenset({
    "internal.thought",
    "speak.internal",
    "think",
    "internal_speech",
})

# Minimum number of observations for a speech-type label to become a norm.
_DEFAULT_SPEECH_PATTERN_MIN_COUNT = 5

# How many maintenance cycles of VAD data to use for the rolling window.
_DEFAULT_VAD_WINDOW_CYCLES = 10

# Label prefix used for behavioral norms.
_NORM_PREFIX = "speech_pattern:"


class SelfInferenceEngine:
    """Observation-driven self-model population engine.

    Parameters
    ----------
    enabled:
        When False the engine is a no-op.  All methods return immediately.
    vad_window_cycles:
        Number of maintenance cycles over which to compute rolling VAD
        mean/variance for ``personality_baseline``.
    speech_pattern_min_count:
        Minimum number of utterances of a given type before it becomes a
        ``behavioral_norms`` entry.  Keeps fields empty rather than
        speculative.
    seed_path:
        Optional path to an operator-seed JSONL (one JSON object per line).
        Applied once on first boot, never re-applied.
    whitelist_commands:
        Command names from the Praxis effector whitelist.  Injected at
        construction time by ``module.py``.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        vad_window_cycles: int = _DEFAULT_VAD_WINDOW_CYCLES,
        speech_pattern_min_count: int = _DEFAULT_SPEECH_PATTERN_MIN_COUNT,
        seed_path: Optional[str | Path] = None,
        whitelist_commands: Optional[list[str]] = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._vad_window_cycles = max(1, int(vad_window_cycles))
        self._speech_pattern_min_count = max(1, int(speech_pattern_min_count))
        self._seed_path: Optional[Path] = (
            Path(seed_path) if seed_path else None
        )
        self._seed_applied: bool = False

        # Speech-type counts (never stores raw text).
        self._speech_type_counts: Counter[str] = Counter()

        # Drive crossing counts (drive name → count).
        self._drive_counts: Counter[str] = Counter()

        # VAD rolling window (one entry per maintenance cycle).
        self._vad_window: deque[_VADSample] = deque(
            maxlen=self._vad_window_cycles
        )
        # Buffer for the most recent VAD sample observed since the last
        # maintenance cycle; pushed to _vad_window at cycle end.
        self._last_vad: Optional[_VADSample] = None

        # Capability map builder.
        self._cap_builder = CapabilityMapBuilder(whitelist_commands)

    # ------------------------------------------------------------------
    # Properties

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_whitelist_commands(self, commands: Optional[list[str]]) -> None:
        """Inject the Praxis effector whitelist into the capability-map builder.

        Wired once at boot (``boot._wire_eidolon_capabilities``), so the
        self-model's ``capability_map["effectors"]`` reflects what the entity can
        execute. Independent of ``enabled``: the whitelist is stored regardless,
        and surfaces in ``capability_map`` only when self-inference runs on a
        maintenance cycle.
        """
        self._cap_builder.set_whitelist(list(commands) if commands else [])

    # ------------------------------------------------------------------
    # Seed

    def apply_seed(self, model: SelfModel) -> SelfModel:
        """Load the seed JSONL and merge into ``model`` on first boot.

        Only the four target fields are read from the seed; any other keys
        are ignored.  Returns the (possibly updated) model unchanged if the
        seed has already been applied or if ``seed_path`` is not configured.
        """
        if not self._enabled:
            return model
        if self._seed_applied:
            return model
        self._seed_applied = True  # mark before attempting load
        if self._seed_path is None:
            return model
        try:
            lines = Path(self._seed_path).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            log.warning(
                "eidolon self-inference: seed_path %s not found; skipping",
                self._seed_path,
            )
            return model
        except Exception:
            log.warning(
                "eidolon self-inference: failed to read seed_path %s",
                self._seed_path,
                exc_info=True,
            )
            return model

        merged: dict[str, Any] = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.debug("eidolon seed: skipping non-JSON line")
                continue
            if not isinstance(obj, dict):
                continue
            for key in ("values", "behavioral_norms", "personality_baseline", "capability_map"):
                if key in obj:
                    merged[key] = obj[key]

        if not merged:
            return model

        updates: dict[str, Any] = {}
        if "values" in merged:
            values = merged["values"]
            if isinstance(values, list):
                updates["values"] = [str(v) for v in values]
        if "behavioral_norms" in merged:
            norms = merged["behavioral_norms"]
            if isinstance(norms, list):
                updates["behavioral_norms"] = [str(n) for n in norms]
        if "personality_baseline" in merged:
            pb = merged["personality_baseline"]
            if isinstance(pb, dict):
                updates["personality_baseline"] = {
                    str(k): float(v) for k, v in pb.items()
                }
        if "capability_map" in merged:
            cm = merged["capability_map"]
            if isinstance(cm, dict):
                updates["capability_map"] = dict(cm)

        if updates:
            model = model.with_updates(**updates)
            log.info(
                "eidolon self-inference: seed applied (%d fields)", len(updates)
            )
        return model

    # ------------------------------------------------------------------
    # Observation callbacks (called by module.py from the consumer loops)

    def observe_lingua(self, payload: dict[str, Any], event_type: str) -> None:
        """Record one lingua.out event.

        PRIVACY INVARIANT: ``payload`` is inspected for structural metadata
        only (event type label).  Raw text content is NEVER read or stored.
        """
        if not self._enabled:
            return
        # Use the event type label (e.g. "internal.thought") as the
        # observational signal.  Completely ignores "text" or any content
        # fields.  Only types in _INTERNAL_SPEECH_TYPES are counted; all
        # others are silently dropped.
        if event_type in _INTERNAL_SPEECH_TYPES:
            self._speech_type_counts[event_type] += 1

    def observe_thymos_state(self, payload: dict[str, Any]) -> None:
        """Record one thymos.state or thymos.report event (VAD sample)."""
        if not self._enabled:
            return
        state = payload.get("state") or {}
        try:
            v = float(state.get("valence", 0.0))
            a = float(state.get("arousal", 0.0))
            d = float(state.get("dominance", 0.0))
        except (TypeError, ValueError):
            return
        # Buffer the most recent sample; pushed to the rolling window at
        # maintenance_cycle_end() so this inter-cycle period is represented.
        self._last_vad = (v, a, d)

    def observe_thymos_drive(self, payload: dict[str, Any]) -> None:
        """Record one thymos.drive crossing event."""
        if not self._enabled:
            return
        drive = str(payload.get("drive") or "")
        if drive:
            self._drive_counts[drive] += 1

    def observe_nous_policy(self, payload: dict[str, Any]) -> None:
        """Record one nous.policy event."""
        if not self._enabled:
            return
        self._cap_builder.observe_policy(payload)

    # ------------------------------------------------------------------
    # Maintenance cycle end

    def maintenance_cycle_end(self, model: SelfModel) -> SelfModel:
        """Re-derive all four self-model fields and return the updated model.

        Called by ``module.py`` whenever a ``hypnos.sleep.completed`` event
        is observed.  Writes atomically via ``SelfModel.with_updates``.
        Fields that do not yet have sufficient observations are left as they
        are (empty on first boot, seed value if seed was applied).
        """
        if not self._enabled:
            return model

        # Push latest VAD sample onto the rolling window first so that
        # observations made during this inter-maintenance period are included
        # in the current cycle's statistics.
        if self._last_vad is not None:
            self._vad_window.append(self._last_vad)
            self._last_vad = None

        updates: dict[str, Any] = {}

        # 1. behavioral_norms — from speech-type counts.
        norms = self._derive_behavioral_norms()
        if norms is not None:
            updates["behavioral_norms"] = norms

        # 2. personality_baseline — from rolling VAD statistics.
        pb = self._derive_personality_baseline()
        if pb is not None:
            updates["personality_baseline"] = pb

        # 3. values — intersection of norms + drive crossings.
        if norms is not None:
            values = self._derive_values(norms)
            if values is not None:
                updates["values"] = values

        # 4. capability_map — from whitelist + policy outcomes.
        cap = self._cap_builder.build()
        if cap:
            updates["capability_map"] = cap

        if updates:
            model = model.with_updates(**updates)

        return model

    # ------------------------------------------------------------------
    # Internal derivation helpers (pure — no side effects, no text stored)

    def _derive_behavioral_norms(self) -> Optional[list[str]]:
        """Return norm labels for speech types above the min-count threshold.

        Returns ``None`` if no type meets the threshold (so the existing
        field is left untouched rather than being cleared to an empty list).
        """
        qualifying = [
            label
            for label, count in self._speech_type_counts.items()
            if count >= self._speech_pattern_min_count
        ]
        if not qualifying:
            return None
        return sorted(f"{_NORM_PREFIX}{label}" for label in qualifying)

    def _derive_personality_baseline(self) -> Optional[dict[str, float]]:
        """Compute rolling VAD mean and variance from the window.

        Returns ``None`` if the window is empty.
        """
        if not self._vad_window:
            return None
        n = len(self._vad_window)
        sv = sa = sd = 0.0
        for v, a, d in self._vad_window:
            sv += v
            sa += a
            sd += d
        mean_v, mean_a, mean_d = sv / n, sa / n, sd / n

        # Variance (population).
        var_v = var_a = var_d = 0.0
        for v, a, d in self._vad_window:
            var_v += (v - mean_v) ** 2
            var_a += (a - mean_a) ** 2
            var_d += (d - mean_d) ** 2
        var_v /= n
        var_a /= n
        var_d /= n

        return {
            "valence_mean": round(mean_v, 6),
            "valence_var": round(var_v, 6),
            "arousal_mean": round(mean_a, 6),
            "arousal_var": round(var_a, 6),
            "dominance_mean": round(mean_d, 6),
            "dominance_var": round(var_d, 6),
        }

    def _derive_values(self, norms: list[str]) -> Optional[list[str]]:
        """Derive values from the intersection of norms and drive history.

        A *value* in this model is a drive that both:
        - has crossed threshold at least ``speech_pattern_min_count`` times,
        - corresponds to a qualifying speech-type norm (i.e. both internal
          speech and drive activity are consistently present).

        Returns ``None`` if no drive meets the threshold.
        """
        qualifying_drives = [
            drive
            for drive, count in self._drive_counts.items()
            if count >= self._speech_pattern_min_count
        ]
        if not qualifying_drives or not norms:
            return None
        # Accept all qualifying drives when there is at least one norm, to
        # reflect the co-occurrence assumption described in the proposal.
        return sorted(f"drive:{drive}" for drive in qualifying_drives)
