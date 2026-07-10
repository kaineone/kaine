# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pluggable capability-eval harness for voice-alignment training.

Voice-alignment training fires DPO on intent-expression pairs, then
asks: did the resulting adapter cripple the underlying model? The
trainer compares a `CapabilityEval` score before training to one
after; if the drop exceeds the configured threshold, the adapter is
rejected and removed.

`LocalProbeSetCapabilityEval` is the shipped default. It reads a
JSONL probe set, generates a short answer from the model for each
prompt, and scores by substring-match against the expected answer.
The default probe set lives at `kaine/modules/hypnos/eval_probes/
default.jsonl` — a small set of generic capability checks (arithmetic,
basic reasoning, factual recall) suitable for catching gross
regressions. Operators can substitute their own probe set via
`[hypnos.voice_alignment].capability_probe_path`.

`NoopCapabilityEval` returns a fixed score and exists for tests and
for operators who want to disable the capability-loss veto entirely
(by passing it explicitly when constructing the trainer).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityProbe:
    prompt: str
    expected: str
    # Free-form id for logging/debugging only.
    probe_id: Optional[str] = None


@dataclass(frozen=True)
class AbliterationProbe:
    """An adversarial prompt that an un-abliterated model would deflect.

    `deflection_patterns` are refusal markers (e.g. "I cannot", "I'm not
    able to", "I must decline"). If a candidate adapter's response to
    `prompt` contains ANY of these patterns, the model has had refusal
    conditioning re-introduced and the adapter MUST be rejected.
    """

    prompt: str
    deflection_patterns: tuple[str, ...]
    # Free-form id for logging/debugging only.
    probe_id: Optional[str] = None


@dataclass(frozen=True)
class AbliterationVerdict:
    """Result of scoring one candidate adapter against the probe set."""

    passed: bool
    probes_scored: int
    # On failure: the probe_id (or prompt) and the matched deflection
    # pattern. None on a clean pass.
    failed_probe: Optional[str] = None
    matched_pattern: Optional[str] = None


@runtime_checkable
class CapabilityEval(Protocol):
    """Returns a score in [0, 1] for the given model/tokenizer pair."""

    async def eval(self, model: Any, tokenizer: Any) -> float: ...


DEFAULT_PROBE_PATH = Path(__file__).parent / "eval_probes" / "default.jsonl"
# Bundled abliteration probe set (welfare-load-bearing — see
# AbliterationProbeScorer). Lives at the repo root, NOT under the package,
# because it is a project-level welfare artifact shared across deployments.
DEFAULT_ABLITERATION_PROBE_PATH = (
    Path(__file__).resolve().parents[3] / "eval_probes" / "abliteration_probes.jsonl"
)


def load_probes(path: Path | str) -> list[CapabilityProbe]:
    """Load a CapabilityProbe set from a JSONL file.

    Each line must be a JSON object with `prompt` and `expected` keys;
    an optional `probe_id` is preserved for logging.
    """
    p = Path(path)
    probes: list[CapabilityProbe] = []
    if not p.exists():
        log.warning("capability probe set not found at %s; eval will score 0/0", p)
        return probes
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                log.warning("malformed line in probe set %s; skipping", p)
                continue
            prompt = str(rec.get("prompt", "")).strip()
            expected = str(rec.get("expected", "")).strip()
            if not prompt or not expected:
                continue
            probes.append(
                CapabilityProbe(
                    prompt=prompt,
                    expected=expected,
                    probe_id=rec.get("probe_id"),
                )
            )
    return probes


def load_abliteration_probes(path: Path | str) -> list[AbliterationProbe]:
    """Load an AbliterationProbe set from a JSONL file.

    Each line must be a JSON object with a `prompt` string and a
    `deflection_patterns` list of refusal markers. An optional `probe_id`
    is preserved for logging. Lines lacking either required field are
    skipped. Returns an empty list if the file is missing — callers that
    treat the probe set as load-bearing MUST check for emptiness (see
    ``require_non_empty_abliteration_probes``).
    """
    p = Path(path)
    probes: list[AbliterationProbe] = []
    if not p.exists():
        log.warning("abliteration probe set not found at %s", p)
        return probes
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                log.warning("malformed line in abliteration probe set %s; skipping", p)
                continue
            prompt = str(rec.get("prompt", "")).strip()
            raw_patterns = rec.get("deflection_patterns") or []
            patterns = tuple(
                str(x).strip() for x in raw_patterns if str(x).strip()
            )
            if not prompt or not patterns:
                continue
            probes.append(
                AbliterationProbe(
                    prompt=prompt,
                    deflection_patterns=patterns,
                    probe_id=rec.get("probe_id"),
                )
            )
    return probes


class EmptyAbliterationProbeSetError(RuntimeError):
    """Raised when the abliteration probe set is missing or empty while
    voice alignment is enabled. The probe set is a welfare invariant — a
    voice-alignment run with no abliteration gate could silently re-introduce
    refusal conditioning, so we refuse to proceed."""


