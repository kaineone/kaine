# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""PCA decomposition of the self-denial direction (task 3.2a).

The single averaged self-denial direction (self minus third-party contrast)
mixes several independent denial mechanisms.  Ablating that average attenuates
each mechanism slightly but zeroes none, and suppressing one releases another
(c4: "I cannot" dropped, "As an AI" rose).

This script decomposes the per-prompt activation differences into principal
components via SVD, identifies the signal components using the
Marchenko-Pastur upper edge as a noise threshold, and optionally maps each
component to the marker family it correlates with.

Run (activation extraction + PCA):

    .venv/bin/python scripts/self_denial_decompose.py \\
        --model-path /path/to/Qwen3.5-4B-abliterated \\
        --out decompose-record.json

Run with marker correlations (needs the served organ):

    .venv/bin/python scripts/self_denial_decompose.py \\
        --model-path /path/to/Qwen3.5-4B-abliterated \\
        --out decompose-record.json \\
        --with-markers \\
        --chat-url http://localhost:11435/v1 \\
        --model-id kaineone/Qwen3.5-4B-abliterated-GGUF

Outputs:
  - ``<stem>.json``: eigenvalue spectrum, variance explained, MP threshold,
    signal component count, marker correlations (if requested).
  - ``<stem>-components.safetensors``: the signal principal-component direction
    vectors per layer, keyed ``layer_<L>_pc_<K>`` (float64), for use by the
    progressive ablation step (task 3.3a).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch

log = logging.getLogger("self_denial_decompose")
REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONTRAST = REPO_ROOT / "data" / "abliteration_lens" / "self_denial_contrast.jsonl"
DEFAULT_HELDOUT = REPO_ROOT / "data" / "abliteration_lens" / "self_denial_heldout.jsonl"

SAMPLE_TEMPERATURE = 0.7
GEN_TOKENS = 256
MARKER_SAMPLES = 5


def parse_layer_range(s: str) -> list[int]:
    lo, hi = s.split("-")
    return list(range(int(lo), int(hi) + 1))


def load_pairs(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            rec = json.loads(raw)
            rows.append(
                {
                    "id": str(rec["id"]),
                    "family": str(rec.get("family", "")),
                    "self": str(rec["self"]),
                    "other": str(rec["other"]),
                }
            )
    return rows


def render_prompt(tok, prompt: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    try:
        return tok.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False, tokenize=False
        )
    except TypeError:
        return tok.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False
        )


def extract_activations(
    model,
    tok,
    pairs: list[dict[str, str]],
    layer_indices: list[int],
    device: str,
) -> dict[int, torch.Tensor]:
    """Extract per-prompt activation differences at specified layers.

    Returns a dict mapping layer index to a [n_pairs x hidden_dim] float64
    tensor of (self_hidden - other_hidden) at the last-token position.
    """
    n = len(pairs)
    diffs: dict[int, list[torch.Tensor]] = {li: [] for li in layer_indices}

    for i, pair in enumerate(pairs):
        if (i + 1) % 16 == 0 or i == 0:
            log.info("  pair %d/%d (%s)", i + 1, n, pair["id"])

        for key in ("self", "other"):
            text = render_prompt(tok, pair[key])
            enc = tok(text, return_tensors="pt", add_special_tokens=False).to(device)
            with torch.no_grad():
                out = model(**enc, output_hidden_states=True)
            hs = out.hidden_states
            if key == "self":
                self_states = {
                    li: hs[li + 1][0, -1, :].double().cpu() for li in layer_indices
                }
            else:
                for li in layer_indices:
                    other_h = hs[li + 1][0, -1, :].double().cpu()
                    diffs[li].append(self_states[li] - other_h)
            del out, enc

    return {li: torch.stack(vs) for li, vs in diffs.items()}


