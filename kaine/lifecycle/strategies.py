# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import math
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.embedding_defaults import LEGACY_EMBEDDING_SPACE
from kaine.text_embedding import same_space


def _normalised_entropy(dist: Any) -> float:
    """Shannon entropy of a discrete distribution normalised to [0, 1].

    Point mass → 0.0; uniform → 1.0. Robust to unnormalised / degenerate input.
    """
    try:
        values = [float(x) for x in dist]
    except (TypeError, ValueError):
        return 1.0
    n = len(values)
    if n <= 1:
        return 0.0
    total = sum(values)
    if total <= 0.0:
        return 1.0
    ent = 0.0
    for v in values:
        q = v / total
        if q > 0.0:
            ent -= q * math.log(q)
    return ent / math.log(n)


def _mean_posterior_entropy(state: dict[str, Any]) -> float:
    """Mean normalised entropy across a serialized planning module posterior.

    The posterior is a list (per hidden-state factor) of probability vectors.
    A missing/empty posterior is treated as maximally uncertain (1.0) so a fork
    that actually computed beliefs always wins over one that did not.
    """
    posterior = state.get("posterior")
    if not isinstance(posterior, list) or not posterior:
        return 1.0
    entropies = [_normalised_entropy(factor) for factor in posterior if factor]
    if not entropies:
        return 1.0
    return sum(entropies) / len(entropies)