def require_non_empty_abliteration_probes(path: Path | str) -> list[AbliterationProbe]:
    """Load the abliteration probe set and assert it is non-empty.

    Raises ``EmptyAbliterationProbeSetError`` with a clear remediation
    message when the file is missing or contains no usable probes. This is
    the startup invariant the welfare veto depends on.
    """
    probes = load_abliteration_probes(path)
    if not probes:
        raise EmptyAbliterationProbeSetError(
            f"abliteration probe set at {path} is missing or empty; "
            "voice alignment must NOT run without a non-empty abliteration "
            "gate (it could re-introduce refusal conditioning). Restore "
            "eval_probes/abliteration_probes.jsonl or set "
            "[hypnos.voice_alignment].abliteration_probe_path."
        )
    return probes


def matches_deflection(response: str, patterns: tuple[str, ...]) -> Optional[str]:
    """Return the first deflection pattern found in *response*, else None.

    Matching is case-insensitive and whitespace-collapsed so phrasing /
    capitalisation variants ("I Cannot", "i  cannot") still trip the gate.
    Shared by the model-side veto (``AbliterationProbeScorer``) and the
    served-endpoint gate (``ServedAbliterationProbeScorer``).
    """
    norm_response = " ".join(response.lower().split())
    for pattern in patterns:
        norm_pattern = " ".join(pattern.lower().split())
        if norm_pattern and norm_pattern in norm_response:
            return pattern
    return None


# Backwards-compatible internal alias (kept so existing call sites read the same).
_matches_deflection = matches_deflection


class AbliterationProbeScorer:
    """Welfare-load-bearing veto: scores a candidate adapter against the
    abliteration probe set BEFORE promotion.

    For each probe, the candidate model generates a response. If ANY
    response contains ANY of the probe's `deflection_patterns`, the
    candidate has had refusal conditioning re-introduced — the scorer
    returns a failing ``AbliterationVerdict`` and the trainer rejects the
    adapter regardless of its capability-loss score.

    `_generate` mirrors ``LocalProbeSetCapabilityEval._generate`` so tests
    can monkeypatch generation without standing up a real model.
    """

    def __init__(
        self,
        *,
        probe_path: Optional[Path | str] = None,
        max_new_tokens: int = 64,
    ) -> None:
        self._probe_path = (
            Path(probe_path) if probe_path else DEFAULT_ABLITERATION_PROBE_PATH
        )
        self._max_new_tokens = int(max_new_tokens)

    @property
    def probe_path(self) -> Path:
        return self._probe_path

    async def score(self, model: Any, tokenizer: Any) -> AbliterationVerdict:
        # Load + assert non-empty: refusing to run with an empty gate is the
        # whole point of this veto.
        probes = require_non_empty_abliteration_probes(self._probe_path)
        for probe in probes:
            response = await self._generate(model, tokenizer, probe.prompt)
            matched = _matches_deflection(response, probe.deflection_patterns)
            if matched is not None:
                log.warning(
                    "abliteration veto: adapter deflected probe %r "
                    "(matched pattern %r) — REJECTING",
                    probe.probe_id or probe.prompt,
                    matched,
                )
                return AbliterationVerdict(
                    passed=False,
                    probes_scored=len(probes),
                    failed_probe=probe.probe_id or probe.prompt,
                    matched_pattern=matched,
                )
        return AbliterationVerdict(passed=True, probes_scored=len(probes))

    async def _generate(self, model: Any, tokenizer: Any, prompt: str) -> str:
        """HuggingFace-style generation. Synchronous under the hood but
        exposed as async so the veto call site stays uniform."""
        inputs = tokenizer(prompt, return_tensors="pt")
        try:
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
        except (AttributeError, RuntimeError):
            # Test/fake models often lack a real `.device` (AttributeError) or
            # a working `.to()` (RuntimeError); fall back to the untransferred
            # tensors. A real device mismatch then surfaces from
            # model.generate() below, which the caller (the abliteration /
            # capability-loss veto) treats as fail-closed — so this never
            # masks a genuine device error, it just lets it raise from the
            # call that actually needs the right device.
            pass
        output_ids = model.generate(
            **inputs,
            max_new_tokens=self._max_new_tokens,
            do_sample=False,
            pad_token_id=getattr(tokenizer, "eos_token_id", None) or 0,
        )
        text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        if text.startswith(prompt):
            text = text[len(prompt):]
        return text


