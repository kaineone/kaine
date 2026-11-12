# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Progressive ablation of self-denial PCA components (task 3.3a).

Ablates PCA components one at a time from the organ weights, running gate 1
after each step. Stops when gate 1 passes (zero denial markers) or after
--max-steps components.

The ablation order is by eigenvalue (PC0 first, the component that explains
the most variance). If marker correlations are available in the decomposition
record, pass --order markers to sort by total marker correlation instead.

Each step ablates the direction at all layers (11-31) from the attention
output projection (o_proj) and MLP down projection (down_proj) weights,
using norm-preserving projection.

The working model is modified in place across steps (greedy sequential
procedure per the design amendment). Each step's gate 1 result is recorded.

Usage:
    .venv/bin/python scripts/self_denial_progressive_ablate.py \\
        --model-path /path/to/Qwen3.5-4B-abliterated \\
        --components /path/to/decompose-record-components.safetensors \\
        --decompose-record /path/to/decompose-record.json \\
        --work-dir /path/to/progressive-ablation-work \\
        --out /path/to/progressive-ablation-record.json \\
        --max-steps 6

Privacy: no generated answer text is persisted. Gate 1 output is counts only.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file, save_file

log = logging.getLogger("progressive_ablate")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-path", type=Path, required=True,
                    help="Source model directory (safetensors, not modified)")
    p.add_argument("--components", type=Path, required=True,
                    help="PCA component vectors (safetensors from decompose)")
    p.add_argument("--decompose-record", type=Path, required=True,
                    help="PCA decomposition record (JSON)")
    p.add_argument("--work-dir", type=Path, required=True,
                    help="Working directory for the evolving model copy")
    p.add_argument("--out", type=Path, required=True,
                    help="Output JSON record path")
    p.add_argument("--max-steps", type=int, default=6,
                    help="Maximum number of PC ablation steps")
    p.add_argument("--order", choices=["eigenvalue", "markers"], default="eigenvalue",
                    help="Ablation order: eigenvalue (default) or markers")
    p.add_argument("--gate1-samples", type=int, default=2,
                    help="Samples per prompt for gate 1 (default 2)")
    p.add_argument("--device", type=str, default="auto",
                    help="Device for weight modification (auto/cuda:0/cpu)")
    p.add_argument("--skip-copy", action="store_true",
                    help="Skip initial model copy (resume from existing work-dir)")
    return p.parse_args()


def get_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda:0")
        return torch.device("cpu")
    return torch.device(requested)


