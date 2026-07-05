# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""AgentModel — per-agent social model for Empatheia.

Stores numeric histograms, behavioral feature summaries, reliability,
and interaction counts only. Zero raw sense-data persistence: no
transcript text, no raw audio features.

`familiarity()` is in [0, 1] and increases monotonically with both
interaction count and model coverage (how many emotion categories have
been observed at least once).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

# Canonical emotion categories matching audition.emotion payloads.
EMOTION_CATEGORIES: tuple[str, ...] = (
    "angry",
    "disgusted",
    "fearful",
    "happy",
    "neutral",
    "sad",
    "surprised",
    "unknown",
)

# Number of interactions before familiarity saturates (approaches 1).
# Chosen so ~50 interactions → ~0.85, ~200 interactions → ~0.98.
_COUNT_SCALE: float = 50.0

# Blend weight for incremental histogram / reliability updates.
# Smaller = slower drift (more stable); larger = faster adaptation.
_EMA_ALPHA: float = 0.2


@dataclass
class AgentModel:
    """Social model of one interacting agent.

    Fields
    ------
    id : str
        Stable unique identifier (operator-assigned or derived from speaker
        label). Never contains raw transcript or audio data.
    label : str
        Human-readable display label.
    emotion_histogram : dict[str, float]
        Normalised frequency distribution over emotion categories.
        Values sum to ≤ 1.0 (exact 1.0 after the first observation).
    behavioral_summary : dict[str, float]
        Numeric features extracted from the stream of observations:
        currently ``mean_confidence`` and ``mean_prediction_error``.
        Stored as running EMA — no raw sense data.
    reliability : float
        In [0, 1]. Tracks how predictable this agent's behavior is.
        Starts at 1.0 and decays toward 0 when observations frequently
        deviate beyond ``deviation_threshold``.
    interaction_count : int
        Total number of observations folded into this model.
    first_seen : float
        Unix timestamp of the first observation.
    last_seen : float
        Unix timestamp of the most recent observation.
    """

    id: str
    label: str
    emotion_histogram: dict[str, float] = field(default_factory=dict)
    behavioral_summary: dict[str, float] = field(default_factory=dict)
    reliability: float = 1.0
    interaction_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Familiarity
    # ------------------------------------------------------------------

    def familiarity(self) -> float:
        """Return a familiarity score in [0, 1].

        Combines:
        - interaction_count contribution: a saturating sigmoid approaching
          1 as interactions grow (scale constant ~50 interactions).
        - model_coverage contribution: fraction of emotion categories seen
          at least once.

        Both are averaged, so the score rises monotonically as we observe
        more interactions AND as the model covers more categories.
        """
        count_score = 1.0 - math.exp(-self.interaction_count / _COUNT_SCALE)
        seen_categories = sum(1 for v in self.emotion_histogram.values() if v > 0.0)
        coverage = seen_categories / len(EMOTION_CATEGORIES) if EMOTION_CATEGORIES else 0.0
        return (count_score + coverage) / 2.0

    # ------------------------------------------------------------------
    # Update rules
    # ------------------------------------------------------------------

    def update_from_emotion(
        self,
        category: str,
        confidence: float,
        prediction_error: float = 0.0,
        *,
        deviation_threshold: float = 0.5,
        now: float | None = None,
    ) -> float:
        """Fold one emotion observation into the model.

        Parameters
        ----------
        category : str
            Observed emotion category (from ``audition.emotion`` payload).
        confidence : float
            Classifier confidence in [0, 1].
        prediction_error : float
            Forward-model prediction error from the audition event.
        deviation_threshold : float
            Above this deviation the agent is considered out-of-character.
        now : float | None
            Wall-clock timestamp (seconds since epoch). Defaults to
            ``time.time()``.

        Returns
        -------
        float
            Deviation magnitude of this observation from the current model
            (0.0 if no prior model exists).
        """
        ts = now if now is not None else time.time()
        if self.interaction_count == 0:
            self.first_seen = ts

        # Measure deviation BEFORE updating (compare against prior model).
        deviation = self._compute_deviation(category, confidence)

        # Update emotion histogram with EMA blend.
        cat = category if category in EMOTION_CATEGORIES else "unknown"
        for k in EMOTION_CATEGORIES:
            current = self.emotion_histogram.get(k, 0.0)
            target = 1.0 if k == cat else 0.0
            self.emotion_histogram[k] = (
                (1.0 - _EMA_ALPHA) * current + _EMA_ALPHA * target
            )

        # Update behavioral summary (EMA of confidence and prediction_error).
        self.behavioral_summary["mean_confidence"] = (
            (1.0 - _EMA_ALPHA) * self.behavioral_summary.get("mean_confidence", confidence)
            + _EMA_ALPHA * confidence
        )
        self.behavioral_summary["mean_prediction_error"] = (
            (1.0 - _EMA_ALPHA)
            * self.behavioral_summary.get("mean_prediction_error", prediction_error)
            + _EMA_ALPHA * prediction_error
        )

        # Update reliability: decay when out-of-character, recover otherwise.
        if deviation > deviation_threshold:
            self.reliability = max(0.0, self.reliability - _EMA_ALPHA)
        else:
            self.reliability = min(1.0, self.reliability + _EMA_ALPHA * 0.5)

        self.interaction_count += 1
        self.last_seen = ts
        return deviation

    def _compute_deviation(self, category: str, confidence: float) -> float:
        """Deviation of observed category from current histogram model.

        Returns 0.0 before any prior observations exist.
        """
        if self.interaction_count == 0:
            return 0.0
        cat = category if category in EMOTION_CATEGORIES else "unknown"
        expected = self.emotion_histogram.get(cat, 0.0)
        # Deviation is how surprising the observation is relative to its
        # expected frequency, scaled by classifier confidence.
        return (1.0 - expected) * confidence

    # ------------------------------------------------------------------
    # Serialization helpers (for AgentStore)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (no raw sense data)."""
        return {
            "id": self.id,
            "label": self.label,
            "emotion_histogram": dict(self.emotion_histogram),
            "behavioral_summary": dict(self.behavioral_summary),
            "reliability": self.reliability,
            "interaction_count": self.interaction_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentModel":
        model = cls(id=d["id"], label=d.get("label", d["id"]))
        model.emotion_histogram = dict(d.get("emotion_histogram") or {})
        model.behavioral_summary = dict(d.get("behavioral_summary") or {})
        model.reliability = float(d.get("reliability", 1.0))
        model.interaction_count = int(d.get("interaction_count", 0))
        model.first_seen = float(d.get("first_seen", time.time()))
        model.last_seen = float(d.get("last_seen", time.time()))
        return model
