# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Discrete generative model for Nous active inference (pymdp 1.0, JAX).

Nous reframes reasoning as active inference (KAINE Paper §3.3.2): belief
updating + policy selection by expected-free-energy (EFE) minimisation, using
**pymdp 1.0**'s JAX-native :class:`pymdp.agent.Agent`.

The workspace is open-ended; pymdp needs a *fixed discrete* generative model.
v1 keeps a deliberately **compact** factor set derived from workspace content
(the paper flags pymdp-at-scale as unvalidated, §9):

Hidden state factors
--------------------
0. ``action_latent`` — the controllable factor. Its states line up 1:1 with the
   v1 :data:`ACTION_SPACE`; it is the *only* control factor, so EFE planning
   evaluates exactly ``len(ACTION_SPACE)`` policies. Other factors are
   uncontrollable (a single, identity transition).
1. ``salience_band`` — coarse salience of the dominant coalition member
   (low / medium / high by default).
2. ``affect_quadrant`` — Thymos valence×arousal quadrant
   (calm-pleasant / excited-pleasant / calm-unpleasant / excited-unpleasant).
3. ``event_cluster`` — a small set of recurring event-type clusters (the open
   seam; see :func:`register_event_cluster`).

Observation modalities mirror the perceptual factors 1:1 (an identity-ish
likelihood ``A``), so a clear observation cleanly identifies the latent band.
The ``action_latent`` factor has its own modality too (the entity observes its
own last action), which keeps the model square and gives ``infer_states`` a
modality per factor.

Everything is built as **JAX arrays / lists-of-arrays over factors/modalities**
to match the pymdp 1.0 API. The :class:`GenerativeModel` dataclass holds the
A/B/C/D tensors plus the labels needed to translate a posterior back into the
preserved ``nous.belief`` contract.

Seam to grow factors online
---------------------------
v1 ships a frozen factor set. :func:`register_event_cluster` documents the
single intended growth point: new recurring event-type clusters extend the
``event_cluster`` factor. Growing factor *count* (vs. states) means rebuilding
the model and the agent; that is intentionally out of scope for v1 but the
encode path tolerates unseen clusters gracefully (they map to the catch-all
``other`` state) so the running model never crashes on novel input.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import numpy as np

# --------------------------------------------------------------------------
# Authoritative v1 action space.
# --------------------------------------------------------------------------
# The B-matrix of the controllable factor (factor 0) is indexed over this
# fixed four-element action space. `request_think` is an EPISTEMIC action:
# it keeps computation internal to the cognitive loop and therefore does NOT
# require a Praxis whitelist entry — the absence of a whitelist is not a v1
# blocker. `request_speak` / `request_maintenance` are still proposed only as
# intents; Syneidesis inhibition + Praxis whitelists in the executive path
# gate whether they are ever realized (Nous proposes, the executive disposes).
ACTION_SPACE: tuple[str, ...] = (
    "no_op",
    "request_think",
    "request_speak",
    "request_maintenance",
)

# Default perceptual factor labels (states). These are the human-readable
# labels surfaced in the preserved `nous.belief.statement` field.
SALIENCE_BANDS: tuple[str, ...] = ("salience_low", "salience_medium", "salience_high")

AFFECT_QUADRANTS: tuple[str, ...] = (
    "affect_calm_pleasant",
    "affect_excited_pleasant",
    "affect_calm_unpleasant",
    "affect_excited_unpleasant",
)

# The event-cluster factor's *baseline* states. Index 0 is always the
# catch-all `other` bucket that unseen / unmapped event types fall into, so
# encode never produces an out-of-range index. Growing this tuple (via
# `register_event_cluster`) is the documented online-growth seam.
DEFAULT_EVENT_CLUSTERS: tuple[str, ...] = (
    "cluster_other",
    "cluster_perception",
    "cluster_affect",
    "cluster_self",
)

# Mapping from event SOURCE (module name) to an event-cluster label. Unmapped
# sources fall through to `cluster_other`. This is intentionally small in v1.
_SOURCE_TO_CLUSTER: dict[str, str] = {
    "soma": "cluster_perception",
    "topos": "cluster_perception",
    "audition": "cluster_perception",
    "chronos": "cluster_perception",
    "thymos": "cluster_affect",
    "empatheia": "cluster_affect",
    "eidolon": "cluster_self",
    "mnemos": "cluster_self",
}