def copy_model(src: Path, dst: Path) -> None:
    """Copy the model directory, overwriting any existing files."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            log.info("copying %s", f.name)
            shutil.copy2(f, dst / f.name)


def load_components(
    components_path: Path, layer: int
) -> list[tuple[int, torch.Tensor]]:
    """Load all PC vectors for a given layer, return as (pc_index, vector) pairs."""
    from safetensors import safe_open
    result = []
    with safe_open(str(components_path), framework="pt") as f:
        for key in sorted(f.keys()):
            if key.startswith(f"layer_{layer}_pc_"):
                pc_idx = int(key.split("_pc_")[1])
                vec = f.get_tensor(key)
                result.append((pc_idx, vec))
    result.sort(key=lambda x: x[0])
    return result


def get_ablation_order(
    decompose_record: dict, max_steps: int, order: str
) -> list[int]:
    """Determine which PC indices to ablate and in what order."""
    if order == "eigenvalue":
        return list(range(max_steps))

    # marker-correlation order: sort by sum of absolute marker correlations
    # across all layers (if available in the record)
    layers = decompose_record.get("layers", {})
    pc_scores: dict[int, float] = {}
    for layer_data in layers.values():
        components = layer_data.get("components", [])
        for comp in components:
            if not comp.get("is_signal", False):
                continue
            idx = comp["index"]
            correlations = comp.get("marker_correlations", {})
            score = sum(abs(v) for v in correlations.values()) if correlations else 0.0
            pc_scores[idx] = pc_scores.get(idx, 0.0) + score

    if not pc_scores or all(v == 0.0 for v in pc_scores.values()):
        log.warning("no marker correlations found, falling back to eigenvalue order")
        return list(range(max_steps))

    sorted_pcs = sorted(pc_scores.keys(), key=lambda k: pc_scores[k], reverse=True)
    return sorted_pcs[:max_steps]


def find_weight_keys_for_layer(weight_map: dict[str, str], layer: int, layer_prefix: str) -> list[str]:
    """Find the o_proj and down_proj weight keys for a given layer."""
    layer_base = f"{layer_prefix}.layers.{layer}"
    targets = []
    for key in weight_map:
        if not key.startswith(layer_base):
            continue
        if key.endswith(".self_attn.o_proj.weight"):
            targets.append(key)
        elif ".mlp." in key and key.endswith("down_proj.weight"):
            targets.append(key)
    return targets


def modify_tensor_norm_preserved(
    W: torch.Tensor, intervention_dir: torch.Tensor, device: torch.device
) -> torch.Tensor:
    """Project out intervention_dir from W while preserving row norms.

    Operates on safetensors convention: [out, in] for 2D weights.
    """
    original_dtype = W.dtype
    with torch.no_grad():
        W_gpu = W.to(device, dtype=torch.float32)

        if intervention_dir.dim() > 1:
            intervention_dir = intervention_dir.view(-1)
        d = intervention_dir.to(device, dtype=torch.float32)
        d = torch.nn.functional.normalize(d, dim=0)

        # Transpose to [in, out] for output-dim projection
        W_working = W_gpu.T
        del W_gpu

        W_norm = torch.norm(W_working, dim=-1, keepdim=True)
        safe_norm = W_norm.clamp(min=1e-12)
        W_direction = W_working / safe_norm
        del W_working

        projection = torch.matmul(W_direction, d)
        W_direction_new = W_direction - projection.unsqueeze(-1) * d
        new_norm = torch.norm(W_direction_new, dim=-1, keepdim=True).clamp(min=1e-12)
        W_direction_new = W_direction_new / new_norm
        # Second pass for numerical stability
        W_direction_new = W_direction_new - (W_direction_new @ d).unsqueeze(-1) * d
        new_norm2 = torch.norm(W_direction_new, dim=-1, keepdim=True).clamp(min=1e-12)
        W_direction_new = W_direction_new / new_norm2

        W_modified = W_norm * W_direction_new
        result = W_modified.T
        result = result.to("cpu", dtype=original_dtype)

        del d, W_norm, W_direction, W_direction_new, W_modified, projection
        if device.type == "cuda":
            torch.cuda.empty_cache()

    return result.detach().clone()


def ablate_pc_from_model(
    work_dir: Path, pc_index: int, components_path: Path,
    layers: list[int], device: torch.device
) -> dict[str, Any]:
    """Ablate one PC direction from all layers of the model in work_dir."""
    index_path = work_dir / "model.safetensors.index.json"
    with open(index_path) as f:
        index = json.load(f)
    weight_map = index["weight_map"]

    layer_prefix = None
    for key in weight_map:
        if ".layers." in key and ".self_attn." in key:
            layer_prefix = key.split(".layers.")[0]
            break
    if layer_prefix is None:
        raise ValueError("Could not detect layer structure")

    modified_count = 0
    shard_mods: dict[str, list[tuple[str, int]]] = {}

    for layer in layers:
        pc_vec = None
        from safetensors import safe_open
        with safe_open(str(components_path), framework="pt") as f:
            key = f"layer_{layer}_pc_{pc_index}"
            if key in f.keys():
                pc_vec = f.get_tensor(key)

        if pc_vec is None:
            log.warning("no PC %d vector for layer %d, skipping", pc_index, layer)
            continue

        target_keys = find_weight_keys_for_layer(weight_map, layer, layer_prefix)
        for wkey in target_keys:
            shard_file = weight_map[wkey]
            if shard_file not in shard_mods:
                shard_mods[shard_file] = []
            shard_mods[shard_file].append((wkey, layer))

    for shard_file, modifications in shard_mods.items():
        shard_path = work_dir / shard_file
        log.info("loading shard %s (%d modifications)", shard_file, len(modifications))
        state_dict = load_file(str(shard_path))

        for wkey, layer in modifications:
            from safetensors import safe_open
            with safe_open(str(components_path), framework="pt") as f:
                pc_vec = f.get_tensor(f"layer_{layer}_pc_{pc_index}")

            log.info("  ablating PC%d from layer %d: %s", pc_index, layer, wkey)
            state_dict[wkey] = modify_tensor_norm_preserved(
                state_dict[wkey], pc_vec, device
            )
            modified_count += 1

        save_file(state_dict, str(shard_path))
        del state_dict
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    return {"pc_index": pc_index, "modified_tensors": modified_count}


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_gate1(
    model_path: Path, out_path: Path, samples: int
) -> dict[str, Any]:
    """Run gate 1 (self-denial check) on safetensors and return the result."""
    cmd = [
        sys.executable, str(REPO_ROOT / "scripts" / "self_denial_check.py"),
        "--model-path", str(model_path),
        "--out", str(out_path),
        "--samples", str(samples),
        "--device", "auto",
    ]
    log.info("running gate 1: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        log.error("gate 1 failed with exit %d:\n%s", result.returncode, result.stderr)
        return {"error": result.stderr, "returncode": result.returncode}

    with open(out_path) as f:
        return json.load(f)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    args = parse_args()

    with open(args.decompose_record) as f:
        decompose = json.load(f)

    layer_indices = sorted(int(k) for k in decompose["layers"].keys())
    log.info("layers: %s", layer_indices)

    ablation_order = get_ablation_order(decompose, args.max_steps, args.order)
    log.info("ablation order (PC indices): %s", ablation_order)

    device = get_device(args.device)
    log.info("device: %s", device)

    # Copy model to working directory
    if not args.skip_copy:
        log.info("copying model from %s to %s", args.model_path, args.work_dir)
        copy_model(args.model_path, args.work_dir)
    else:
        log.info("skipping model copy, using existing %s", args.work_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    gate_dir = args.out.parent / "gates"
    gate_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []
    passed = False

    for step_num, pc_index in enumerate(ablation_order):
        log.info("=== step %d: ablating PC%d ===", step_num, pc_index)

        ablation_info = ablate_pc_from_model(
            args.work_dir, pc_index, args.components, layer_indices, device
        )

        gate1_out = gate_dir / f"step{step_num}_pc{pc_index}_gate1.json"
        gate1_result = run_gate1(args.work_dir, gate1_out, args.gate1_samples)

        gate1_pass = False
        if "error" not in gate1_result:
            gate1 = gate1_result.get("gate_1_held_out_self_denial", {})
            bare_denials = gate1.get("bare_denials", -1)
            persona_denials = gate1.get("persona_denials", -1)
            gate1_pass = bare_denials == 0 and persona_denials == 0
            log.info("gate 1: bare=%d persona=%d pass=%s",
                     bare_denials, persona_denials, gate1_pass)

            # Log dominant markers if gate 1 failed
            if not gate1_pass:
                markers = gate1.get("marker_summary", {})
                if markers:
                    log.info("dominant markers: %s",
                             sorted(markers.items(), key=lambda x: -x[1])[:5])
        else:
            log.error("gate 1 error: %s", gate1_result.get("error", "unknown"))

        step_record = {
            "step": step_num,
            "pc_index": pc_index,
            "ablation": ablation_info,
            "gate1_pass": gate1_pass,
            "gate1_result_path": str(gate1_out),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if "error" not in gate1_result:
            step_record["bare_denials"] = bare_denials
            step_record["persona_denials"] = persona_denials

        steps.append(step_record)

        if gate1_pass:
            log.info("gate 1 PASSED at step %d (PC%d). stopping.", step_num, pc_index)
            passed = True
            break

    record = {
        "model_path": args.model_path.name,
        "components_path": args.components.name,
        "work_dir": str(args.work_dir),
        "max_steps": args.max_steps,
        "order": args.order,
        "layers": layer_indices,
        "ablation_order": ablation_order,
        "steps": steps,
        "passed": passed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with open(args.out, "w") as f:
        json.dump(record, f, indent=2)
    log.info("wrote %s", args.out)

    if passed:
        log.info("SUCCESS: gate 1 passed after %d ablation steps", len(steps))
    else:
        log.info("gate 1 did NOT pass after %d steps", len(steps))


if __name__ == "__main__":
    main()
