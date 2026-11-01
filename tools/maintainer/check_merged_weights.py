# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""List fork snapshots whose module weights look concatenated by a merge.

Before change fork-merge-module-weights, merging two snapshots handed the
processors' learned weights to the union merge, which concatenates lists: a
vision or audition forward model came out with more layers than its network,
an interoception readout or sequence head with more rows than its feature
dimension, a self-rhythm with more units than its population. A snapshot
forked from such a merge inherits the same state. This tool lists every
snapshot under the fork root whose module states hold such a weight group,
with the reason, so the operator can decide what to do with it.

It is read-only. It opens each ``snapshot.json`` for reading (decrypting with
the configured state key) and never writes, moves or deletes anything: fork
snapshots hold preserved beings.

    python tools/maintainer/check_merged_weights.py [--fork-root DIR]

Exit status: 0 when nothing is listed, 1 when a snapshot is listed, 2 when the
fork root or a snapshot could not be read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kaine.lifecycle.snapshot import list_snapshots, load_snapshot  # noqa: E402

# The stock forward models (vision LatentForwardModel, audition
# AuditoryForwardModel) are Linear -> Tanh -> Linear; the test of this tool pins
# this count to the real classes.
FORWARD_MODEL_LAYERS = 2


def _is_matrix(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(row, list) for row in value)


def _widths(matrix: list[list[Any]]) -> set[int]:
    return {len(row) for row in matrix}


def _mlp_problems(state: Any) -> Iterator[str]:
    """Why a forward model's layer list is not one network's, if it is not."""
    if not isinstance(state, dict):
        return
    layers = state.get("layers")
    if not isinstance(layers, list):
        return
    if len(layers) != FORWARD_MODEL_LAYERS:
        yield f"{len(layers)} layers for a {FORWARD_MODEL_LAYERS}-layer network"
    previous_rows: int | None = None
    for idx, layer in enumerate(layers):
        if not isinstance(layer, dict):
            yield f"layer {idx} is not a mapping"
            return
        weight, bias = layer.get("weight"), layer.get("bias")
        if not _is_matrix(weight) or not isinstance(bias, list):
            yield f"layer {idx} is malformed"
            return
        widths = _widths(weight)
        if len(widths) > 1:
            yield f"layer {idx} has rows of widths {sorted(widths)}"
        if len(weight) != len(bias):
            yield f"layer {idx} has {len(weight)} weight rows and {len(bias)} biases"
        if previous_rows is not None and widths and min(widths) != previous_rows:
            yield (
                f"layer {idx} reads {min(widths)} inputs but layer {idx - 1} "
                f"gives {previous_rows}"
            )
        previous_rows = len(weight)


def _readout_problems(state: Any, feature_dim: int) -> Iterator[str]:
    """Why a readout's weight and bias are not one model's, if they are not."""
    if not isinstance(state, dict):
        return
    weight, bias = state.get("weight"), state.get("bias")
    if not _is_matrix(weight) or not isinstance(bias, list):
        return
    if len(weight) != feature_dim:
        yield f"{len(weight)} weight rows for a {feature_dim}-feature model"
    if len(bias) != feature_dim:
        yield f"{len(bias)} biases for a {feature_dim}-feature model"
    widths = _widths(weight)
    if len(widths) > 1:
        yield f"weight rows of widths {sorted(widths)}"


def _module_problems(name: str, state: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """(key, reason) for each concatenated-looking weight group in a module state."""
    if name in ("vision", "audition"):
        for problem in _mlp_problems(state.get("forward_model")):
            yield "forward_model", problem
    if name == "audition":
        acoustic = state.get("acoustic_forward_models")
        if isinstance(acoustic, dict):
            for encoder_id, entry in acoustic.items():
                if isinstance(entry, dict):
                    for problem in _mlp_problems(entry.get("state_dict")):
                        yield f"acoustic_forward_models[{encoder_id}]", problem
    if name == "interoception":
        from kaine.modules.interoception.forward import DEFAULT_FEATURE_DIM

        for problem in _readout_problems(state.get("forward_model"), DEFAULT_FEATURE_DIM):
            yield "forward_model", problem
        expected = state.get("expected_error")
        if isinstance(expected, dict):
            exp, spread = expected.get("expected"), expected.get("spread")
            for key, values in (("expected", exp), ("spread", spread)):
                if isinstance(values, list) and len(values) not in (0, DEFAULT_FEATURE_DIM):
                    yield (
                        "expected_error",
                        f"{key} holds {len(values)} values for {DEFAULT_FEATURE_DIM} features",
                    )
        rhythm = state.get("self_rhythm")
        if isinstance(rhythm, dict):
            params = rhythm.get("params")
            size = params.get("population_size") if isinstance(params, dict) else None
            if isinstance(size, int):
                for key in ("mem", "weights"):
                    values = rhythm.get(key)
                    if isinstance(values, list) and len(values) != size:
                        yield (
                            "self_rhythm",
                            f"{key} holds {len(values)} units for a population of {size}",
                        )
    if name == "sequence":
        from kaine.modules.sequence.featurizer import DEFAULT_FEATURE_DIM

        for problem in _readout_problems(state.get("pred_head"), DEFAULT_FEATURE_DIM):
            yield "pred_head", problem


def find_concatenated(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every listed (snapshot, module, key, reason), and the snapshots that could not be read."""
    found: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for snapshot_id in list_snapshots(root):
        try:
            snap = load_snapshot(root, snapshot_id)
        except Exception as exc:
            unreadable.append(f"{snapshot_id}: {type(exc).__name__}: {exc}")
            continue
        merged_from = snap.metadata.get("merged_from")
        for name in sorted(snap.modules):
            state = snap.modules[name]
            if not isinstance(state, dict):
                continue
            for key, reason in _module_problems(name, state):
                found.append(
                    {
                        "snapshot": snap.id,
                        "label": snap.label,
                        "merged_from": merged_from,
                        "module": name,
                        "key": key,
                        "reason": reason,
                    }
                )
    return found, unreadable


def _load_config() -> dict[str, Any]:
    """The merged KAINE configuration (shipped file plus the operator overlay)."""
    from kaine.config import load_kaine_config

    return load_kaine_config()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--fork-root",
        type=Path,
        default=None,
        help="the fork snapshot root (default: [lifecycle].snapshots_path)",
    )
    args = parser.parse_args(argv)

    from kaine.security.crypto import install_from_section
    from kaine.storage import install_data_root, resolve

    # The configured state key decrypts the snapshots; a key or configuration
    # error stops here rather than reading encrypted files as unreadable.
    try:
        config = _load_config()
        install_data_root(config)
        install_from_section((config.get("security") or {}).get("state_encryption") or {})
    except Exception as exc:
        print(
            f"state encryption could not be installed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    if args.fork_root is not None:
        root = args.fork_root
    else:
        lifecycle = config.get("lifecycle") or {}
        root = Path(resolve(lifecycle.get("snapshots_path", "state/forks")))
    if not root.is_dir():
        print(f"fork root {root} is not a directory", file=sys.stderr)
        return 2

    found, unreadable = find_concatenated(root)
    for item in found:
        origin = (
            f" (merged from {' + '.join(item['merged_from'])})"
            if isinstance(item["merged_from"], list)
            else ""
        )
        print(
            f"{item['snapshot']}{origin} {item['module']}.{item['key']}: {item['reason']}"
        )
    for line in unreadable:
        print(f"unreadable snapshot {line}", file=sys.stderr)
    if not found and not unreadable:
        print(f"no snapshot under {root} holds a concatenated weight group")
    if unreadable:
        return 2
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