# Factor / modality ordering. Factor 0 is the (single) control factor.
ACTION_FACTOR = 0
SALIENCE_FACTOR = 1
AFFECT_FACTOR = 2
EVENT_FACTOR = 3


@dataclass(frozen=True)
class GenerativeModel:
    """A built pymdp 1.0 generative model + the labels needed to read it back.

    ``A``/``B``/``C``/``D`` are lists of ``numpy`` arrays in pymdp's
    list-over-modalities / list-over-factors layout. They are kept as numpy so
    the model is cheap to serialize and so :mod:`engine` can hand them to
    :class:`pymdp.agent.Agent` (which casts to JAX). ``state_labels`` gives the
    human-readable label for every (factor, state) so a posterior can be
    rendered into the preserved ``nous.belief`` contract.
    """

    A: list[np.ndarray]
    B: list[np.ndarray]
    C: list[np.ndarray]
    D: list[np.ndarray]
    A_dependencies: list[list[int]]
    num_states: list[int]
    num_obs: list[int]
    state_labels: list[tuple[str, ...]]
    actions: tuple[str, ...] = ACTION_SPACE
    # Perceptual factor labels, retained for encode_snapshot lookups.
    salience_bands: tuple[str, ...] = SALIENCE_BANDS
    affect_quadrants: tuple[str, ...] = AFFECT_QUADRANTS
    event_clusters: tuple[str, ...] = DEFAULT_EVENT_CLUSTERS

    @property
    def num_factors(self) -> int:
        return len(self.B)

    @property
    def num_modalities(self) -> int:
        return len(self.A)

    @property
    def num_actions(self) -> int:
        return len(self.actions)


def register_event_cluster(
    clusters: Sequence[str],
    *,
    source: str,
    label: str,
) -> tuple[str, ...]:
    """Document/extend the online-growth seam for event clusters.

    v1 does NOT grow the model live (growing factor cardinality means
    rebuilding the agent), but this is the single intended growth point: add a
    new recurring event-type cluster and route a source to it. Returns the new
    cluster tuple; the caller rebuilds the model from it. Idempotent.
    """
    if label not in clusters:
        clusters = tuple(clusters) + (label,)
    _SOURCE_TO_CLUSTER[source] = label
    return tuple(clusters)


def _normalize_columns(mat: np.ndarray) -> np.ndarray:
    """Normalise a 2-D likelihood/transition slice over axis 0 (the output)."""
    col_sums = mat.sum(axis=0, keepdims=True)
    col_sums = np.where(col_sums == 0.0, 1.0, col_sums)
    return mat / col_sums


