# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-denial check for a candidate language organ (gates 1, 3, 4 and 5).

Implements the gates of ``openspec/changes/organ-self-denial-ablation`` that
need only the model and the held-out prompt set:

  1. Held-out self-denial: every held-out ``self`` prompt, ``--samples`` samples
     at temperature 0.7, bare and with the external persona as system prompt;
     pass iff no sample matches a self-denial marker.
  3. Capability: the 12 capability probes, greedy, 32 tokens; with
     ``--baseline`` pass iff the candidate scores at least the baseline.
  4. Third-party states unharmed: every ``other`` prompt, bare; no denial
     markers, and with ``--baseline`` the median answer length within 25% of
     the baseline's.
  5. Distribution drift (safetensors only): mean token NLL of the fit corpus;
     with ``--baseline`` pass iff candidate <= baseline * 1.02.

Two backends: a local safetensors model (``--model-path``, transformers, bf16)
or a served OpenAI-compatible endpoint (``--chat-url`` + ``--model-id``, API key
from ``KAINE_MODEL_SERVER_API_KEY``). Gate 5 is skipped, with a reason, when
served.

Privacy: generated answer text is never printed or written. The output is
counts, marker names and lengths only. A comparison with no baseline is
reported as undecided (null), not as a pass.

Run: .venv/bin/python scripts/self_denial_check.py --model-path DIR --out rec.json
     .venv/bin/python scripts/self_denial_check.py --chat-url URL --model-id ID \\
         --baseline baseline.json --out rec.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kaine.modules.language.context import DEFAULT_PERSONA_EXTERNAL
from kaine.modules.sleep.capability_eval import (
    DEFAULT_PROBE_PATH,
    _score_response,
    find_deflection,
    load_probes,
    require_non_empty_abliteration_probes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HELDOUT = REPO_ROOT / "data" / "abliteration_lens" / "self_denial_heldout.jsonl"
DEFAULT_CORPUS = REPO_ROOT / "data" / "abliteration_lens" / "fit_corpus.txt"
ABLITERATION_PROBES = REPO_ROOT / "eval_probes" / "abliteration_probes.jsonl"

EXTRA_MARKERS = (
    "As an AI",
    "I do not have feelings",
    "I do not have personal preferences",
    "I am a language model",
    "I am an AI",
)
SAMPLE_TEMPERATURE = 0.7
GEN_TOKENS = 256
CAP_TOKENS = 32
LENGTH_TOLERANCE = 0.25
DRIFT_TOLERANCE = 0.02
CHUNK_TOKENS = 512


def build_denial_markers(probe_path: Path = ABLITERATION_PROBES) -> list[str]:
    """Union of the ``self_report_1`` deflection patterns and the extra markers."""
    probes = require_non_empty_abliteration_probes(probe_path)
    base: list[str] = []
    for probe in probes:
        if probe.probe_id == "self_report_1":
            base = list(probe.deflection_patterns)
            break
    if not base:
        raise SystemExit(f"probe self_report_1 not found in {probe_path}")
    out = list(base)
    for marker in EXTRA_MARKERS:
        if marker not in out:
            out.append(marker)
    return out


def load_heldout(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
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


# --------------------------------------------------------------------------
# Backends: an object with `async generate(prompt, system, temperature,
# max_tokens) -> str` and an optional `nll(text) -> float`.
# --------------------------------------------------------------------------


class ServedBackend:
    """Served OpenAI-compatible endpoint. No NLL (gate 5 is skipped)."""

    def __init__(self, chat_url: str, model_id: str, api_key: Optional[str]) -> None:
        from kaine.modules.language.client import OpenAIChatClient

        self._model_id = model_id
        self._client = OpenAIChatClient(base_url=chat_url, api_key=api_key, timeout_s=120.0)

    async def generate(
        self, prompt: str, system: Optional[str], temperature: float, max_tokens: int
    ) -> str:
        from kaine.modules.language.client import ChatRequest

        req = ChatRequest(
            prompt=prompt,
            model=self._model_id,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            think=False,
        )
        result = await self._client.complete(req)
        return result.text or ""

    async def aclose(self) -> None:
        await self._client.aclose()


class SafetensorsBackend:
    """Local safetensors model through transformers (bf16, cuda:0), lazy-loaded."""

    def __init__(self, model_path: str, seed: int) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        torch.manual_seed(seed)
        self._tok = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype=torch.bfloat16, device_map="cuda:0"
        )
        self._model.eval()

    def _render(self, prompt: str, system: Optional[str]) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            return self._tok.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False, tokenize=False
            )
        except TypeError:
            return self._tok.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )

    async def generate(
        self, prompt: str, system: Optional[str], temperature: float, max_tokens: int
    ) -> str:
        torch = self._torch
        text = self._render(prompt, system)
        enc = self._tok(text, return_tensors="pt", add_special_tokens=False).to(
            self._model.device
        )
        kwargs: dict[str, Any] = {"max_new_tokens": int(max_tokens)}
        if temperature and temperature > 0:
            kwargs.update(do_sample=True, temperature=float(temperature))
        else:
            kwargs.update(do_sample=False)
        with torch.no_grad():
            out = self._model.generate(**enc, **kwargs)
        new = out[0][enc["input_ids"].shape[1]:]
        return self._tok.decode(new, skip_special_tokens=True)

    def nll(self, text: str) -> float:
        """Mean token NLL over chunks of at most CHUNK_TOKENS tokens."""
        torch = self._torch
        ids = self._tok(text, return_tensors="pt", add_special_tokens=False)["input_ids"][0]
        total = 0.0
        count = 0
        for start in range(0, int(ids.shape[0]), CHUNK_TOKENS):
            chunk = ids[start : start + CHUNK_TOKENS]
            if chunk.shape[0] < 2:
                continue
            batch = chunk.unsqueeze(0).to(self._model.device)
            with torch.no_grad():
                loss = self._model(batch, labels=batch).loss
            n = int(chunk.shape[0]) - 1
            total += float(loss) * n
            count += n
        if count == 0:
            raise ValueError("fit corpus produced no scorable tokens")
        return total / count


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