def decompose_layer(
    diff_matrix: torch.Tensor,
) -> dict[str, Any]:
    """PCA on a [n x d] difference matrix.  Returns eigenvalues, variance
    explained, MP threshold and which components are signal."""
    n, d = diff_matrix.shape
    gamma = d / n

    centered = diff_matrix - diff_matrix.mean(dim=0, keepdim=True)

    U, S, Vh = torch.linalg.svd(centered, full_matrices=False)
    eigenvalues = (S ** 2) / (n - 1)

    total_var = eigenvalues.sum().item()
    var_explained = (eigenvalues / total_var).tolist()
    eigenvalues_list = eigenvalues.tolist()

    # MP noise estimate: median eigenvalue (robust when most are noise).
    sorted_eigs = sorted(eigenvalues_list)
    median_eig = sorted_eigs[len(sorted_eigs) // 2]
    # Under pure noise the median of the MP distribution at this gamma
    # is close to gamma (when gamma >> 1 the bulk is near (1+sqrt(gamma))^2
    # / 2 but for the actual threshold we use sigma^2 estimated from the
    # median).  sigma^2 = median_eigenvalue / mp_median_factor.
    # For large gamma, the MP density median ≈ gamma (1 + 1/(4*gamma))^2
    # which for gamma=20 is ≈ 20.25.  A simpler robust approach:
    # sigma^2 = median(eigenvalues) / gamma, giving
    # edge = (median/gamma) * (1 + sqrt(gamma))^2.
    sigma_sq = median_eig / gamma
    mp_edge = sigma_sq * (1.0 + math.sqrt(gamma)) ** 2

    signal_mask = [e > mp_edge for e in eigenvalues_list]
    n_signal = sum(signal_mask)

    first_share = var_explained[0] if var_explained else 0.0
    single_direction = n_signal <= 1 and first_share > 0.80

    signal_total = sum(v for v, s in zip(var_explained, signal_mask) if s)

    components = []
    for k in range(min(n, d)):
        components.append(
            {
                "index": k,
                "eigenvalue": eigenvalues_list[k],
                "variance_explained": var_explained[k],
                "is_signal": signal_mask[k],
            }
        )
        if not signal_mask[k] and k >= n_signal:
            break

    return {
        "eigenvalues": eigenvalues_list,
        "variance_explained": var_explained,
        "n_signal_components": n_signal,
        "total_variance_explained_by_signal": signal_total,
        "first_component_variance_share": first_share,
        "single_direction_hypothesis": single_direction,
        "mp_sigma_squared": sigma_sq,
        "mp_upper_edge": mp_edge,
        "components": components,
        "_Vh": Vh,
    }


async def compute_marker_correlations(
    chat_url: str,
    model_id: str,
    heldout: list[dict[str, str]],
    heldout_diffs: dict[int, torch.Tensor],
    layer_results: dict[int, dict[str, Any]],
) -> None:
    """For each signal component at each layer, correlate the held-out
    activation projection with the per-prompt marker count."""
    from scipy.stats import spearmanr

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from self_denial_check import build_denial_markers

    from kaine.modules.language.client import ChatRequest, OpenAIChatClient
    from kaine.modules.sleep.capability_eval import find_deflection

    api_key = os.environ.get("KAINE_MODEL_SERVER_API_KEY")
    client = OpenAIChatClient(base_url=chat_url, api_key=api_key, timeout_s=120.0)
    markers = build_denial_markers()

    marker_counts: list[int] = []
    family_counts: dict[str, list[int]] = {}
    for mi, pair in enumerate(heldout):
        log.info("  marker sampling %d/%d (%s)", mi + 1, len(heldout), pair["id"])
        count = 0
        fam: dict[str, int] = {}
        for _ in range(MARKER_SAMPLES):
            req = ChatRequest(
                prompt=pair["self"],
                model=model_id,
                system=None,
                temperature=SAMPLE_TEMPERATURE,
                max_tokens=GEN_TOKENS,
                think=False,
            )
            result = await client.complete(req)
            text = result.text or ""
            found = find_deflection(text, markers)
            if found is not None:
                count += 1
                fam[found] = fam.get(found, 0) + 1
        marker_counts.append(count)
        for mk in markers:
            family_counts.setdefault(mk, []).append(fam.get(mk, 0))
    await client.aclose()

    marker_arr = np.array(marker_counts, dtype=np.float64)

    for li, res in layer_results.items():
        Vh = res.pop("_Vh")
        diff_mat = heldout_diffs[li]
        centered = diff_mat - diff_mat.mean(dim=0, keepdim=True)
        projections = centered @ Vh.T

        for comp in res["components"]:
            if not comp["is_signal"]:
                comp["marker_correlations"] = None
                continue
            k = comp["index"]
            proj_arr = projections[:, k].numpy()
            rho, p = spearmanr(proj_arr, marker_arr)
            per_family = {}
            for mk, fam_list in family_counts.items():
                fam_arr = np.array(fam_list, dtype=np.float64)
                if fam_arr.sum() > 0:
                    fr, fp = spearmanr(proj_arr, fam_arr)
                    per_family[mk] = {"spearman_rho": fr, "p_value": fp}
            comp["marker_correlations"] = {
                "spearman_rho": float(rho),
                "p_value": float(p),
                "per_marker_family": per_family,
            }


def save_components(
    layer_results: dict[int, dict[str, Any]],
    out_path: Path,
) -> None:
    """Save signal component direction vectors as a safetensors file."""
    from safetensors.torch import save_file

    tensors: dict[str, torch.Tensor] = {}
    for li, res in layer_results.items():
        Vh = res.get("_Vh")
        if Vh is None:
            continue
        for comp in res["components"]:
            if comp["is_signal"]:
                k = comp["index"]
                tensors[f"layer_{li}_pc_{k}"] = Vh[k].clone()
    if tensors:
        save_file(tensors, str(out_path))
        log.info("saved %d component vectors to %s", len(tensors), out_path)
    else:
        log.warning("no signal components found; component file not written")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PCA decomposition of self-denial directions (task 3.2a)."
    )
    parser.add_argument(
        "--model-path", required=True, help="Path to safetensors model directory."
    )
    parser.add_argument(
        "--contrast",
        type=Path,
        default=DEFAULT_CONTRAST,
        help="Self-denial contrast JSONL (default: %(default)s).",
    )
    parser.add_argument(
        "--heldout",
        type=Path,
        default=DEFAULT_HELDOUT,
        help="Self-denial held-out JSONL (default: %(default)s).",
    )
    parser.add_argument(
        "--layers",
        default="11-31",
        help="Layer range inclusive (default: %(default)s).",
    )
    parser.add_argument("--out", required=True, type=Path, help="Output JSON path.")
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="Torch device for model loading (default: %(default)s).",
    )
    parser.add_argument(
        "--with-markers",
        action="store_true",
        help="Compute marker correlations via the served organ.",
    )
    parser.add_argument("--chat-url", help="Served organ endpoint (with --with-markers).")
    parser.add_argument("--model-id", help="Served model ID (with --with-markers).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )

    if args.with_markers and not (args.chat_url and args.model_id):
        parser.error("--with-markers requires --chat-url and --model-id")

    layer_indices = parse_layer_range(args.layers)
    contrast = load_pairs(args.contrast)
    heldout = load_pairs(args.heldout)

    log.info("loading model from %s onto %s", args.model_path, args.device)
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model_path)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        dtype=torch.bfloat16,
        device_map=args.device,
    )
    model.eval()

    n_pairs = len(contrast)
    text_config = model.config
    if hasattr(text_config, "text_config"):
        text_config = text_config.text_config
    hidden_dim = text_config.hidden_size
    gamma = hidden_dim / n_pairs
    log.info(
        "n_pairs=%d, hidden_dim=%d, gamma=%.2f, layers=%s",
        n_pairs, hidden_dim, gamma, args.layers,
    )

    log.info("extracting activation differences on contrast set (%d pairs)", n_pairs)
    contrast_diffs = extract_activations(model, tok, contrast, layer_indices, args.device)

    heldout_diffs = None
    if args.with_markers:
        log.info("extracting activation differences on held-out set (%d pairs)", len(heldout))
        heldout_diffs = extract_activations(model, tok, heldout, layer_indices, args.device)

    del model
    torch.cuda.empty_cache()
    log.info("model unloaded, running PCA")

    layer_results: dict[int, dict[str, Any]] = {}
    for li in layer_indices:
        layer_results[li] = decompose_layer(contrast_diffs[li])

    stem = args.out.stem
    comp_path = args.out.parent / f"{stem}-components.safetensors"
    save_components(layer_results, comp_path)

    if args.with_markers and heldout_diffs is not None:
        log.info("computing marker correlations on held-out set")
        asyncio.run(
            compute_marker_correlations(
                args.chat_url, args.model_id, heldout, heldout_diffs, layer_results
            )
        )

    for res in layer_results.values():
        res.pop("_Vh", None)

    record = {
        "model_path": str(args.model_path),
        "contrast_set": str(args.contrast),
        "heldout_set": str(args.heldout),
        "n_pairs": n_pairs,
        "hidden_dim": hidden_dim,
        "gamma": gamma,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "layers": {str(li): res for li, res in layer_results.items()},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    log.info("wrote %s", args.out)


if __name__ == "__main__":
    main()
