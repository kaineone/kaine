# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import copy
import math
from typing import Any, Optional, Protocol, runtime_checkable


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
    """Mean normalised entropy across a serialized Nous posterior.

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


class MnemosMergeStrategy:
    """Mnemos: sum short_term_size, tag retrieved memories on next read."""

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
        embed_a = state_a.get("embedder_model_id")
        embed_b = state_b.get("embedder_model_id")
        if embed_a == embed_b:
            out["embedder_model_id"] = embed_a
        else:
            out["embedder_model_id"] = embed_a or embed_b
            metadata["embedder_mismatch"] = True
        out["pending_source_tag"] = ["fork-a", "fork-b"]
        if metadata:
            out["metadata"] = metadata
        return out


class NousMergeStrategy:
    """Nous (active inference): one-sided selection by posterior certainty.

    Nous is now a pymdp/JAX active-inference engine — there is no NAR subprocess
    lifecycle, so the former ``restart_count`` / ``pending_revision`` fields are
    gone. Two forked Nous states can hold *different* posteriors over the same
    latent factors; merging probability distributions has no principled
    field-level union. Instead the strategy performs **one-sided selection**:
    keep the fork whose posterior is more *certain* (lower mean normalised
    entropy) and discard the other.

    If the discarded fork's mean posterior entropy differs from the kept fork's
    by more than ``warning_threshold``, a ``nous.merge_warning`` flag is set on
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
            out["nous.merge_warning"] = True
        return out


class EidolonMergeStrategy:
    """Eidolon: dedup values/norms, sum speech count, concatenate history."""

    def merge(self, state_a, state_b):
        one = _one_sided(state_a, state_b)
        if one is not None:
            return one
        out: dict[str, Any] = {}
        for field_name in ("values", "behavioral_norms"):
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


class ThymosMergeStrategy:
    """Thymos: average dimensional baseline, max drives, union goals."""

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


def default_strategies() -> dict[str, MergeStrategy]:
    """Map of module-name → strategy for KAINE's stock modules."""
    return {
        "mnemos": MnemosMergeStrategy(),
        "nous": NousMergeStrategy(),
        "eidolon": EidolonMergeStrategy(),
        "thymos": ThymosMergeStrategy(),
    }