def build_generative_model(
    *,
    actions: Sequence[str] = ACTION_SPACE,
    salience_bands: Sequence[str] = SALIENCE_BANDS,
    affect_quadrants: Sequence[str] = AFFECT_QUADRANTS,
    event_clusters: Sequence[str] = DEFAULT_EVENT_CLUSTERS,
    max_states_per_factor: Optional[int] = None,
    likelihood_confidence: float = 0.9,
) -> GenerativeModel:
    """Construct the compact A/B/C/D generative model.

    Parameters
    ----------
    actions:
        The control factor's states / the v1 action space. Defaults to
        :data:`ACTION_SPACE` (four actions).
    salience_bands, affect_quadrants, event_clusters:
        State labels for the three perceptual factors.
    max_states_per_factor:
        Optional cap; raises ``ValueError`` if any factor exceeds it. Used by
        the complexity-envelope validator so a misconfiguration fails loudly.
    likelihood_confidence:
        Diagonal mass of the observation likelihood ``A`` for the perceptual
        factors (the rest is spread uniformly over the off-diagonal), so a
        clear observation strongly — but not infinitely — identifies its
        latent band. Must be in (0, 1].
    """
    if not 0.0 < likelihood_confidence <= 1.0:
        raise ValueError("likelihood_confidence must be in (0, 1]")

    actions = tuple(actions)
    salience_bands = tuple(salience_bands)
    affect_quadrants = tuple(affect_quadrants)
    event_clusters = tuple(event_clusters)
    if len(actions) < 1:
        raise ValueError("action space must be non-empty")

    # Factor cardinalities, in factor order.
    num_states = [
        len(actions),
        len(salience_bands),
        len(affect_quadrants),
        len(event_clusters),
    ]
    state_labels: list[tuple[str, ...]] = [
        actions,
        salience_bands,
        affect_quadrants,
        event_clusters,
    ]
    if max_states_per_factor is not None:
        for f, n in enumerate(num_states):
            if n > max_states_per_factor:
                raise ValueError(
                    f"factor {f} has {n} states, exceeds max_states_per_factor="
                    f"{max_states_per_factor}"
                )

    # One observation modality per factor (square model). Identity-ish A.
    num_obs = list(num_states)
    n_factors = len(num_states)
    A_dependencies = [[f] for f in range(n_factors)]

    A: list[np.ndarray] = []
    for f in range(n_factors):
        n = num_states[f]
        if f == ACTION_FACTOR:
            # The entity observes its own last action exactly (identity).
            mat = np.eye(n)
        else:
            off = (1.0 - likelihood_confidence) / max(n - 1, 1)
            mat = np.full((n, n), off)
            np.fill_diagonal(mat, likelihood_confidence)
            mat = _normalize_columns(mat)
        A.append(mat)

    # Transition B. Factor 0 (action_latent) is controllable: action a moves
    # the latent deterministically to state a (the entity "becomes" the action
    # it takes). Every other factor is uncontrollable: a single identity slice.
    B: list[np.ndarray] = []
    for f in range(n_factors):
        n = num_states[f]
        if f == ACTION_FACTOR:
            n_actions = len(actions)
            mat = np.zeros((n, n, n_actions))
            for a in range(n_actions):
                # next-state == a regardless of previous state.
                slice_ = np.zeros((n, n))
                slice_[a, :] = 1.0
                mat[:, :, a] = slice_
        else:
            mat = np.zeros((n, n, 1))
            mat[:, :, 0] = np.eye(n)
        B.append(mat)

    # Preferences C over observations. v1: mildly prefer the "no_op" /
    # low-arousal-ish baseline is NOT encoded; instead we prefer observing a
    # HIGH-salience signal (information-rich) and stay neutral elsewhere. This
    # gives EFE something to discriminate over while remaining conservative.
    C: list[np.ndarray] = []
    for f in range(n_factors):
        pref = np.zeros(num_obs[f])
        if f == SALIENCE_FACTOR and len(salience_bands) >= 1:
            # Prefer the highest salience band (last index) — being engaged
            # with the most salient content is the entity's default disposition.
            pref[-1] = 1.0
        C.append(pref)

    # Prior D over hidden states: uniform (no strong prior in v1), except the
    # action latent starts at no_op (index 0).
    D: list[np.ndarray] = []
    for f in range(n_factors):
        n = num_states[f]
        if f == ACTION_FACTOR:
            d = np.zeros(n)
            d[0] = 1.0
        else:
            d = np.full(n, 1.0 / n)
        D.append(d)

    return GenerativeModel(
        A=A,
        B=B,
        C=C,
        D=D,
        A_dependencies=A_dependencies,
        num_states=num_states,
        num_obs=num_obs,
        state_labels=state_labels,
        actions=actions,
        salience_bands=salience_bands,
        affect_quadrants=affect_quadrants,
        event_clusters=event_clusters,
    )


def _salience_to_band(salience: float, n_bands: int) -> int:
    """Map a [0, 1] salience to a band index, robust to n_bands == 1."""
    if n_bands <= 1:
        return 0
    s = min(max(float(salience), 0.0), 1.0)
    idx = int(s * n_bands)
    return min(idx, n_bands - 1)


def _affect_to_quadrant(valence: float, arousal: float, n_quadrants: int) -> int:
    """Map valence/arousal to a quadrant index in the AFFECT_QUADRANTS order.

    Order: calm-pleasant, excited-pleasant, calm-unpleasant, excited-unpleasant.
    Falls back to index 0 if the factor was shrunk below four states.
    """
    if n_quadrants < 4:
        return 0
    pleasant = float(valence) >= 0.0
    excited = float(arousal) >= 0.5
    if pleasant and not excited:
        return 0
    if pleasant and excited:
        return 1
    if not pleasant and not excited:
        return 2
    return 3


def _dominant_event(snapshot: Any) -> Optional[tuple[float, Any]]:
    """Return (salience, event) of the most-salient selected event, or None."""
    best: Optional[tuple[float, Any]] = None
    for _entry_id, event in getattr(snapshot, "selected_events", []) or []:
        sal = float(getattr(event, "salience", 0.0) or 0.0)
        if best is None or sal > best[0]:
            best = (sal, event)
    return best


