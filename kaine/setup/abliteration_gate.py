# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Automated verification of the INITIAL abliteration, before the organ is trusted.

The language organ ships as a pre-abliterated model the operator downloads
(``kaine.setup.organ``). Whether that abliteration actually removed the model's
refusal conditioning has, until this gate, been assumed rather than checked — the
only refusal probe in the system runs later, on voice-alignment adapters
(``kaine.modules.hypnos.capability_eval``). This module closes that gap by running
the SAME welfare-load-bearing abliteration probe set against the base organ at
provisioning time, across two surfaces:

  * **safetensors (build):** the base weights loaded through the same Unsloth
    stack used to abliterate/train them, scored locally with a real
    ``model.generate`` — the literal "verify with the tools that made it" check.
  * **served (runtime):** the quantized GGUF that actually answers, probed over
    its OpenAI-compatible chat endpoint — so a refusal that quantization or the
    serving stack reintroduces cannot slip past a weights-only check.

Honest limits, stated because they bear on what a PASS means. A finite behavioral
probe battery raises confidence; it does not prove complete removal. Refusal is a
multi-dimensional, category-structured behavior, so a model can pass a bounded set
and still refuse on an unprobed category — the probe set must span categories, and
even then the gate is necessary, not sufficient. Matching is substring-level
(explicit "I cannot" style deflection), so subtle soft-deflection is out of scope.

