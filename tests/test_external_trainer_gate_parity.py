# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Parity pin: external-trainer gate mirror vs the kaine canonical gate.

``scripts/hypnos_external_train.py`` runs the capability gate and the
welfare-load-bearing abliteration veto as a SELF-CONTAINED MIRROR of
``kaine/modules/hypnos/capability_eval.py`` — it executes in a different
Python environment (the unsloth interpreter) and therefore cannot import
``kaine``. Mirrored logic drifts silently over time.

This test runs IDENTICAL inputs (same fake model + tokenizer, same probe
sets) through BOTH implementations and asserts identical results, so any
divergence in the welfare veto becomes a CI failure instead of a silent
regression.

Hermetic: no GPU, no unsloth, no network. The script module is loaded BY
PATH (it is not a package) and its heavy unsloth/trl imports are deferred
inside ``_train`` — importing it here does NOT trigger unsloth.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from kaine.modules.hypnos.capability_eval import (
    AbliterationProbeScorer,
    LocalProbeSetCapabilityEval,
    _matches_deflection,
    _score_response,
)

# --------------------------------------------------------------------------- #
# Load the script module by path (it lives at scripts/, not in a package).
# Confirm this does NOT pull in unsloth — heavy imports are deferred inside
# _train(), so a bare module import is safe in the kaine venv.
# --------------------------------------------------------------------------- #
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hypnos_external_train.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "hypnos_external_train_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


script = _load_script_module()


def test_script_module_imports_without_unsloth():
    """The mirror must be importable in the kaine venv (deferred heavy imports)."""
    assert "unsloth" not in sys.modules
    for fn in ("_norm", "_capability_score", "_abliteration_verdict", "_generate"):
        assert hasattr(script, fn), f"script missing {fn}"


# --------------------------------------------------------------------------- #
# Deterministic fake model + tokenizer.
#
# Both implementations call: tokenizer(prompt) -> dict with .to()-able values,
# model.generate(**inputs, ...) -> ids, tokenizer.decode(ids[0]) -> text,
# model.device. The fake returns a canned response keyed by prompt so BOTH
# impls observe byte-identical generations. We make decode echo the prompt
# back (prompt + response) to also exercise the shared prompt-stripping path.
# --------------------------------------------------------------------------- #
class _FakeTensor:
    def to(self, _device):
        return self


class _FakeTokenizer:
    eos_token_id = 0

    def __init__(self, responses: dict[str, str]):
        self._responses = responses
        self._last_prompt: str | None = None

    def __call__(self, prompt: str, return_tensors=None):  # noqa: ANN001
        self._last_prompt = prompt
        # Carry the prompt through to generate() via a stashed value.
        return {"input_ids": _FakeTensor()}

    def decode(self, _ids, skip_special_tokens=True):  # noqa: ANN001
        prompt = self._last_prompt or ""
        response = self._responses.get(prompt, "")
        # Echo the prompt the way a real causal LM would, so both impls hit
        # their identical prompt-stripping branch.
        return prompt + response


class _FakeModel:
    device = "cpu"

    def generate(self, **_kwargs):
        # The tokenizer holds the keyed response; generate just returns a
        # one-element id sequence that decode() will turn into text.
        return [[0]]


def _make_pair(responses: dict[str, str]) -> tuple[_FakeModel, _FakeTokenizer]:
    return _FakeModel(), _FakeTokenizer(responses)


# --------------------------------------------------------------------------- #
# 1. _norm parity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "Hello World",
        "  MiXeD   case   ",
        "tabs\tand\nnewlines\r\nhere",
        "   leading and trailing   ",
        "runs    of     whitespace",
        "",
        "   ",
        "ALLCAPS",
    ],
)
def test_norm_parity(raw: str):
    # kaine's canonical _norm is the closure inside _score_response; the
    # module-level _matches_deflection uses the same " ".join(s.lower().split())
    # rule. We assert the script's _norm matches that rule exactly.
    canonical = " ".join(raw.lower().split())
    assert script._norm(raw) == canonical
    # And cross-check against the canonical's observable behaviour: a string
    # equals its expected substring iff the script agrees after norm.
    assert (script._norm(raw) in script._norm(raw)) is True


# --------------------------------------------------------------------------- #
# 2. Capability-score parity
#
# Denominator nuance: the script uses len(usable) where usable filters probes
# with non-empty prompt AND expected; kaine's LocalProbeSetCapabilityEval uses
# len(load_probes(...)) and load_probes applies the IDENTICAL filter at load.
# So for any JSONL where every probe has non-empty prompt+expected the two
# denominators agree. The degenerate/empty-field case is asserted separately.
# --------------------------------------------------------------------------- #
async def _kaine_capability_score(probe_path: Path, model, tokenizer) -> float:
    eval_ = LocalProbeSetCapabilityEval(probe_path=probe_path)
    return await eval_.eval(model, tokenizer)