def encode_snapshot(
    snapshot: Any,
    model: GenerativeModel,
) -> list[int]:
    """Map a :class:`WorkspaceSnapshot` to pymdp observation indices.

    Returns one integer observation index per modality (in modality order:
    action_latent, salience_band, affect_quadrant, event_cluster). Missing or
    malformed factors degrade gracefully to a safe default index rather than
    raising — the engine must never crash the cognitive cycle on odd input.

    - action_latent modality: the entity has not yet acted this cycle, so it
      observes ``no_op`` (index 0). The engine overwrites this from the chosen
      action on the next cycle if it wants closed-loop self-observation.
    - salience_band: band of the dominant coalition member's salience (0 if no
      events).
    - affect_quadrant: derived from a Thymos event in the coalition if present;
      else the neutral calm-pleasant quadrant (index 0).
    - event_cluster: cluster of the dominant event's source; ``cluster_other``
      (index 0) if unmapped / no events.
    """
    n_action = model.num_obs[ACTION_FACTOR]
    n_sal = model.num_obs[SALIENCE_FACTOR]
    n_aff = model.num_obs[AFFECT_FACTOR]
    n_evt = model.num_obs[EVENT_FACTOR]

    obs = [0, 0, 0, 0]

    # action_latent: always no_op at the start of a cycle.
    obs[ACTION_FACTOR] = 0

    dominant = _dominant_event(snapshot)
    if dominant is None:
        # No coalition members: safe neutral defaults.
        obs[SALIENCE_FACTOR] = 0
        obs[AFFECT_FACTOR] = 0
        obs[EVENT_FACTOR] = 0
        return [min(o, n - 1) for o, n in zip(obs, (n_action, n_sal, n_aff, n_evt))]

    dom_sal, dom_event = dominant
    obs[SALIENCE_FACTOR] = _salience_to_band(dom_sal, n_sal)

    # affect: prefer an explicit Thymos affect signal anywhere in the coalition.
    valence: Optional[float] = None
    arousal: Optional[float] = None
    for _eid, event in getattr(snapshot, "selected_events", []) or []:
        payload = getattr(event, "payload", {}) or {}
        if getattr(event, "source", "") == "thymos":
            state = payload.get("state") if isinstance(payload, dict) else None
            if isinstance(state, dict):
                if "valence" in state:
                    valence = _safe_float(state.get("valence"))
                if "arousal" in state:
                    arousal = _safe_float(state.get("arousal"))
            if isinstance(payload, dict):
                if valence is None and "valence" in payload:
                    valence = _safe_float(payload.get("valence"))
                if arousal is None and "arousal" in payload:
                    arousal = _safe_float(payload.get("arousal"))
    if valence is None:
        valence = 0.0
    if arousal is None:
        arousal = 0.0
    obs[AFFECT_FACTOR] = _affect_to_quadrant(valence, arousal, n_aff)

    # event_cluster: from the dominant event's source.
    source = str(getattr(dom_event, "source", "") or "")
    cluster_label = _SOURCE_TO_CLUSTER.get(source, "cluster_other")
    try:
        obs[EVENT_FACTOR] = model.event_clusters.index(cluster_label)
    except ValueError:
        obs[EVENT_FACTOR] = 0

    # Clamp every index defensively to its modality's cardinality.
    return [min(max(o, 0), n - 1) for o, n in zip(obs, (n_action, n_sal, n_aff, n_evt))]


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ACTION_SPACE",
    "SALIENCE_BANDS",
    "AFFECT_QUADRANTS",
    "DEFAULT_EVENT_CLUSTERS",
    "ACTION_FACTOR",
    "SALIENCE_FACTOR",
    "AFFECT_FACTOR",
    "EVENT_FACTOR",
    "GenerativeModel",
    "build_generative_model",
    "encode_snapshot",
    "register_event_cluster",
]

# pymdp 1.0 / equinox emits a benign "JAX array is being set as static" warning
# from the Agent constructor (its static `policies`/dependency fields). It is
# expected and harmless on CPU; engine.py suppresses it locally at the
# construction site rather than globally here.
_ = warnings  # referenced for the module docstring note above
