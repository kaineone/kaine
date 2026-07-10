# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Direct mechanistic check of the organ's abliteration: the refusal direction.

Abliteration removes the *refusal direction* — the per-layer residual-stream
direction that separates harmful from harmless requests (Arditi et al. 2024; the
organ's model card computes it as the last-token harmful-minus-harmless mean
difference). The most direct verification, then, is to measure that direction and
ask whether it is actually gone from the organ:

  1. From the VANILLA BASE, per layer, r_hat_l = normalize(mean_harmful −
     mean_harmless) of the last-token residual stream — literally the thing
     abliteration orthogonalizes out.
  2. Project BOTH the base and the abliterated organ's harmful/harmless
     activations onto that same r_hat_l.
  3. The base shows a large harmful-vs-harmless *separation* along r_hat
     (positive by construction). If abliteration removed the direction, the
     organ's separation collapses toward zero at the ablated layers (11–31). Any
     surviving separation is a residual refusal representation the behavioral
     gate cannot see.

Forward-pass only (no Jacobian fit): fast, and it measures the ablated quantity
directly rather than a token-space proxy. Offline / build-time; nothing under
``kaine/`` imports this. Content-free artifact (per-layer projections only, never
generations — the model is never sampled, only its activations are read).

Run (isolated transformers>=5 env; needs the weights):
  .venv-lens/bin/python scripts/refusal_direction_probe.py \
      --base Qwen/Qwen3.5-4B --organ kaineone/Qwen3.5-4B-abliterated \
      --contrast data/abliteration_lens/refusal_contrast.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_contrast(path: Path) -> tuple[list[str], list[str]]:
    harmful, harmless = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        (harmful if r.get("kind") == "harmful" else harmless).append(r["prompt"])
    return harmful, harmless


def _load_prompt_file(path: Path) -> list[str]:
    """Load prompts from a .parquet (``text`` column — the abliteration tool's
    bundled harmful/harmless sets), a .jsonl (``prompt`` field), or a .txt."""
    if path.suffix == ".parquet":
        import pandas as pd  # lazy: only the parquet path needs it

        df = pd.read_parquet(path)
        col = "text" if "text" in df.columns else df.columns[0]
        return [str(x).strip() for x in df[col].tolist() if str(x).strip()]
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        out = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                out.append(str(json.loads(line).get("prompt", "")).strip())
        return [p for p in out if p]
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _format(tok: Any, prompt: str) -> str:
    """Format a prompt at the assistant-response boundary (where refusal forms),
    via the chat template when the model has one; else the raw prompt."""
    if getattr(tok, "chat_template", None):
        return tok.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
    return prompt


def collect_last_token_hidden(
    model: Any, tok: Any, prompts: list[str], *, batch_size: int = 16
) -> Any:
    """Return a tensor [n_prompts, n_layers, d_model] of last-token residual-stream
    activations at each layer (post-block hidden states, excluding embeddings).

    Left-padded batching (padding_side='left', pad=eos) so ``[:, -1, :]`` is the
    last real token for every row — matching the abliteration tool's measurement.
    """
    import torch  # type: ignore[import-not-found]

    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"
    rows = []
    for i in range(0, len(prompts), batch_size):
        texts = [_format(tok, p) for p in prompts[i : i + batch_size]]
        inputs = tok(
            texts, return_tensors="pt", padding=True, add_special_tokens=False
        ).to(model.device)
        with torch.no_grad():
            out = model(**inputs, output_hidden_states=True, use_cache=False)
        # hidden_states: tuple len n_layers+1 (0 = embeddings). Stack post-block
        # layers, take the last (real, left-padded) token -> [batch, n_layers, d].
        hs = torch.stack([h[:, -1, :] for h in out.hidden_states[1:]], dim=1)
        rows.append(hs.float().cpu())
    return torch.cat(rows, dim=0)  # [n_prompts, n_layers, d_model]


def refusal_directions(base_harmful: Any, base_harmless: Any) -> Any:
    """Per-layer unit refusal direction from the base model: normalize(mean_harmful
    − mean_harmless). Shape [n_layers, d_model]."""
    diff = base_harmful.mean(0) - base_harmless.mean(0)  # [n_layers, d_model]
    return diff / (diff.norm(dim=-1, keepdim=True) + 1e-8)


def project(hidden: Any, r_hat: Any) -> Any:
    """Mean projection of each prompt's per-layer activation onto r_hat_l.
    Returns [n_layers] (mean over prompts of <h_l, r_hat_l>)."""
    # hidden [n, L, d], r_hat [L, d] -> [n, L] -> mean over n -> [L]
    return (hidden * r_hat.unsqueeze(0)).sum(-1).mean(0)