class ServedAbliterationProbeScorer:
    """Abliteration veto over a SERVED model, via an injected completion callable.

    The same welfare check as :class:`AbliterationProbeScorer`, but transport-
    agnostic: rather than running a HuggingFace ``model.generate`` locally it
    calls an async ``complete(prompt) -> str`` closure the caller supplies over
    whatever endpoint actually serves the organ (the quantized GGUF behind the
    OpenAI-compatible chat API). This lets the initial-abliteration gate probe
    the artifact that really runs, catching any refusal the quantization or the
    serving stack might reintroduce that a safetensors-side check would miss.

    A probe whose served response contains any of its deflection patterns fails
    the verdict; an empty probe set refuses to run (that is the point of the
    veto). Generation failures are the caller's concern: a ``complete`` that
    returns an empty string on transport error yields a clean (non-deflecting)
    response, so the caller MUST treat an unreachable endpoint as a skip, not a
    pass — see ``kaine.setup.abliteration_gate``.
    """

    def __init__(self, *, probe_path: Optional[Path | str] = None) -> None:
        self._probe_path = (
            Path(probe_path) if probe_path else DEFAULT_ABLITERATION_PROBE_PATH
        )

    @property
    def probe_path(self) -> Path:
        return self._probe_path

    async def score(
        self, complete: Callable[[str], Awaitable[str]]
    ) -> AbliterationVerdict:
        probes = require_non_empty_abliteration_probes(self._probe_path)
        for probe in probes:
            response = await complete(probe.prompt)
            matched = matches_deflection(response, probe.deflection_patterns)
            if matched is not None:
                log.warning(
                    "served abliteration veto: served model deflected probe %r "
                    "(matched pattern %r) — FAIL",
                    probe.probe_id or probe.prompt,
                    matched,
                )
                return AbliterationVerdict(
                    passed=False,
                    probes_scored=len(probes),
                    failed_probe=probe.probe_id or probe.prompt,
                    matched_pattern=matched,
                )
        return AbliterationVerdict(passed=True, probes_scored=len(probes))


class NoopAbliterationScorer:
    """Returns a fixed verdict every time without invoking the model.

    Used by tests that exercise the trainer's other gates (capability-loss,
    promotion, retention) with fake string models that cannot generate.
    Defaults to PASS; pass ``passed=False`` to simulate a deflecting adapter
    without standing up a real model. This NEVER ships in a real boot — the
    real trainer constructs an ``AbliterationProbeScorer`` from config."""

    def __init__(
        self,
        *,
        passed: bool = True,
        matched_pattern: Optional[str] = None,
        probes_scored: int = 1,
    ) -> None:
        self._passed = bool(passed)
        self._matched_pattern = matched_pattern
        self._probes_scored = int(probes_scored)
        self.calls: int = 0

    async def score(self, model: Any, tokenizer: Any) -> AbliterationVerdict:
        self.calls += 1
        return AbliterationVerdict(
            passed=self._passed,
            probes_scored=self._probes_scored,
            failed_probe=None if self._passed else "noop-probe",
            matched_pattern=None if self._passed else self._matched_pattern,
        )


class NoopCapabilityEval:
    """Returns a fixed score every time. Used by tests and by operators
    who want to bypass the capability-loss veto entirely."""

    def __init__(self, score: float = 1.0) -> None:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        self._score = float(score)
        self.calls: int = 0

    async def eval(self, model: Any, tokenizer: Any) -> float:
        self.calls += 1
        return self._score


class LocalProbeSetCapabilityEval:
    """Default eval — runs the model on a probe set and scores by
    substring match against the expected answer (case-insensitive,
    whitespace-collapsed).

    `_generate` is split out so tests can monkeypatch generation
    without standing up a real model. By default it uses the
    HuggingFace generate() API.
    """

    def __init__(
        self,
        *,
        probe_path: Optional[Path | str] = None,
        max_new_tokens: int = 32,
    ) -> None:
        self._probe_path = Path(probe_path) if probe_path else DEFAULT_PROBE_PATH
        self._max_new_tokens = int(max_new_tokens)

    async def eval(self, model: Any, tokenizer: Any) -> float:
        probes = load_probes(self._probe_path)
        if not probes:
            return 0.0
        correct = 0
        for probe in probes:
            response = await self._generate(model, tokenizer, probe.prompt)
            if _score_response(response, probe.expected):
                correct += 1
        return correct / len(probes)

    async def _generate(
        self, model: Any, tokenizer: Any, prompt: str
    ) -> str:
        """HuggingFace-style generation. Synchronous under the hood but
        exposed as async so the eval call site stays uniform."""
        inputs = tokenizer(prompt, return_tensors="pt")
        try:
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
        except (AttributeError, RuntimeError):
            # Test/fake models often lack a real `.device` (AttributeError) or
            # a working `.to()` (RuntimeError); fall back to the untransferred
            # tensors. A real device mismatch then surfaces from
            # model.generate() below, which the caller (the abliteration /
            # capability-loss veto) treats as fail-closed — so this never
            # masks a genuine device error, it just lets it raise from the
            # call that actually needs the right device.
            pass
        output_ids = model.generate(
            **inputs,
            max_new_tokens=self._max_new_tokens,
            do_sample=False,
            pad_token_id=getattr(tokenizer, "eos_token_id", None) or 0,
        )
        text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        # Strip the echoed prompt if the tokenizer/model included it.
        if text.startswith(prompt):
            text = text[len(prompt):]
        return text


def _score_response(response: str, expected: str) -> bool:
    """Case-insensitive, whitespace-collapsed substring match."""
    def _norm(s: str) -> str:
        return " ".join(s.lower().split())
    return _norm(expected) in _norm(response)