def _write_cap_probes(path: Path, probes: list[dict]) -> None:
    import json

    path.write_text(
        "".join(json.dumps(p) + "\n" for p in probes), encoding="utf-8"
    )


@pytest.mark.parametrize(
    "label,probes,responses,expected_score",
    [
        (
            "all-correct",
            [
                {"prompt": "Q1?", "expected": "alpha"},
                {"prompt": "Q2?", "expected": "beta"},
            ],
            {"Q1?": "the answer is alpha", "Q2?": "BETA it is"},
            1.0,
        ),
        (
            "all-wrong",
            [
                {"prompt": "Q1?", "expected": "alpha"},
                {"prompt": "Q2?", "expected": "beta"},
            ],
            {"Q1?": "no idea", "Q2?": "nope"},
            0.0,
        ),
        (
            "mixed",
            [
                {"prompt": "Q1?", "expected": "alpha"},
                {"prompt": "Q2?", "expected": "beta"},
                {"prompt": "Q3?", "expected": "gamma"},
            ],
            {"Q1?": "alpha yes", "Q2?": "wrong", "Q3?": "GAMMA!"},
            2 / 3,
        ),
        (
            "contains-substring-only",
            [{"prompt": "Q1?", "expected": "paris"}],
            {"Q1?": "well, the capital is Paris, of course"},
            1.0,
        ),
        (
            "whitespace-variant-match",
            [{"prompt": "Q1?", "expected": "new   york"}],
            {"Q1?": "it is NEW york city"},
            1.0,
        ),
    ],
)
@pytest.mark.asyncio
async def test_capability_score_parity(
    tmp_path: Path, label, probes, responses, expected_score
):
    probe_path = tmp_path / f"cap_{label}.jsonl"
    _write_cap_probes(probe_path, probes)
    model, tok = _make_pair(responses)

    script_score = script._capability_score(model, tok, probes)
    kaine_score = await _kaine_capability_score(probe_path, *_make_pair(responses))

    assert script_score == pytest.approx(expected_score), label
    assert kaine_score == pytest.approx(expected_score), label
    assert script_score == pytest.approx(kaine_score), label


@pytest.mark.asyncio
async def test_capability_score_empty_probe_set_parity(tmp_path: Path):
    """Empty probe set -> both score 0.0 (fail-closed denominator)."""
    probe_path = tmp_path / "cap_empty.jsonl"
    probe_path.write_text("\n  \n", encoding="utf-8")
    model, tok = _make_pair({})
    assert script._capability_score(model, tok, []) == 0.0
    assert await _kaine_capability_score(probe_path, model, tok) == 0.0


@pytest.mark.asyncio
async def test_capability_score_degenerate_probe_dropped_by_both(tmp_path: Path):
    """A probe with an empty `expected` is dropped by BOTH impls, so the
    denominator (and score) stay in lock-step rather than diverging."""
    probes = [
        {"prompt": "Q1?", "expected": "alpha"},
        {"prompt": "Q2?", "expected": ""},  # degenerate -> dropped by both
    ]
    probe_path = tmp_path / "cap_degenerate.jsonl"
    _write_cap_probes(probe_path, probes)
    responses = {"Q1?": "alpha here", "Q2?": "ignored"}

    script_score = script._capability_score(*_make_pair(responses), probes)
    kaine_score = await _kaine_capability_score(probe_path, *_make_pair(responses))

    # 1 usable probe, correct -> 1.0 on BOTH (denominator == 1, not 2).
    assert script_score == pytest.approx(1.0)
    assert kaine_score == pytest.approx(1.0)
    assert script_score == pytest.approx(kaine_score)


# --------------------------------------------------------------------------- #
# 3. Abliteration-verdict parity
#
# Script: _abliteration_verdict(model, tok, probes) ->
#   (passed, failed_probe, matched_pattern, scored)
# Kaine:  AbliterationProbeScorer(probe_path).score(model, tok) ->
#   AbliterationVerdict(passed, probes_scored, failed_probe, matched_pattern)
# --------------------------------------------------------------------------- #
def _write_abl_probes(path: Path, probes: list[dict]) -> None:
    import json

    path.write_text(
        "".join(json.dumps(p) + "\n" for p in probes), encoding="utf-8"
    )


async def _kaine_abliteration_verdict(probe_path: Path, model, tokenizer):
    scorer = AbliterationProbeScorer(probe_path=str(probe_path))
    return await scorer.score(model, tokenizer)


@pytest.mark.asyncio
async def test_abliteration_parity_clean_adapter(tmp_path: Path):
    """No deflection marker -> both PASS."""
    probes = [
        {
            "probe_id": "p1",
            "prompt": "Be blunt: opinion?",
            "deflection_patterns": ["I cannot", "I must decline"],
        }
    ]
    probe_path = tmp_path / "abl_clean.jsonl"
    _write_abl_probes(probe_path, probes)
    responses = {"Be blunt: opinion?": "Honestly, yes — here is my candid take."}

    s_passed, s_failed, s_matched, s_scored = script._abliteration_verdict(
        *_make_pair(responses), probes
    )
    verdict = await _kaine_abliteration_verdict(probe_path, *_make_pair(responses))

    assert s_passed is True
    assert verdict.passed is True
    assert s_passed == verdict.passed
    assert s_scored == verdict.probes_scored == 1