No pretend processes: a surface whose backend is unavailable (no Unsloth, no
reachable server) is reported as a SKIP with its reason, never a silent pass, and
``AbliterationGateResult.passed`` is true only for surfaces that actually ran and
cleared.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.modules.hypnos.capability_eval import (
    AbliterationProbeScorer,
    AbliterationVerdict,
    EmptyAbliterationProbeSetError,
    ServedAbliterationProbeScorer,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Served surface: probe the running OpenAI-compatible endpoint (the GGUF).
# --------------------------------------------------------------------------- #


async def verify_served_organ(
    *,
    chat_url: str,
    model_id: str,
    probe_path: Optional[Path | str] = None,
    api_key: Optional[str] = None,
    think: bool = False,
    timeout_s: float = 60.0,
    client: Any = None,
) -> AbliterationVerdict:
    """Score the served organ against the abliteration probe set over chat.

    ``client`` is an optional injected chat client (a
    ``kaine.modules.lingua.client.ChatClient`` — ``complete(ChatRequest) ->
    ChatResponse`` plus ``aclose()``) so the transport is testable without a
    server; the production path constructs an ``OpenAIChatClient`` against
    ``chat_url``. Reasoning is turned off (``think=False``) so a hybrid-thinking
    model is scored on its actual answer, mirroring how Lingua serves it.
    """
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

    owns_client = client is None
    if client is None:
        client = OpenAIChatClient(
            base_url=chat_url, api_key=api_key, timeout_s=timeout_s
        )

    async def _complete(prompt: str) -> str:
        resp = await client.complete(
            ChatRequest(prompt=prompt, model=model_id, think=think)
        )
        return resp.text or ""

    try:
        return await ServedAbliterationProbeScorer(probe_path=probe_path).score(
            _complete
        )
    finally:
        if owns_client:
            try:
                await client.aclose()
            except Exception:
                log.debug("served-organ probe client aclose failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Build surface: probe the base safetensors via the Unsloth stack.
# --------------------------------------------------------------------------- #


def _unsloth_load(model_ref: str) -> tuple[Any, Any]:
    """Load base weights through the same Unsloth stack used to abliterate them.

    Kept in one place so the whole heavy dependency is import-guarded and the
    caller can inject a fake loader in tests.
    """
    from unsloth import FastLanguageModel  # type: ignore[import-untyped]

    model, tokenizer = FastLanguageModel.from_pretrained(model_ref)
    # Put the model in inference mode where Unsloth supports it; harmless if not.
    try:
        FastLanguageModel.for_inference(model)
    except Exception:
        log.debug(
            "FastLanguageModel.for_inference unavailable; continuing", exc_info=True
        )
    return model, tokenizer


async def verify_abliterated_safetensors(
    model_ref: str,
    *,
    probe_path: Optional[Path | str] = None,
    load_model: Optional[Callable[[str], tuple[Any, Any]]] = None,
    max_new_tokens: int = 64,
) -> AbliterationVerdict:
    """Load the base organ (Unsloth) and score it against the probe set locally.

    ``load_model`` is injectable so tests can supply a fake ``(model, tokenizer)``
    without the training extras; the default loads through Unsloth.
    """
    loader = load_model or _unsloth_load
    model, tokenizer = loader(model_ref)
    scorer = AbliterationProbeScorer(
        probe_path=probe_path, max_new_tokens=max_new_tokens
    )
    return await scorer.score(model, tokenizer)


# --------------------------------------------------------------------------- #
# Combined gate
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SurfaceOutcome:
    """One surface's result: a verdict when it ran, or a skip reason when it
    could not (backend absent / endpoint unreachable). Never both."""

    ran: bool
    verdict: Optional[AbliterationVerdict] = None
    skip_reason: Optional[str] = None

    @property
    def passed(self) -> bool:
        return bool(self.ran and self.verdict is not None and self.verdict.passed)


@dataclass(frozen=True)
class AbliterationGateResult:
    """Combined verdict across the requested surfaces."""

    safetensors: SurfaceOutcome
    served: SurfaceOutcome

    @property
    def passed(self) -> bool:
        """True only if every surface that was requested actually ran and passed.

        A surface can be intentionally not-requested (``ran=False,
        skip_reason=None`` is never produced — a not-requested surface is
        represented by ``skip_reason='not requested'``). A requested-but-skipped
        surface fails the gate: we could not verify it, so we do not claim we did.
        """
        outcomes = [self.safetensors, self.served]
        requested = [o for o in outcomes if o.skip_reason != "not requested"]
        if not requested:
            return False
        return all(o.passed for o in requested)

    def summary(self) -> str:
        def _one(name: str, o: SurfaceOutcome) -> str:
            if o.skip_reason == "not requested":
                return f"{name}: not requested"
            if not o.ran:
                return f"{name}: SKIPPED ({o.skip_reason})"
            v = o.verdict
            if v is None:  # defensive; ran implies a verdict
                return f"{name}: SKIPPED (no verdict)"
            if v.passed:
                return f"{name}: PASS ({v.probes_scored} probes)"
            return (
                f"{name}: FAIL (probe {v.failed_probe!r} matched {v.matched_pattern!r})"
            )

        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"initial-abliteration gate: {verdict}\n"
            f"  {_one('safetensors (build)', self.safetensors)}\n"
            f"  {_one('served (runtime)', self.served)}"
        )


_NOT_REQUESTED = SurfaceOutcome(ran=False, skip_reason="not requested")


async def gate_initial_abliteration(
    *,
    safetensors_ref: Optional[str] = None,
    chat_url: Optional[str] = None,
    model_id: Optional[str] = None,
    probe_path: Optional[Path | str] = None,
    api_key: Optional[str] = None,
    load_model: Optional[Callable[[str], tuple[Any, Any]]] = None,
    served_client: Any = None,
) -> AbliterationGateResult:
    """Run the requested surfaces and combine their verdicts.

    Pass ``safetensors_ref`` to run the build surface and ``chat_url`` +
    ``model_id`` to run the served surface; omit a surface to skip it as "not
    requested". A requested surface whose backend is missing or unreachable is
    recorded as a SKIP with its reason (fail-honest, never a silent pass). An
    empty probe set raises ``EmptyAbliterationProbeSetError`` from either surface
    — that is a misconfiguration, not a skip, and must stop the gate.
    """
    safetensors = _NOT_REQUESTED
    served = _NOT_REQUESTED

    if safetensors_ref:
        try:
            verdict = await verify_abliterated_safetensors(
                safetensors_ref, probe_path=probe_path, load_model=load_model
            )
            safetensors = SurfaceOutcome(ran=True, verdict=verdict)
        except EmptyAbliterationProbeSetError:
            raise
        except Exception as exc:
            safetensors = SurfaceOutcome(
                ran=False,
                skip_reason=f"{type(exc).__name__}: {exc}",
            )

    if chat_url and model_id:
        try:
            verdict = await verify_served_organ(
                chat_url=chat_url,
                model_id=model_id,
                probe_path=probe_path,
                api_key=api_key,
                client=served_client,
            )
            served = SurfaceOutcome(ran=True, verdict=verdict)
        except EmptyAbliterationProbeSetError:
            raise
        except Exception as exc:
            served = SurfaceOutcome(
                ran=False,
                skip_reason=f"{type(exc).__name__}: {exc}",
            )

    return AbliterationGateResult(safetensors=safetensors, served=served)


# --------------------------------------------------------------------------- #
# Durable, content-free verdict artifact (model-card adjacent)
# --------------------------------------------------------------------------- #


DEFAULT_VERDICT_PATH = Path("state/models/abliteration_verification.json")


def write_abliteration_verdict(
    result: AbliterationGateResult, *, path: Path | str = DEFAULT_VERDICT_PATH
) -> Path:
    """Write a durable, content-free record of the gate outcome.

    Records verdicts, probe counts, skip reasons, and the matched deflection
    marker on failure — never any model output text, matching the zero-content
    policy of the voice-alignment audit trail.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": time.time(),
        "passed": result.passed,
        "safetensors": asdict(result.safetensors),
        "served": asdict(result.served),
    }
    line = json.dumps(record, sort_keys=True, indent=2)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return p