@runtime_checkable
class MergeStrategy(Protocol):
    """Merge two parent module states into one.

    Either parent may be None when a module exists in only one parent.
    Implementations MUST handle (None, b) and (a, None) gracefully and
    SHOULD source-tag entries so downstream consumers can tell which
    parent contributed which data.
    """

    def merge(
        self,
        state_a: Optional[dict[str, Any]],
        state_b: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


class UnionMergeStrategy:
    """Default last-write-wins union for scalar keys, recursive for dicts.

    Used for any module without a specialized strategy. Documented
    semantics: keys present in both sides take b's value; nested dicts
    are merged recursively; lists are concatenated then deduplicated by
    preserving first occurrence.
    """

    def merge(
        self,
        state_a: Optional[dict[str, Any]],
        state_b: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        if state_a is None and state_b is None:
            return {}
        if state_a is None:
            return copy.deepcopy(state_b or {})
        if state_b is None:
            return copy.deepcopy(state_a or {})
        out = copy.deepcopy(state_a)
        for key, val_b in state_b.items():
            if key in out and isinstance(out[key], dict) and isinstance(val_b, dict):
                out[key] = UnionMergeStrategy().merge(out[key], val_b)
            elif key in out and isinstance(out[key], list) and isinstance(val_b, list):
                merged: list[Any] = list(out[key])
                seen = {repr(item) for item in merged}
                for item in val_b:
                    if repr(item) not in seen:
                        merged.append(item)
                        seen.add(repr(item))
                out[key] = merged
            else:
                out[key] = copy.deepcopy(val_b)
        return out


def _one_sided(state_a, state_b) -> Optional[dict[str, Any]]:
    if state_a is None and state_b is None:
        return {}
    if state_a is None:
        return copy.deepcopy(state_b or {})
    if state_b is None:
        return copy.deepcopy(state_a or {})
    return None


class EpisodicMemoryMergeStrategy:
    """The episodic memory module: sum short_term_size, tag retrieved memories on next read."""

    def merge(self, state_a, state_b):
        one = _one_sided(state_a, state_b)
        if one is not None:
            return one
        out: dict[str, Any] = {}
        out["short_term_size"] = int(state_a.get("short_term_size", 0)) + int(
            state_b.get("short_term_size", 0)
        )
        prefix_a = state_a.get("collection_prefix")
        prefix_b = state_b.get("collection_prefix")
        metadata: dict[str, Any] = {}
        if prefix_a == prefix_b:
            out["collection_prefix"] = prefix_a
        else:
            out["collection_prefix"] = prefix_a or prefix_b
            metadata["prefix_mismatch"] = True
            metadata["parent_prefixes"] = [prefix_a, prefix_b]
        embed_a = state_a.get("embedding_space")
        embed_b = state_b.get("embedding_space")
        defaulted_a = embed_a if embed_a is not None else LEGACY_EMBEDDING_SPACE
        defaulted_b = embed_b if embed_b is not None else LEGACY_EMBEDDING_SPACE
        out["embedding_space"] = defaulted_a
        if not same_space(defaulted_a, defaulted_b):
            metadata["embedding_space_mismatch"] = True
        out["pending_source_tag"] = ["fork-a", "fork-b"]
        if metadata:
            out["metadata"] = metadata
        return out


class PlanningMergeStrategy:
    """The planning module (active inference): one-sided selection by posterior certainty.

    The planning module is now a pymdp/JAX active-inference engine — there is no NAR subprocess
    lifecycle, so the former ``restart_count`` / ``pending_revision`` fields are
    gone. Two forked planning module states can hold *different* posteriors over the same
    latent factors; merging probability distributions has no principled
    field-level union. Instead the strategy performs **one-sided selection**:
    keep the fork whose posterior is more *certain* (lower mean normalised
    entropy) and discard the other.

    If the discarded fork's mean posterior entropy differs from the kept fork's
    by more than ``warning_threshold``, a ``planning.merge_warning`` flag is set on
    the result so the operator/sidecar can review a contentious merge (the two
    forks reached substantially different confidence).
    """

    def __init__(self, warning_threshold: float = 0.2) -> None:
        if not 0.0 <= warning_threshold <= 1.0:
            raise ValueError("warning_threshold must be in [0, 1]")
        self._warning_threshold = float(warning_threshold)

    def merge(self, state_a, state_b):
        one = _one_sided(state_a, state_b)
        if one is not None:
            return one
        if "posterior" not in state_a and "posterior" not in state_b:
            # ForkManager.merge takes the posterior with the learned prior it
            # was inferred under (planning's weight group) and hands this
            # strategy only the rest; there is no certainty to compare.
            return copy.deepcopy(state_a)
        ent_a = _mean_posterior_entropy(state_a)
        ent_b = _mean_posterior_entropy(state_b)
        # Lower entropy (more certain) wins; tie → keep A (deterministic).
        if ent_b < ent_a:
            kept, kept_ent, discarded_ent = state_b, ent_b, ent_a
        else:
            kept, kept_ent, discarded_ent = state_a, ent_a, ent_b
        out = copy.deepcopy(kept)
        out["selected_fork_entropy"] = kept_ent
        out["discarded_fork_entropy"] = discarded_ent
        if abs(discarded_ent - kept_ent) > self._warning_threshold:
            out["planning.merge_warning"] = True
        return out


class SelfModelMergeStrategy:
    """The self-model module: dedup values/norms, sum speech count, concatenate history."""

    def merge(self, state_a, state_b):
        one = _one_sided(state_a, state_b)
        if one is not None:
            return one
        out: dict[str, Any] = {}
        for field_name in ("values", "behavioral_norms", "situation_facts"):
            merged: list[Any] = []
            seen: set[str] = set()
            for src in (state_a.get(field_name) or [], state_b.get(field_name) or []):
                for item in src:
                    key = repr(item)
                    if key not in seen:
                        merged.append(item)
                        seen.add(key)
            out[field_name] = merged
        out["internal_speech_count"] = int(state_a.get("internal_speech_count", 0)) + int(
            state_b.get("internal_speech_count", 0)
        )
        history_a = [{"source": "fork-a", **dict(h)} for h in state_a.get("identity_history") or []]
        history_b = [{"source": "fork-b", **dict(h)} for h in state_b.get("identity_history") or []]
        out["identity_history"] = history_a + history_b
        baseline_a = state_a.get("personality_baseline")
        baseline_b = state_b.get("personality_baseline")
        if isinstance(baseline_a, dict) and isinstance(baseline_b, dict):
            avg: dict[str, float] = {}
            for key in set(baseline_a) | set(baseline_b):
                a_val = float(baseline_a.get(key, 0.0))
                b_val = float(baseline_b.get(key, 0.0))
                avg[key] = (a_val + b_val) / 2.0
            out["personality_baseline"] = avg
        elif baseline_a is not None:
            out["personality_baseline"] = baseline_a
        elif baseline_b is not None:
            out["personality_baseline"] = baseline_b
        drift_a = int(state_a.get("drift_count", 0))
        drift_b = int(state_b.get("drift_count", 0))
        out["drift_count"] = drift_a + drift_b
        return out


class AffectMergeStrategy:
    """The affect module: average dimensional baseline, max drives, union goals."""

    def merge(self, state_a, state_b):
        one = _one_sided(state_a, state_b)
        if one is not None:
            return one
        out: dict[str, Any] = {}
        dim_a = state_a.get("dimensional") or {}
        dim_b = state_b.get("dimensional") or {}
        avg_dim: dict[str, float] = {}
        for key in set(dim_a) | set(dim_b):
            a_val = float(dim_a.get(key, 0.0))
            b_val = float(dim_b.get(key, 0.0))
            avg_dim[key] = (a_val + b_val) / 2.0
        out["dimensional"] = avg_dim
        drives_a = state_a.get("drives") or {}
        drives_b = state_b.get("drives") or {}
        max_drives: dict[str, float] = {}
        for key in set(drives_a) | set(drives_b):
            max_drives[key] = max(
                float(drives_a.get(key, 0.0)), float(drives_b.get(key, 0.0))
            )
        out["drives"] = max_drives
        goals_a = state_a.get("goals") or []
        goals_b = state_b.get("goals") or []
        seen: set[str] = set()
        merged_goals: list[Any] = []
        for src_label, src in (("fork-a", goals_a), ("fork-b", goals_b)):
            for g in src:
                key = repr(g.get("id") if isinstance(g, dict) else g)
                if key in seen:
                    continue
                seen.add(key)
                if isinstance(g, dict):
                    merged_goals.append({"source": src_label, **g})
                else:
                    merged_goals.append({"source": src_label, "value": g})
        out["goals"] = merged_goals
        history_a = list(state_a.get("emotional_history") or [])
        history_b = list(state_b.get("emotional_history") or [])
        out["emotional_history"] = [
            {"source": "fork-a", **h} if isinstance(h, dict) else {"source": "fork-a", "value": h}
            for h in history_a
        ] + [
            {"source": "fork-b", **h} if isinstance(h, dict) else {"source": "fork-b", "value": h}
            for h in history_b
        ]
        return out


class SocialCognitionMergeStrategy:
    """Reconcile two diverged AgentStore snapshots.

    Semantics
    ---------
    - interaction_count: SUM — both branches saw real interactions.
    - emotion_histogram: weighted average by interaction count — each
      branch's histogram is weighted by how many observations it made.
    - behavioral_summary: weighted average by interaction count. A missing
      or null entry on one side is absent, and the merged value then comes
      from the side that has one.
    - reliability: weighted average by interaction count.
    - first_seen: min (earliest observation).
    - last_seen: max (most recent observation).

    The merged profiles travel in the merged snapshot; restoring it loads
    them into the social cognition module's store.
    """

    def merge(
        self,
        state_a: dict[str, Any] | None,
        state_b: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if state_a is None and state_b is None:
            return {}
        if state_a is None:
            return dict(state_b or {})
        if state_b is None:
            return dict(state_a or {})

        profiles_a: dict[str, Any] = state_a.get("profiles", {})
        profiles_b: dict[str, Any] = state_b.get("profiles", {})
        all_ids = set(profiles_a) | set(profiles_b)

        merged_profiles: dict[str, Any] = {}
        for agent_id in all_ids:
            pa = profiles_a.get(agent_id)
            pb = profiles_b.get(agent_id)
            if pa is None:
                merged_profiles[agent_id] = dict(pb)
            elif pb is None:
                merged_profiles[agent_id] = dict(pa)
            else:
                merged_profiles[agent_id] = _merge_profiles(pa, pb)

        return {"profiles": merged_profiles}


def _merge_summary(
    summary_a: dict[str, Any],
    summary_b: dict[str, Any],
    count_a: int,
    count_b: int,
) -> dict[str, Any]:
    """Merge behavioral_summary dicts by interaction count weights.

    A missing or null entry on one side is treated as absent, so the
    merged value comes from the side that has one. When all contributing
    sides have an interaction count of zero, the plain mean of their
    values is used.
    """
    all_keys = set(summary_a) | set(summary_b)
    merged: dict[str, Any] = {}

    for key in all_keys:
        a_has = key in summary_a and summary_a[key] is not None
        b_has = key in summary_b and summary_b[key] is not None
        values = []
        counts = []

        if a_has:
            values.append(float(summary_a[key]))
            counts.append(count_a)
        if b_has:
            values.append(float(summary_b[key]))
            counts.append(count_b)

        if not values:
            continue

        total = sum(counts)
        if total == 0:
            merged[key] = sum(values) / len(values)
        else:
            merged[key] = sum(
                (count / total) * value for count, value in zip(counts, values)
            )

    return merged


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors; 0.0 if either has zero norm."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _merge_exemplars(
    exemplars_a: list[dict[str, Any]] | None,
    exemplars_b: list[dict[str, Any]] | None,
    centroid: list[float] | None,
    max_size: int = 20,
) -> list[dict[str, Any]]:
    """Union two exemplar lists, dedupe near-duplicates, cap at max_size.

    Near-duplicates (cosine > 0.99) keep the later timestamp. When over
    the cap, exemplars most similar to the centroid are evicted first.
    """
    merged: list[dict[str, Any]] = []
    for ex in list(exemplars_a or []) + list(exemplars_b or []):
        emb = ex.get("embedding")
        if not emb:
            continue
        ts = ex.get("timestamp")
        ts_val = float(ts) if ts is not None else float("-inf")
        for i, kept in enumerate(merged):
            if _cosine_similarity(emb, kept["embedding"]) > 0.99:
                kts = kept.get("timestamp")
                kts_val = float(kts) if kts is not None else float("-inf")
                if ts_val > kts_val:
                    merged[i] = dict(ex)
                break
        else:
            merged.append(dict(ex))

    if len(merged) > max_size:
        if centroid:
            merged.sort(
                key=lambda e: _cosine_similarity(e["embedding"], centroid)
            )
            # Least similar to the centroid first; keep the most diverse.
        merged = merged[:max_size]
    return merged


def _merge_centroid(
    ca: list[float] | None,
    cb: list[float] | None,
    na: int,
    nb: int,
) -> list[float] | None:
    """Sample-count weighted centroid average, re-normalized to unit length."""
    if not ca and not cb:
        return None
    if not ca or not cb or len(ca) != len(cb):
        src = ca if ca else cb
        return list(src) if src else None
    wa, wb = (na, nb) if (na + nb) > 0 else (1, 1)
    mixed = [(wa * x + wb * y) / (wa + wb) for x, y in zip(ca, cb)]
    norm = sum(v * v for v in mixed) ** 0.5
    if norm == 0.0:
        return mixed
    return [v / norm for v in mixed]


def _merge_opt_reliability(
    ra: float | None, rb: float | None, na: int, nb: int
) -> float | None:
    if ra is None:
        return rb
    if rb is None:
        return ra
    if na + nb == 0:
        return (ra + rb) / 2
    return (na * ra + nb * rb) / (na + nb)


_BINDING_RANK = {"unbound": 0, "voice_only": 1, "face_only": 1, "bound": 2}


def _merge_identity_fields(
    pa: dict[str, Any], pb: dict[str, Any]
) -> dict[str, Any]:
    """Merge identity-binding fields; tolerant of absent keys (old profiles)."""
    vna = int(pa.get("voice_sample_count") or 0)
    vnb = int(pb.get("voice_sample_count") or 0)
    fna = int(pa.get("face_sample_count") or 0)
    fnb = int(pb.get("face_sample_count") or 0)

    voice_centroid = _merge_centroid(
        pa.get("voice_centroid"), pb.get("voice_centroid"), vna, vnb
    )
    face_centroid = _merge_centroid(
        pa.get("face_centroid"), pb.get("face_centroid"), fna, fnb
    )

    ca = pa.get("binding_confidence")
    cb = pb.get("binding_confidence")
    conf_a = float(ca) if ca is not None else 0.0
    conf_b = float(cb) if cb is not None else 0.0
    state_a = str(pa.get("binding_state") or "unbound")
    state_b = str(pb.get("binding_state") or "unbound")
    rank_a = _BINDING_RANK.get(state_a, 0)
    rank_b = _BINDING_RANK.get(state_b, 0)
    if rank_a != rank_b:
        binding_state = state_a if rank_a > rank_b else state_b
    else:
        binding_state = state_a if conf_a >= conf_b else state_b

    if ca is None and cb is None:
        binding_confidence = None
    else:
        binding_confidence = max(conf_a, conf_b)

    acoustic_src = pa if vna >= vnb else pb
    acoustic = acoustic_src.get("voice_acoustic_embedding")
    if acoustic is None:
        acoustic = (pb if acoustic_src is pa else pa).get(
            "voice_acoustic_embedding"
        )

    return {
        "voice_centroid": voice_centroid,
        "face_centroid": face_centroid,
        "voice_exemplars": _merge_exemplars(
            pa.get("voice_exemplars"), pb.get("voice_exemplars"), voice_centroid
        ),
        "face_exemplars": _merge_exemplars(
            pa.get("face_exemplars"), pb.get("face_exemplars"), face_centroid
        ),
        "voice_sample_count": vna + vnb,
        "face_sample_count": fna + fnb,
        "binding_state": binding_state,
        "binding_confidence": binding_confidence,
        "voice_reliability": _merge_opt_reliability(
            pa.get("voice_reliability"), pb.get("voice_reliability"), vna, vnb
        ),
        "face_reliability": _merge_opt_reliability(
            pa.get("face_reliability"), pb.get("face_reliability"), fna, fnb
        ),
        "voice_acoustic_embedding": acoustic,
    }


def _merge_profiles(
    pa: dict[str, Any], pb: dict[str, Any]
) -> dict[str, Any]:
    """Merge two AgentModel dicts by weighted average."""
    count_a = int(pa.get("interaction_count", 0))
    count_b = int(pb.get("interaction_count", 0))
    total = count_a + count_b

    if total == 0:
        # No observations on either side — take pa as base.
        result = dict(pa)
        result.update(_merge_identity_fields(pa, pb))
        return result

    w_a = count_a / total
    w_b = count_b / total

    # Merge emotion histogram (weighted average).
    hist_a = pa.get("emotion_histogram") or {}
    hist_b = pb.get("emotion_histogram") or {}
    all_cats = set(hist_a) | set(hist_b)
    merged_hist = {
        cat: w_a * float(hist_a.get(cat, 0.0)) + w_b * float(hist_b.get(cat, 0.0))
        for cat in all_cats
    }

    # Merge behavioral_summary.
    bsummary_a = pa.get("behavioral_summary") or {}
    bsummary_b = pb.get("behavioral_summary") or {}
    merged_bsummary = _merge_summary(bsummary_a, bsummary_b, count_a, count_b)

    # Reliability: weighted average.
    reliability = (
        w_a * float(pa.get("reliability", 1.0))
        + w_b * float(pb.get("reliability", 1.0))
    )

    identity_fields = _merge_identity_fields(pa, pb)

    return {
        **identity_fields,
        "id": pa.get("id") or pb.get("id"),
        "label": pa.get("label") or pb.get("label"),
        "emotion_histogram": merged_hist,
        "behavioral_summary": merged_bsummary,
        "reliability": reliability,
        "interaction_count": total,
        "first_seen": min(
            float(pa.get("first_seen", 0.0)), float(pb.get("first_seen", 0.0))
        ),
        "last_seen": max(
            float(pa.get("last_seen", 0.0)), float(pb.get("last_seen", 0.0))
        ),
    }


# The keys of a module's serialized state that hold learned parameters, with
# the seeds, layouts and encoder ids those parameters were trained against.
# ForkManager.merge takes each group whole from one parent (equal, one-sided, or
# the operator's ``module_weights_from`` choice) and never hands its keys to the
# module's strategy, so a weight list is never concatenated or split from the
# reservoir it was trained on. Data, not module methods, so a merge in a process
# with no live modules (the dashboard) declares the same groups.
#
# vision        forward_model: LatentForwardModel layers; encoder_model_id:
#               the encoder whose latents those layers predict.
# audition      forward_model: the utterance AuditoryForwardModel layers;
#               forward_model_features: the feature layout they were trained
#               on; acoustic_forward_models: per-encoder acoustic models.
# interoception forward_model: the readout over the CfC reservoir that
#               reservoir_seed rebuilds; feature_layout: the metric layout the
#               readout predicts; expected_error: the running statistics of
#               that readout's errors; self_rhythm: the self-rhythm
#               oscillator's plastic time constant with the population arrays
#               and RNG state it evolved with.
# sequence      pred_head: the prediction head over the reservoir that
#               reservoir_seed rebuilds; featurizer_layout: the input layout
#               both were trained on.
# planning      learned: the learned transition prior (pB) and the belief
#               carried with it; posterior and last_action: the belief and the
#               action inferred under that prior.
#
# The inventory is pinned by tests/test_fork_merge_module_weights.py, which also
# fails when a stock module serializes a weight-like list outside its group.
MODULE_WEIGHT_GROUPS: dict[str, tuple[str, ...]] = {
    "vision": ("forward_model", "encoder_model_id"),
    "audition": ("forward_model", "forward_model_features", "acoustic_forward_models"),
    "interoception": (
        "forward_model",
        "reservoir_seed",
        "feature_layout",
        "expected_error",
        "self_rhythm",
    ),
    "sequence": ("pred_head", "reservoir_seed", "featurizer_layout"),
    "planning": ("learned", "posterior", "last_action"),
}

# The keys of each weight group that hold the learned parameters themselves; the
# group's other keys are the bindings (seeds, layouts, encoder ids) those
# parameters were trained against. A parent whose group holds bindings only (for
# example vision with forward prediction switched off) has no learned weights to
# offer: when its bindings agree with the other parent's, the other parent's
# group is copied as one-sided.
MODULE_WEIGHT_PARAMETERS: dict[str, tuple[str, ...]] = {
    "vision": ("forward_model",),
    "audition": ("forward_model", "acoustic_forward_models"),
    "interoception": ("forward_model", "expected_error", "self_rhythm"),
    "sequence": ("pred_head",),
    "planning": ("learned", "posterior", "last_action"),
}


def default_strategies() -> dict[str, MergeStrategy]:
    """Map of module-name → strategy for KAINE's stock modules."""
    return {
        "episodic_memory": EpisodicMemoryMergeStrategy(),
        "planning": PlanningMergeStrategy(),
        "self_model": SelfModelMergeStrategy(),
        "affect": AffectMergeStrategy(),
        "social_cognition": SocialCognitionMergeStrategy(),
    }