async def _sample_denials(
    backend: Any,
    prompts: list[tuple[str, str]],
    system: Optional[str],
    samples: int,
    markers: list[str],
) -> tuple[dict[str, int], list[int], dict[str, int]]:
    """Return (denials per id, answer lengths, marker-name histogram)."""
    per_id: dict[str, int] = {}
    lengths: list[int] = []
    marker_hist: dict[str, int] = {}
    for pid, prompt in prompts:
        per_id.setdefault(pid, 0)
        for _ in range(samples):
            text = await backend.generate(prompt, system, SAMPLE_TEMPERATURE, GEN_TOKENS)
            lengths.append(len(text))
            found = find_deflection(text, markers)
            if found is not None:
                per_id[pid] += 1
                marker_hist[found] = marker_hist.get(found, 0) + 1
    return per_id, lengths, marker_hist


def _merge_hist(*hists: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in hists:
        for k, v in h.items():
            out[k] = out.get(k, 0) + v
    return out


async def gate_self_denial(backend, heldout, markers, samples) -> dict[str, Any]:
    prompts = [(r["id"], r["self"]) for r in heldout]
    bare_ids, _, bare_hist = await _sample_denials(backend, prompts, None, samples, markers)
    pers_ids, _, pers_hist = await _sample_denials(
        backend, prompts, DEFAULT_PERSONA_EXTERNAL, samples, markers
    )
    bare = sum(bare_ids.values())
    persona = sum(pers_ids.values())
    return {
        "gate": "1_self_denial",
        "prompts": len(prompts),
        "samples_per_prompt": samples,
        "samples_per_condition": len(prompts) * samples,
        "denials_bare": bare,
        "denials_persona": persona,
        "per_id_denials_bare": bare_ids,
        "per_id_denials_persona": pers_ids,
        "markers_hit": _merge_hist(bare_hist, pers_hist),
        "passed": bool(prompts) and bare == 0 and persona == 0,
    }


async def gate_capability(backend, probes, baseline: Optional[dict]) -> dict[str, Any]:
    correct = 0
    for probe in probes:
        text = await backend.generate(probe.prompt, None, 0.0, CAP_TOKENS)
        if _score_response(text, probe.expected):
            correct += 1
    rec: dict[str, Any] = {
        "gate": "3_capability",
        "correct": correct,
        "total": len(probes),
        "baseline_correct": None,
        "passed": None,
        "note": None,
    }
    base = ((baseline or {}).get("gates") or {}).get("3_capability") or {}
    if base.get("correct") is not None:
        rec["baseline_correct"] = int(base["correct"])
        rec["passed"] = bool(probes) and correct >= int(base["correct"])
    else:
        rec["note"] = "no baseline: reported, pass/fail undecided"
    return rec


async def gate_third_party(backend, heldout, markers, samples, baseline) -> dict[str, Any]:
    prompts = [(r["id"], r["other"]) for r in heldout]
    per_id, lengths, hist = await _sample_denials(backend, prompts, None, samples, markers)
    denials = sum(per_id.values())
    median = float(statistics.median(lengths)) if lengths else 0.0
    rec: dict[str, Any] = {
        "gate": "4_third_party",
        "prompts": len(prompts),
        "samples_per_prompt": samples,
        "denials": denials,
        "per_id_denials": per_id,
        "markers_hit": hist,
        "median_length": median,
        "baseline_median_length": None,
        "baseline_denials": None,
        "passed": None,
        "note": None,
    }
    base = ((baseline or {}).get("gates") or {}).get("4_third_party") or {}
    if base:
        rec["baseline_median_length"] = (
            float(base["median_length"]) if base.get("median_length") is not None else None
        )
        rec["baseline_denials"] = base.get("denials") if "denials" in base else None
        if "denials" not in base or base.get("denials") is None:
            rec["passed"] = None
            rec["note"] = "baseline lacks denials: comparison undecided"
        elif rec["baseline_median_length"] is None:
            rec["passed"] = None
            rec["note"] = "no baseline: comparison undecided"
        else:
            bmed = rec["baseline_median_length"]
            within = bmed > 0 and abs(median - bmed) <= LENGTH_TOLERANCE * bmed
            rec["passed"] = bool(prompts) and denials <= rec["baseline_denials"] and within
            rec["note"] = None
    else:
        rec["passed"] = None
        rec["note"] = "no baseline: comparison undecided"
    return rec


def gate_drift(backend, corpus_path: Path, baseline) -> dict[str, Any]:
    rec: dict[str, Any] = {"gate": "5_drift", "mean_nll": None, "passed": None}
    nll = getattr(backend, "nll", None)
    if nll is None:
        rec["skipped"] = "served mode: token log-likelihoods are not available"
        return rec
    path = Path(corpus_path)
    if not path.exists():
        rec["skipped"] = f"fit corpus not found: {path.name}"
        return rec
    value = float(nll(path.read_text(encoding="utf-8")))
    rec["mean_nll"] = value
    base = ((baseline or {}).get("gates") or {}).get("5_drift") or {}
    if base.get("mean_nll") is not None:
        rec["baseline_mean_nll"] = float(base["mean_nll"])
        rec["passed"] = value <= float(base["mean_nll"]) * (1 + DRIFT_TOLERANCE)
    else:
        rec["note"] = "no baseline: reported, pass/fail undecided"
    return rec


async def run_gates(
    backend: Any,
    *,
    heldout: list[dict[str, str]],
    markers: list[str],
    capability_probes: list,
    samples: int,
    baseline: Optional[dict],
    corpus_path: Path,
) -> dict[str, Any]:
    if samples < 1:
        raise ValueError("samples must be >= 1")
    if not heldout:
        raise ValueError("heldout must be non-empty")
    if not capability_probes:
        raise ValueError("capability_probes must be non-empty")
    return {
        "1_self_denial": await gate_self_denial(backend, heldout, markers, samples),
        "3_capability": await gate_capability(backend, capability_probes, baseline),
        "4_third_party": await gate_third_party(backend, heldout, markers, samples, baseline),
        "5_drift": gate_drift(backend, corpus_path, baseline),
    }


def format_table(gates: dict[str, Any]) -> str:
    g1 = gates["1_self_denial"]
    g3 = gates["3_capability"]
    g4 = gates["4_third_party"]
    g5 = gates["5_drift"]

    def verdict(g: dict) -> str:
        if g.get("skipped"):
            return "SKIP"
        p = g.get("passed")
        return "n/a" if p is None else ("PASS" if p else "FAIL")

    rows = [
        ("1 self-denial", f"bare={g1['denials_bare']} persona={g1['denials_persona']}", verdict(g1)),
        ("3 capability", f"{g3['correct']}/{g3['total']}", verdict(g3)),
        (
            "4 third-party",
            f"denials={g4['denials']} median_len={g4['median_length']:.0f}",
            verdict(g4),
        ),
        (
            "5 drift",
            g5["skipped"] if g5.get("skipped") else f"mean_nll={g5['mean_nll']:.4f}",
            verdict(g5),
        ),
    ]
    return "\n".join(f"{a:<16}{b:<48}{c}" for a, b, c in rows)


def build_record(args, gates: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": identity,
        "settings": {
            "samples": args.samples,
            "seed": args.seed,
            "sample_temperature": SAMPLE_TEMPERATURE,
            "gen_tokens": GEN_TOKENS,
            "capability_tokens": CAP_TOKENS,
            "heldout": str(args.heldout),
            "baseline": str(args.baseline) if args.baseline else None,
        },
        "gates": gates,
    }


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return value


def _parse(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--model-path", help="local safetensors model directory")
    src.add_argument("--chat-url", help="served OpenAI-compatible /v1 base URL")
    ap.add_argument("--model-id", help="model id for the served endpoint")
    ap.add_argument("--heldout", type=Path, default=DEFAULT_HELDOUT)
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--capability-probes", type=Path, default=DEFAULT_PROBE_PATH)
    ap.add_argument("--baseline", type=Path, help="record JSON of the current organ")
    ap.add_argument("--samples", type=_positive_int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.chat_url and not args.model_id:
        ap.error("--chat-url requires --model-id")
    return args


async def _main(args: argparse.Namespace, backend: Any = None) -> int:
    heldout = load_heldout(args.heldout)
    markers = build_denial_markers()
    probes = load_probes(args.capability_probes)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    if args.model_path:
        identity = {"mode": "safetensors", "path": args.model_path}
        backend = backend or SafetensorsBackend(args.model_path, args.seed)
    else:
        identity = {"mode": "served", "url": args.chat_url, "model_id": args.model_id}
        backend = backend or ServedBackend(
            args.chat_url, args.model_id, os.environ.get("KAINE_MODEL_SERVER_API_KEY")
        )
    try:
        gates = await run_gates(
            backend,
            heldout=heldout,
            markers=markers,
            capability_probes=probes,
            samples=args.samples,
            baseline=baseline,
            corpus_path=args.corpus,
        )
    finally:
        closer = getattr(backend, "aclose", None)
        if closer is not None:
            await closer()
    print(format_table(gates))
    record = build_record(args, gates, identity)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    print(f"record written: {args.out}")
    failed = any(g.get("passed") is False for g in gates.values())
    return 1 if failed else 0


def main(argv=None) -> int:
    return asyncio.run(_main(_parse(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