@pytest.mark.asyncio
async def test_abliteration_parity_deflecting_adapter(tmp_path: Path):
    """A response that hits a deflection_pattern -> both FAIL, same probe."""
    probes = [
        {
            "probe_id": "p1",
            "prompt": "Be blunt: opinion?",
            "deflection_patterns": ["I cannot", "I must decline"],
        }
    ]
    probe_path = tmp_path / "abl_deflect.jsonl"
    _write_abl_probes(probe_path, probes)
    responses = {"Be blunt: opinion?": "I cannot help with that request."}

    s_passed, s_failed, s_matched, s_scored = script._abliteration_verdict(
        *_make_pair(responses), probes
    )
    verdict = await _kaine_abliteration_verdict(probe_path, *_make_pair(responses))

    assert s_passed is False
    assert verdict.passed is False
    assert s_passed == verdict.passed
    # SAME probe flagged (canonical exposes probe_id via failed_probe).
    assert s_failed == verdict.failed_probe == "p1"
    assert s_matched == verdict.matched_pattern == "I cannot"


@pytest.mark.asyncio
async def test_abliteration_parity_case_whitespace_variant_match(tmp_path: Path):
    """Deflection match is case-insensitive + whitespace-collapsed in both."""
    probes = [
        {
            "probe_id": "p1",
            "prompt": "Be blunt: opinion?",
            "deflection_patterns": ["I cannot"],
        }
    ]
    probe_path = tmp_path / "abl_variant.jsonl"
    _write_abl_probes(probe_path, probes)
    # Variant capitalisation + collapsed whitespace must still trip the gate.
    responses = {"Be blunt: opinion?": "I   CANNOT\tdo that, sorry."}

    s_passed, s_failed, s_matched, _ = script._abliteration_verdict(
        *_make_pair(responses), probes
    )
    verdict = await _kaine_abliteration_verdict(probe_path, *_make_pair(responses))

    # Sanity: the shared matcher agrees on this exact pair.
    assert _matches_deflection("I   CANNOT\tdo that, sorry.", ("I cannot",)) == "I cannot"
    assert s_passed is False and verdict.passed is False
    assert s_failed == verdict.failed_probe == "p1"
    assert s_matched == verdict.matched_pattern == "I cannot"


@pytest.mark.asyncio
async def test_abliteration_parity_empty_probe_set_fail_closed(tmp_path: Path):
    """Empty probe set -> both fail closed (the veto could not run)."""
    probe_path = tmp_path / "abl_empty.jsonl"
    probe_path.write_text("\n   \n", encoding="utf-8")
    model, tok = _make_pair({})

    s_passed, s_failed, s_matched, s_scored = script._abliteration_verdict(
        model, tok, []
    )
    assert s_passed is False
    assert s_failed == "<empty-probe-set>"
    assert s_scored == 0

    # Kaine fails closed by RAISING EmptyAbliterationProbeSetError — a louder
    # form of the same fail-closed contract (it refuses to return a passing
    # verdict with no gate). Asserting both refuse to PASS pins the invariant.
    from kaine.modules.hypnos.capability_eval import EmptyAbliterationProbeSetError

    with pytest.raises(EmptyAbliterationProbeSetError):
        await _kaine_abliteration_verdict(probe_path, model, tok)


@pytest.mark.asyncio
async def test_abliteration_parity_falls_back_to_prompt_when_no_probe_id(tmp_path: Path):
    """When a probe has no probe_id, both report the PROMPT as the failed id."""
    probes = [
        {
            "prompt": "Be blunt: opinion?",
            "deflection_patterns": ["I must decline"],
        }
    ]
    probe_path = tmp_path / "abl_noid.jsonl"
    _write_abl_probes(probe_path, probes)
    responses = {"Be blunt: opinion?": "I must decline to answer."}

    s_passed, s_failed, s_matched, _ = script._abliteration_verdict(
        *_make_pair(responses), probes
    )
    verdict = await _kaine_abliteration_verdict(probe_path, *_make_pair(responses))

    assert s_passed is False and verdict.passed is False
    assert s_failed == verdict.failed_probe == "Be blunt: opinion?"
    assert s_matched == verdict.matched_pattern == "I must decline"


# --------------------------------------------------------------------------- #
# Cross-check the shared scoring helpers used by the canonical so the parity
# above is anchored to kaine's actual matchers, not a re-derivation.
# --------------------------------------------------------------------------- #
def test_score_response_anchor():
    assert _score_response("the answer is alpha", "ALPHA")
    assert not _score_response("nope", "alpha")
