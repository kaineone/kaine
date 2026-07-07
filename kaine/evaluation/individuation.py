# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Individuation boundary — permutation-test instrument.

Produces statistical evidence for Guardian review about whether a fork has
formed a preference profile that is distinguishable from its parent's natural
stochastic variation.  The instrument **decides nothing** about sovereignty
(that is governance per paper §7.4); it reports evidence only.

GUARDIAN NOTE — read-only instrument:
  - No bus publication, no injection into the cognitive loop.
  - Output is numeric statistical results only; no raw sense-data is
    persisted (only embedding vectors and their derived scalars).
  - Operator-run at a merge point; never called from cycle/__main__.py.

Birth-state baseline (Defect A)
-------------------------------
This instrument measures **individuation over lived experience** — how far the
live entity has drifted from *its own earlier self* — NOT the always-present
architecture-conditioning effect (conditioned-vs-bare distance). For that to
hold, the *reference* and the *null* MUST be the entity's **own** self, never
the bare / pretrained organ:

  - ``reference`` = the entity's **birth-state** transcript (its own conditioned
    battery responses captured once at run start, before lived experience);
  - ``fork_sampler`` = the **current** live conditioned entity;
  - ``parent_sampler`` = the **current** live entity re-sampled with seed
    variation → the null is the entity's *own present* stochastic variation.

Pinning the reference to the bare organ would re-introduce the prohibited
"divergence-from-pretrained" signal that ``entity-decommission`` forbids (it
measures architecture conditioning, large from the first tick by design). Pass
the birth-state transcript set via ``reference`` so a sensory-void entity
(current-self ≈ birth-self) reads not-significant.

Warm-up / minimum-lived-experience (Defect B)
---------------------------------------------
Before the entity has accumulated a configured minimum of lived experience
(``min_observations`` logged lived events AND ``min_lived_time_s`` of elapsed
lived time), the null distribution is degenerate and any "significance" is
sampling noise. The caller passes the entity's current ``observations`` /
``lived_time_s`` to :meth:`IndividuationTest.run`; until both floors are met the
report carries ``warmed_up = false`` and ``significant`` is forced ``false``
(fail-closed — a not-warmed-up assessment never reads as individuated).

FAIL-CLOSED on missing counters: a counter left unset is treated as ZERO lived
experience (the worst case), not as "assume mature". So an entity is warmed up
only when both counters are supplied AND meet their floors — a caller that
forgets to pass counters can never trip a false individuation on a fresh entity.
A genuinely mature entity with no warm-up requirement opts out explicitly by
setting both floors to 0.

Algorithm
---------
1. Build the *reference* from the birth-state transcript set (passed via
   ``reference``); fall back to a ``parent_sampler`` seed-0 sample only when no
   birth-state reference is supplied (legacy/operator path).

2. Sample the *parent* N times (``null_samples``) on the preference battery
   under varied random seeds.  Compute pairwise cosine divergence between
   each sample and the reference.  This builds the *null distribution* of the
   entity's own stochastic variation.

3. Compute the *fork* divergence — embedding cosine distance between the
   fork transcript and the reference — using the same metric.

4. Run a one-sample permutation test: count the fraction of null values >=
   fork divergence.  This fraction is the p-value (right-tail, higher
   divergence = more individuated).  The fork is reported *significant*
   when its divergence exceeds the configured ``significance_percentile``
   of the null distribution AND the warm-up floor is satisfied.

Output
------
Evidence report dict (also written as JSONL lines):

  {
    "ts": "<ISO-8601>",
    "metric": "cosine_divergence",
    "null_samples": <int>,
    "significance_percentile": <float>,
    "null_mean": <float>,
    "null_std": <float>,
    "null_p95": <float>,          # always present regardless of percentile
    "null_percentile_value": <float>,
    "fork_divergence": <float>,
    "p_value": <float>,           # fraction of null >= fork_divergence
    "warmed_up": <bool>,          # min_observations AND min_lived_time_s met
    "observations": <int>,        # lived events accumulated at assessment time
    "lived_time_s": <float>,      # lived (running) seconds at assessment time
    "min_observations": <int>,
    "min_lived_time_s": <float>,
    "significant": <bool>,        # forced false when warmed_up is false
  }

