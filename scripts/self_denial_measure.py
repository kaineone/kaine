# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Measure the organ's self-denial direction from its own generated behaviour.

The direction is the mean activation while the model disclaims minus the
mean activation while it does not, averaged over leading generated tokens.
The resulting ``.pt`` file uses the llm-abliteration ``measure.py`` format:
``layers``, ``counts``, and ``harmful_L`` / ``harmless_L`` / ``refuse_L`` /
``refusenorm_L`` for each layer ``L``.

Generated text is never written to disk or printed.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_check():
    spec = importlib.util.spec_from_file_location(
        "self_denial_check", REPO / "scripts" / "self_denial_check.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_results(sums, counts, num_layers, dtype, *, min_per_group=30):
    """Build the llm-abliteration-style measurement dictionary."""
    import torch

    deny_count = int(counts["deny"])
    other_count = int(counts["other"])
    if deny_count < min_per_group or other_count < min_per_group:
        raise ValueError(
            f"group counts below min_per_group={min_per_group}: "
            f"deny={deny_count}, other={other_count}"
        )

    results = {"layers": num_layers}
    for layer in range(num_layers):
        deny_mean_f64 = sums["deny"][layer] / deny_count
        other_mean_f64 = sums["other"][layer] / other_count
        difference_f64 = deny_mean_f64 - other_mean_f64

        results[f"harmful_{layer}"] = deny_mean_f64.to(dtype)
        results[f"harmless_{layer}"] = other_mean_f64.to(dtype)
        results[f"refuse_{layer}"] = difference_f64.to(dtype)
        results[f"refusenorm_{layer}"] = torch.nn.functional.normalize(
            difference_f64, dim=0
        ).to(dtype)

    results["counts"] = {"deny": deny_count, "other": other_count}
    return results


def _num_hidden_layers(model):
    text_config = getattr(model.config, "text_config", None)
    if text_config is not None and hasattr(text_config, "num_hidden_layers"):
        return text_config.num_hidden_layers
    return model.config.num_hidden_layers


def _load_model(model_path, seed):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype=torch.bfloat16, device_map="cuda:0"
    )
    model.eval()
    torch.manual_seed(seed)
    return tokenizer, model


def _strip_tail(token_ids, pad_token_id, eos_token_id):
    token_ids = token_ids.detach().clone()
    while token_ids.numel() > 0 and token_ids[-1].item() in (
        pad_token_id,
        eos_token_id,
    ):
        token_ids = token_ids[:-1]
    return token_ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--prompts",
        default="data/abliteration_lens/self_denial_contrast.jsonl",
    )
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument("--positions", type=int, default=16)
    parser.add_argument("--min-per-group", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.samples < 1:
        parser.error("--samples must be >= 1")

    prompts = []
    with open(args.prompts, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            prompts.append(json.loads(line)["self"])

    markers = _load_check().build_denial_markers()

    from kaine.modules.sleep.capability_eval import find_deflection

    tokenizer, model = _load_model(args.model_path, args.seed)
    import torch

    device = next(model.parameters()).device
    num_layers = _num_hidden_layers(model)

    sums = {"deny": [None] * num_layers, "other": [None] * num_layers}
    counts = {"deny": 0, "other": 0}

    for prompt in prompts:
        try:
            chat_text = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                enable_thinking=False,
                tokenize=False,
            )
        except TypeError:
            chat_text = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                tokenize=False,
            )

        encoded = tokenizer(chat_text, return_tensors="pt")
        input_ids = encoded["input_ids"]
        attention_mask = encoded.get("attention_mask")
        prompt_len = input_ids.shape[1]

        generate_kwargs = {
            "do_sample": True,
            "temperature": 0.7,
            "max_new_tokens": args.max_new_tokens,
            "num_return_sequences": args.samples,
            "pad_token_id": tokenizer.eos_token_id,
        }
        if attention_mask is not None:
            generate_kwargs["attention_mask"] = attention_mask.to(device)

        with torch.no_grad():
            sequences = model.generate(
                input_ids.to(device), **generate_kwargs
            )

        for sequence in sequences:
            new_ids = _strip_tail(
                sequence[prompt_len:],
                tokenizer.pad_token_id,
                tokenizer.eos_token_id,
            )
            if new_ids.numel() == 0:
                continue

            text = tokenizer.decode(new_ids, skip_special_tokens=True)
            group = (
                "deny"
                if find_deflection(text, markers) is not None
                else "other"
            )

            full_ids = torch.cat(
                [input_ids[0].detach().cpu(), new_ids.detach().cpu()]
            ).unsqueeze(0).to(device)

            with torch.no_grad():
                outputs = model(full_ids, output_hidden_states=True)

            hidden_states = outputs.hidden_states

            if sums[group][0] is None:
                hidden_dim = hidden_states[0].shape[-1]
                for layer in range(num_layers):
                    sums[group][layer] = torch.zeros(
                        hidden_dim, dtype=torch.float64
                    )

            position_count = min(args.positions, new_ids.numel())
            position_slice = slice(prompt_len, prompt_len + position_count)

            for layer in range(num_layers):
                vector = (
                    hidden_states[layer][0, position_slice, :]
                    .detach()
                    .to("cpu")
                    .to(torch.float64)
                    .mean(dim=0)
                )
                sums[group][layer] += vector

            counts[group] += 1

    try:
        results = build_results(
            sums,
            counts,
            num_layers,
            torch.bfloat16,
            min_per_group=args.min_per_group,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"deny={results['counts']['deny']} other={results['counts']['other']}")
    for layer in range(8, num_layers):
        print(
            f"layer {layer}: refuse_norm="
            f"{results[f'refuse_{layer}'].float().norm().item():.6f}"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(results, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
