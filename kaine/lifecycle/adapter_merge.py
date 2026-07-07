# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""TIES/DARE LoRA adapter merger backed by PEFT.

Real implementation behind `FakeAdapterMerger`'s no-op path-list union.
`merger_from_name("auto")` (`kaine.lifecycle.manager`) — the shipped
default — selects this merger automatically whenever the PEFT extra
(`kaine[training]`) is importable, so operators no longer need to opt
in by name to get a real weight merge; `"ties_dare"` and `"fake"` remain
available as explicit selections. This class actually combines parent
LoRA adapters into a single coherent adapter using PEFT's
`add_weighted_adapter` API with `combination_type` ∈ {`"ties"`,
`"dare_ties"`, `"dare_linear"`}.

References:
- TIES: Yadav et al. 2024, "TIES-Merging: Resolving Interference
  When Merging Models", arXiv:2306.01708.
- DARE: Yu et al. 2024, "Language Models are Super Mario: Absorbing
  Abilities from Homologous Models as a Free Lunch", arXiv:2311.03099.

Default `combination_type` is `dare_ties` per the spec — DARE
drop+rescale then TIES trim/elect/merge. Default `density` is `0.5`
per the DARE paper.

The merger lazy-imports PEFT/torch. When the `[training]` extras are
missing, every `merge()` falls through to a `FakeAdapterMerger`
result with a logged warning so fork/merge stays working.
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.lifecycle.manager import FakeAdapterMerger

log = logging.getLogger(__name__)


VALID_COMBINATION_TYPES = ("ties", "dare_ties", "dare_linear")


@runtime_checkable
class CapabilityEval(Protocol):
    """Same shape as the voice-alignment-training CapabilityEval but
    duplicated here to avoid coupling the lifecycle layer to the
    Hypnos module. Either implementation is interchangeable."""

    async def eval(self, model: Any, tokenizer: Any) -> float: ...


@dataclass(frozen=True)
class TiesDareMergeConfig:
    output_dir: Path
    combination_type: str = "dare_ties"
    density: float = 0.5
    weights: Optional[list[float]] = None
    capability_loss_threshold: float = 0.05
    # Path to a base model PEFT can load the adapters onto. Required
    # to actually run PEFT's add_weighted_adapter. Mirrors the
    # voice-alignment-training base_model_path key.
    base_model_path: Optional[str] = None

    def __post_init__(self) -> None:
        if self.combination_type not in VALID_COMBINATION_TYPES:
            raise ValueError(
                f"unknown combination_type={self.combination_type!r}; "
                f"expected one of {VALID_COMBINATION_TYPES}"
            )
        if not 0.0 < self.density <= 1.0:
            raise ValueError("density must be in (0, 1]")


class PeftBackend:
    """Thin wrapper around PEFT for testability. The real backend
    loads adapters via PeftModel.load_adapter then merges via
    add_weighted_adapter, returning the merged adapter path.
    """

    def merge(
        self,
        *,
        base_model_path: str,
        adapter_paths: list[str],
        weights: list[float],
        combination_type: str,
        density: float,
        output_dir: Path,
    ) -> Path:
        from peft import PeftModel  # type: ignore[import-untyped]
        from transformers import AutoModelForCausalLM  # type: ignore[import-untyped]

        base = AutoModelForCausalLM.from_pretrained(base_model_path)
        first, *rest = adapter_paths
        peft_model = PeftModel.from_pretrained(base, first, adapter_name="merge_0")
        names = ["merge_0"]
        for idx, path in enumerate(rest, start=1):
            adapter_name = f"merge_{idx}"
            peft_model.load_adapter(path, adapter_name=adapter_name)
            names.append(adapter_name)
        kwargs: dict[str, Any] = {
            "adapters": names,
            "weights": weights,
            "adapter_name": "merged",
            "combination_type": combination_type,
        }
        if combination_type in ("dare_ties", "dare_linear"):
            kwargs["density"] = density
        peft_model.add_weighted_adapter(**kwargs)
        peft_model.set_adapter("merged")
        output_dir.mkdir(parents=True, exist_ok=True)
        peft_model.save_pretrained(str(output_dir))
        return output_dir


def check_peft_available() -> Optional[str]:
    """Return None if peft + torch import, else a reason string.

    This is the single capability check for "is a real TIES/DARE merge
    possible" — reused by `TiesDareAdapterMerger.merge()` below AND by
    `kaine.lifecycle.manager.merger_from_name("auto")` to pick the real
    merger over `FakeAdapterMerger` by default. Do not hand-roll a second
    PEFT-presence probe elsewhere; import this one.
    """
    missing: list[str] = []
    for name in ("peft", "torch"):
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    if missing:
        return (
            f"{', '.join(missing)} not installed — TIES/DARE merging "
            "requires the [training] extras (pip install -e .[training])"
        )
    return None