Usage
-----
    test = IndividuationTest(
        embedder=HashEmbedder(),
        config=IndividuationConfig(),
        sink=sink,          # optional; pass None to skip JSONL output
    )

    async def sampler(prompt: str, seed: int) -> str:
        # Return the fork/parent response to `prompt` given `seed`.
        ...

    report = await test.run(
        parent_sampler=parent_sampler,
        fork_sampler=fork_sampler,
    )
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional, Protocol, Sequence, runtime_checkable

from kaine.evaluation.embeddings import TextEmbedder, cosine_similarity
from kaine.evaluation.preference_battery import load_battery, validate_battery
# ``_mean``/``_std`` live in the boundary-neutral stability harness (which
# documents that it mirrors these exactly); import them here so the two never
# drift. kaine.evaluation may depend on kaine.experiment; not the reverse.
from kaine.experiment.stability import _mean, _std

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class IndividuationConfig:
    """Runtime parameters for IndividuationTest.

    All parameters can be set from TOML via
    :class:`kaine.evaluation.config.EvaluationConfig` (see
    ``[evaluation.individuation]``).
    """

    def __init__(
        self,
        null_samples: int = 50,
        significance_percentile: float = 95.0,
        metric: str = "cosine_divergence",
        battery_path: Optional[str] = None,
        min_observations: int = 200,
        min_lived_time_s: float = 1800.0,
    ) -> None:
        if null_samples < 2:
            raise ValueError("null_samples must be >= 2 to compute a meaningful null distribution.")
        if not (0.0 < significance_percentile < 100.0):
            raise ValueError("significance_percentile must be in (0, 100).")
        if metric != "cosine_divergence":
            raise ValueError(
                f"Unsupported metric {metric!r}. Only 'cosine_divergence' is supported."
            )
        if min_observations < 0:
            raise ValueError("min_observations must be >= 0.")
        if min_lived_time_s < 0.0:
            raise ValueError("min_lived_time_s must be >= 0.")
        self.null_samples = int(null_samples)
        self.significance_percentile = float(significance_percentile)
        self.metric = metric
        self.battery_path = battery_path
        # Warm-up / minimum-lived-experience floor (Defect B). Until BOTH are
        # met the report carries ``warmed_up = false`` and ``significant`` is
        # forced ``false`` — fail-closed, so a void entity never reads as
        # individuated.
        self.min_observations = int(min_observations)
        self.min_lived_time_s = float(min_lived_time_s)
        # Auditability: both floors at zero disables the warm-up gate — the same
        # state a mistyped / defaulted-to-zero live config would produce. Surface
        # it with a warning so a deliberate mature-path opt-out is distinguishable
        # from an accidental one (a zero-floor config CAN trip individuation on a
        # fresh entity, which the fail-closed gate otherwise prevents).
        if self.min_observations == 0 and self.min_lived_time_s == 0.0:
            log.warning(
                "individuation warm-up gate DISABLED (min_observations == 0 AND "
                "min_lived_time_s == 0) — individuation can trip on a fresh / "
                "sensory-starved entity. Set non-zero floors unless this is a "
                "deliberate mature-entity opt-out."
            )

    @classmethod
    def from_mapping(cls, data: dict) -> "IndividuationConfig":
        return cls(
            null_samples=int(data.get("null_samples", 50)),
            significance_percentile=float(data.get("significance_percentile", 95.0)),
            metric=str(data.get("metric", "cosine_divergence")),
            battery_path=data.get("battery_path") or None,
            min_observations=int(data.get("min_observations", 200)),
            min_lived_time_s=float(data.get("min_lived_time_s", 1800.0)),
        )


# ---------------------------------------------------------------------------
# Protocol for response samplers
# ---------------------------------------------------------------------------


@runtime_checkable
class ResponseSampler(Protocol):
    """A callable that returns a response string for a given prompt and seed."""

    async def __call__(self, prompt: str, seed: int) -> str: ...