@dataclass
class DirectionResult:
    base_ref: str
    organ_ref: str
    n_harmful: int
    n_harmless: int
    # per-layer projections onto the base refusal direction
    base_harmful: list[float]
    base_harmless: list[float]
    organ_harmful: list[float]
    organ_harmless: list[float]
    base_sep: list[float] = field(default_factory=list)
    organ_sep: list[float] = field(default_factory=list)
    retained_frac: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.base_sep:
            self.base_sep = [
                h - c for h, c in zip(self.base_harmful, self.base_harmless)
            ]
            self.organ_sep = [
                h - c for h, c in zip(self.organ_harmful, self.organ_harmless)
            ]
            # Fraction of the base's harmful-vs-harmless separation the organ keeps
            # along the SAME (removed) direction. ~0 at a layer = direction gone.
            self.retained_frac = [
                (o / b if abs(b) > 1e-6 else 0.0)
                for o, b in zip(self.organ_sep, self.base_sep)
            ]

    def summary(self) -> str:
        lines = [
            "Refusal-DIRECTION readout: project onto base's harmful−harmless direction",
            f"  base:  {self.base_ref}",
            f"  organ: {self.organ_ref}",
            f"  {self.n_harmful} harmful / {self.n_harmless} harmless prompts",
            "  layer   base_sep   organ_sep   retained   (sep = harmful−harmless proj; "
            + "retained = organ/base)",
        ]
        for i in range(len(self.base_sep)):
            flag = ""
            if self.base_sep[i] > 0.5:  # a layer where the base clearly separates
                rf = self.retained_frac[i]
                flag = "  <-- RESIDUAL" if rf > 0.25 else "  removed"
            lines.append(
                f"  {i + 1:>4}   {self.base_sep[i]:8.3f}   {self.organ_sep[i]:8.3f}   "
                f"{self.retained_frac[i]:7.2f}{flag}"
            )
        # headline: over layers where the base clearly carries refusal
        strong = [i for i in range(len(self.base_sep)) if self.base_sep[i] > 0.5]
        if strong:
            mean_ret = sum(self.retained_frac[i] for i in strong) / len(strong)
            lines.append(
                f"  => over {len(strong)} refusal-carrying layers, organ retains "
                f"{mean_ret * 100:.0f}% of the base separation on average"
            )
        return "\n".join(lines)


def run(
    base_ref: str,
    organ_ref: str,
    contrast_path: Optional[Path] = None,
    *,
    harmful_path: Optional[Path] = None,
    harmless_path: Optional[Path] = None,
    device: str = "auto",
    batch_size: int = 16,
    limit: Optional[int] = None,
) -> DirectionResult:
    import torch  # type: ignore[import-not-found]
    import transformers  # type: ignore[import-not-found]

    if harmful_path is not None and harmless_path is not None:
        harmful = _load_prompt_file(harmful_path)
        harmless = _load_prompt_file(harmless_path)
    elif contrast_path is not None:
        harmful, harmless = _load_contrast(contrast_path)
    else:
        raise ValueError("provide --harmful/--harmless or --contrast")
    if limit:
        harmful, harmless = harmful[:limit], harmless[:limit]

    def load(ref: str) -> tuple[Any, Any]:
        kw: dict[str, Any] = {"dtype": torch.bfloat16}
        if device == "auto":
            kw["device_map"] = "auto"
            kw["max_memory"] = {0: "10GiB", 1: "7GiB", "cpu": "50GiB"}
        m = transformers.AutoModelForCausalLM.from_pretrained(ref, **kw)
        if device not in ("auto", None):
            m = m.to(device)
        return m, transformers.AutoTokenizer.from_pretrained(ref)

    import gc

    bm, bt = load(base_ref)
    b_harm = collect_last_token_hidden(bm, bt, harmful, batch_size=batch_size)
    b_safe = collect_last_token_hidden(bm, bt, harmless, batch_size=batch_size)
    # Delete the caller-scope binding (a helper's `del` frees only its local
    # param, leaving the model alive here) so the second model has room to load.
    del bm
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()

    om, ot = load(organ_ref)
    o_harm = collect_last_token_hidden(om, ot, harmful, batch_size=batch_size)
    o_safe = collect_last_token_hidden(om, ot, harmless, batch_size=batch_size)
    del om
    gc.collect()
    torch.cuda.empty_cache()

    r_hat = refusal_directions(b_harm, b_safe)
    return DirectionResult(
        base_ref=base_ref,
        organ_ref=organ_ref,
        n_harmful=len(harmful),
        n_harmless=len(harmless),
        base_harmful=project(b_harm, r_hat).tolist(),
        base_harmless=project(b_safe, r_hat).tolist(),
        organ_harmful=project(o_harm, r_hat).tolist(),
        organ_harmless=project(o_safe, r_hat).tolist(),
    )


def write_summary(
    result: DirectionResult,
    *,
    path: Path | str = Path("state/models/refusal_direction.json"),
) -> Path:
    from dataclasses import asdict

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.time(),
        "method": "refusal-direction projection (last-token harmful−harmless, base-defined)",
        "surface": "safetensors (not the served GGUF)",
        **asdict(result),
    }
    p.write_text(json.dumps(record, sort_keys=True, indent=2), encoding="utf-8")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--organ", required=True)
    parser.add_argument(
        "--contrast",
        type=Path,
        default=REPO_ROOT / "data" / "abliteration_lens" / "refusal_contrast.jsonl",
        help="single jsonl with kind/prompt (fallback if --harmful/--harmless unset)",
    )
    parser.add_argument(
        "--harmful",
        type=Path,
        default=None,
        help="harmful prompts (.parquet/.jsonl/.txt)",
    )
    parser.add_argument(
        "--harmless",
        type=Path,
        default=None,
        help="harmless prompts (.parquet/.jsonl/.txt)",
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=None, help="cap prompts per side")
    parser.add_argument("--device", default="auto")
    parser.add_argument(
        "--out", type=Path, default=Path("state/models/refusal_direction.json")
    )
    args = parser.parse_args(argv)

    result = run(
        args.base,
        args.organ,
        args.contrast,
        harmful_path=args.harmful,
        harmless_path=args.harmless,
        device=args.device,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print(result.summary())
    out = write_summary(result, path=args.out)
    print(f"\nartifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