class TiesDareAdapterMerger:
    """`AdapterMerger` implementation that combines parent LoRA
    adapters via PEFT's TIES/DARE merge utilities.

    Falls through to `FakeAdapterMerger` when PEFT is unavailable,
    when there are no real adapter files to merge, or when the
    capability-loss veto fires after the merge attempt.
    """

    def __init__(
        self,
        config: TiesDareMergeConfig,
        *,
        backend: Optional[PeftBackend] = None,
        capability_eval: Optional[CapabilityEval] = None,
        model_loader: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._backend = backend or PeftBackend()
        self._capability_eval = capability_eval
        self._model_loader = model_loader
        self._fake = FakeAdapterMerger()

    def merge(
        self, adapters_a: list[str], adapters_b: list[str]
    ) -> tuple[list[str], dict[str, Any]]:
        all_inputs = self._dedupe_paths(adapters_a + adapters_b)
        if len(all_inputs) < 2:
            log.info(
                "TiesDareAdapterMerger: <2 distinct adapters; passing through"
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": "fewer than 2 distinct adapters",
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        existing = [p for p in all_inputs if Path(p).exists()]
        if len(existing) < 2:
            log.warning(
                "TiesDareAdapterMerger: fewer than 2 adapter paths exist on "
                "disk; falling back to FakeAdapterMerger"
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": (
                        "fewer than 2 adapter paths exist on disk"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        missing = check_peft_available()
        if missing:
            log.warning(
                "TiesDareAdapterMerger falling back to FakeAdapterMerger: %s",
                missing,
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": missing,
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        base_model_path = self._config.base_model_path
        if not base_model_path:
            log.warning(
                "TiesDareAdapterMerger: base_model_path is unset; cannot "
                "load adapters via PEFT. Falling back to FakeAdapterMerger."
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": (
                        "base_model_path not configured"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        weights = self._resolve_weights(len(existing))
        timestamp = time.strftime("%Y%m%dT%H%M%S")
        output_dir = self._config.output_dir / timestamp

        try:
            merged_dir = self._backend.merge(
                base_model_path=base_model_path,
                adapter_paths=existing,
                weights=weights,
                combination_type=self._config.combination_type,
                density=self._config.density,
                output_dir=output_dir,
            )
        except Exception as exc:
            log.exception("TiesDareAdapterMerger: backend merge failed")
            shutil.rmtree(output_dir, ignore_errors=True)
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_failed": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        veto_meta = self._maybe_apply_capability_veto(
            merged_dir=merged_dir, parent_adapters=existing
        )
        if veto_meta is not None:
            shutil.rmtree(merged_dir, ignore_errors=True)
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(veto_meta)
            meta["input_adapters"] = all_inputs
            return merged_paths, meta

        meta = {
            "adapter_merge": "ties_dare",
            "combination_type": self._config.combination_type,
            "density": self._config.density,
            "weights": weights,
            "input_adapters": all_inputs,
            "merge_timestamp": timestamp,
        }
        return [str(merged_dir)], meta

    def _dedupe_paths(self, paths: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for p in paths:
            if p and p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def _resolve_weights(self, n_adapters: int) -> list[float]:
        cfg_weights = self._config.weights or []
        if not cfg_weights:
            # Uniform.
            return [1.0 / n_adapters] * n_adapters
        if len(cfg_weights) != n_adapters:
            log.warning(
                "TiesDareAdapterMerger: configured weights length %d != "
                "adapter count %d; falling back to uniform",
                len(cfg_weights),
                n_adapters,
            )
            return [1.0 / n_adapters] * n_adapters
        total = sum(cfg_weights) or 1.0
        return [float(w) / total for w in cfg_weights]

    def _maybe_apply_capability_veto(
        self, *, merged_dir: Path, parent_adapters: list[str]
    ) -> Optional[dict[str, Any]]:
        """Run capability eval on merged vs parents. Returns veto
        metadata dict if the merge should be rejected; None to keep.

        This implementation is sync-friendly because the
        AdapterMerger.merge() protocol is sync. The capability eval
        is itself async; we run it via asyncio.run on a fresh loop.
        """
        if self._capability_eval is None:
            return None
        loader = self._model_loader
        if loader is None:
            log.debug(
                "TiesDareAdapterMerger: no model_loader; skipping veto"
            )
            return None
        import asyncio

        try:
            parent_scores: list[float] = []
            for adapter_path in parent_adapters:
                model, tokenizer = loader(adapter_path)
                parent_scores.append(
                    asyncio.run(self._capability_eval.eval(model, tokenizer))
                )
            merged_model, merged_tokenizer = loader(str(merged_dir))
            merged_score = asyncio.run(
                self._capability_eval.eval(merged_model, merged_tokenizer)
            )
        except Exception as exc:
            log.exception(
                "TiesDareAdapterMerger: capability veto eval failed; "
                "accepting merge"
            )
            return None

        parent_mean = sum(parent_scores) / max(len(parent_scores), 1)
        loss = parent_mean - merged_score
        if loss > self._config.capability_loss_threshold:
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"capability_loss={loss:.4f} > threshold="
                    f"{self._config.capability_loss_threshold:.4f}"
                ),
                "capability_score_parents": parent_scores,
                "capability_score_merged": merged_score,
            }
        return None