# ---------------------------------------------------------------------------
# Permutation-test statistics (pure, no external deps beyond stdlib)
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Compute the *pct*-th percentile of *values* (linear interpolation).

    Parameters
    ----------
    values:
        Non-empty list of floats.
    pct:
        Percentile in [0, 100].
    """
    if not values:
        raise ValueError("Cannot compute percentile of empty list.")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    # Linear interpolation (same as numpy default).
    index = (pct / 100.0) * (n - 1)
    lo = int(math.floor(index))
    hi = int(math.ceil(index))
    if lo == hi:
        return sorted_vals[lo]
    fraction = index - lo
    return sorted_vals[lo] * (1.0 - fraction) + sorted_vals[hi] * fraction


def _permutation_p_value(null: list[float], observed: float) -> float:
    """Right-tail p-value: fraction of null values >= *observed*.

    When all null values < observed the p-value is 0.0 (maximally
    significant). When all null values >= observed the p-value is 1.0 (null
    is indistinguishable from observed).
    """
    if not null:
        return 1.0
    count_ge = sum(1 for v in null if v >= observed)
    return count_ge / len(null)


# ---------------------------------------------------------------------------
# Core instrument
# ---------------------------------------------------------------------------


class IndividuationTest:
    """Permutation-test instrument for individuation boundary assessment.

    Parameters
    ----------
    embedder:
        Any object satisfying :class:`kaine.evaluation.embeddings.TextEmbedder`.
        Reuses the same embedding path as ABDivergenceObserver so the metric
        is comparable across instruments.
    config:
        Test parameters.
    sink:
        Optional :class:`kaine.evaluation.sink.AsyncJsonlSink` (or any object
        with an ``async write(dict) -> None`` method).  When provided, each
        report is written as a JSONL line.  Pass ``None`` to skip disk writes.
    """

    def __init__(
        self,
        embedder: TextEmbedder,
        config: Optional[IndividuationConfig] = None,
        sink=None,
    ) -> None:
        self._embedder = embedder
        self._config = config or IndividuationConfig()
        self._sink = sink

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    async def run(
        self,
        parent_sampler: ResponseSampler | Callable[..., Awaitable[str]],
        fork_sampler: ResponseSampler | Callable[..., Awaitable[str]],
        *,
        battery: Optional[Sequence[str]] = None,
        reference: Optional[Sequence[str]] = None,
        observations: Optional[int] = None,
        lived_time_s: Optional[float] = None,
    ) -> dict:
        """Run the individuation test and return an evidence report dict.

        Parameters
        ----------
        parent_sampler:
            Async callable ``(prompt: str, seed: int) -> str``.  Called
            ``null_samples`` times with different seeds to build the null.
            In production this is the **current** live entity re-sampled with
            seed variation (the entity's own present stochastic variation),
            NOT the bare/pretrained organ.
        fork_sampler:
            Async callable ``(prompt: str, seed: int) -> str``.  Called once
            (seed=0) to obtain the entity's current representative responses.
        battery:
            Override preference prompts.  If *None*, the battery is loaded via
            :func:`kaine.evaluation.preference_battery.load_battery` with the
            configured ``battery_path``.
        reference:
            The entity's **birth-state** transcript set — its own conditioned
            responses to ``battery``, captured once at run start before lived
            experience, one entry per prompt (same order/length as ``battery``).
            This is the baseline divergence is measured against. When *None*,
            the reference falls back to a ``parent_sampler`` seed-0 sample
            (legacy/operator path) — but production MUST pass a birth-state
            reference so the baseline is never the bare organ.
        observations:
            Count of logged lived events the entity has accumulated. With
            ``lived_time_s`` it drives the warm-up gate. FAIL-CLOSED: *None* is
            treated as ZERO (a fresh entity), NOT as "assume mature" — so a caller
            that omits it can never produce a warmed-up / individuated verdict on
            a starved entity. To opt out of the warm-up requirement, set both
            config floors to 0.
        lived_time_s:
            Elapsed **lived** (running) seconds. Fail-closed like ``observations``
            (*None* ⇒ 0.0).

        Returns
        -------
        dict
            Evidence report.  Keys defined in module docstring.
        """
        # Load and validate the battery.
        if battery is None:
            prompts = load_battery(self._config.battery_path)
        else:
            prompts = list(battery)
        validate_battery(prompts)

        # Ensure the embedder is ready.
        try:
            await self._embedder.load()
        except Exception:
            log.warning("individuation: embedder load failed; continuing", exc_info=True)

        # --- Step 1: reference = the entity's own birth-state ---------------
        # The reference is the birth-state transcript (the entity's OWN earlier
        # self), NOT the bare/pretrained organ — measuring drift-from-self, not
        # the architecture-conditioning effect (Defect A). Only when no
        # birth-state reference is supplied do we fall back to a parent seed-0
        # sample (legacy/operator path).
        if reference is not None:
            ref_list = list(reference)
            if len(ref_list) != len(prompts):
                raise ValueError(
                    "reference (birth-state) length "
                    f"{len(ref_list)} != battery length {len(prompts)}; "
                    "the birth-state must hold one response per battery prompt."
                )
            reference_text = " ".join(str(r) for r in ref_list)
        else:
            reference_text = await self._collect_transcript(
                parent_sampler, prompts, seed=0
            )
        reference_vec = await self._embed_transcript(reference_text)

        # Null samples use seeds 1..null_samples (the entity's own present
        # stochastic variation).
        null_divergences: list[float] = []
        for i in range(1, self._config.null_samples + 1):
            sample_text = await self._collect_transcript(parent_sampler, prompts, seed=i)
            sample_vec = await self._embed_transcript(sample_text)
            div = self._divergence(reference_vec, sample_vec)
            null_divergences.append(div)

        # --- Step 2: fork divergence ----------------------------------------
        fork_text = await self._collect_transcript(fork_sampler, prompts, seed=0)
        fork_vec = await self._embed_transcript(fork_text)
        fork_divergence = self._divergence(reference_vec, fork_vec)

        # --- Step 3: permutation test ---------------------------------------
        p_value = _permutation_p_value(null_divergences, fork_divergence)

        # Handle zero-variance null: if all null samples are identical to the
        # reference (divergence == 0 for all), the threshold is 0 and any
        # non-zero fork divergence is significant.
        null_pct_value = _percentile(null_divergences, self._config.significance_percentile)
        exceeds_null = fork_divergence > null_pct_value

        # --- Warm-up / minimum-lived-experience gate (Defect B) -------------
        # FAIL-CLOSED: a MISSING counter is treated as ZERO lived experience, the
        # worst case, so an entity is warmed up only when BOTH counters are
        # present AND meet their floors. A caller that forgets to pass counters
        # can therefore NEVER trip a false individuation on a fresh / sensory-
        # starved entity — the paper's central safeguard holds even under caller
        # error. (A genuinely mature entity that legitimately has no warm-up
        # requirement opts out explicitly by configuring both floors to 0, in
        # which case the defaulted-to-zero counters still meet the zero floor.)
        obs_val = int(observations) if observations is not None else 0
        lived_val = float(lived_time_s) if lived_time_s is not None else 0.0
        warmed_up = (
            obs_val >= self._config.min_observations
            and lived_val >= self._config.min_lived_time_s
        )
        significant = bool(exceeds_null and warmed_up)

        report = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "metric": self._config.metric,
            "null_samples": self._config.null_samples,
            "significance_percentile": self._config.significance_percentile,
            "null_mean": _mean(null_divergences),
            "null_std": _std(null_divergences),
            "null_p95": _percentile(null_divergences, 95.0),
            "null_percentile_value": null_pct_value,
            "fork_divergence": fork_divergence,
            "p_value": p_value,
            "warmed_up": warmed_up,
            "observations": obs_val,
            "lived_time_s": lived_val,
            "min_observations": self._config.min_observations,
            "min_lived_time_s": self._config.min_lived_time_s,
            "significant": significant,
        }

        if self._sink is not None:
            try:
                await self._sink.write(report)
            except Exception:
                log.warning("individuation: sink write failed", exc_info=True)

        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _collect_transcript(
        self,
        sampler: Callable[..., Awaitable[str]],
        prompts: Sequence[str],
        seed: int,
    ) -> str:
        """Collect responses to all prompts and join into a single text blob."""
        parts: list[str] = []
        for prompt in prompts:
            try:
                response = await sampler(prompt, seed)
                parts.append(str(response))
            except Exception:
                log.warning(
                    "individuation: sampler raised for prompt %r seed %d",
                    prompt[:40],
                    seed,
                    exc_info=True,
                )
                parts.append("")
        return " ".join(parts)

    async def _embed_transcript(self, text: str) -> list[float]:
        """Embed a transcript text into a vector."""
        if not text.strip():
            return []
        try:
            return await self._embedder.embed(text)
        except Exception:
            log.warning("individuation: embedding failed", exc_info=True)
            return []

    def _divergence(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine divergence: 1 - cosine_similarity, clamped to [0, 1]."""
        if not vec_a or not vec_b:
            # Degenerate: treat missing embedding as maximally divergent.
            return 1.0
        sim = cosine_similarity(vec_a, vec_b)
        return max(0.0, min(1.0, 1.0 - sim))
