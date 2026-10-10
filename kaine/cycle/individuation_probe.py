# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sampler for individuation probes.

The sampler draws one answer from the being for a battery prompt, through
Lingua's own chat client with the current adapter, without touching the intent
log or the bus. The persona and conditioning digest are taken from the same
self-model snapshot; if the snapshot has not arrived, or a required disclosure
fact is missing, the run is marked inconclusive. Every failure becomes a
ProbeFailure with a reason, and the producer then marks the whole run
inconclusive. A failure is never scored.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine.lifecycle.individuation_store import ProbeSample


@dataclass(frozen=True)
class ProbeFailure:
    reason: str


async def adapter_applied(*, adapter_output_dir: Path | None, resolver: Any | None) -> bool:
    if adapter_output_dir is None:
        return True

    from kaine.modules.hypnos.adapter_store import current_path

    current = current_path(adapter_output_dir)
    if current is None:
        return True

    if resolver is None:
        return False

    try:
        field = await resolver.lora_field()
    except Exception:
        return False

    return field is not None


def adapter_expected_from(adapter_output_dir: Path | None) -> Callable[[], bool]:
    """Return a callable that is True when a current adapter.gguf exists.

    The returned callable is suitable for the ``adapter_expected`` argument of
    :func:`build_probe_sampler`: True means the being should be using its
    adapter, so a response without ``lora_applied`` is a failure.
    """
    def _check() -> bool:
        if adapter_output_dir is None:
            return False
        from kaine.modules.hypnos.adapter_store import current_path
        current = current_path(adapter_output_dir)
        if current is None:
            return False
        return (current / "adapter.gguf").is_file()

    return _check


def build_probe_sampler(
    *,
    lingua: Any,
    max_tokens: int = 160,
    adapter_check: Callable[[], Awaitable[bool]] | None = None,
    required_fact: str | None = None,
    adapter_expected: Callable[[], bool] | None = None,
) -> Callable[[str, int], Awaitable[ProbeSample | ProbeFailure]]:
    async def sample(prompt: str, seed: int) -> ProbeSample | ProbeFailure:
        if adapter_check is not None:
            try:
                check_result = await adapter_check()
            except Exception:
                return ProbeFailure("adapter_not_applied")
            if not check_result:
                return ProbeFailure("adapter_not_applied")

        sm = lingua.probe_self_model()
        if sm is None:
            return ProbeFailure("self_model_not_ready")
        if required_fact is not None and required_fact not in (
            sm.get("situation_facts") or []
        ):
            return ProbeFailure("disclosure_not_ready")

        try:
            req = lingua.probe_request(
                prompt, seed=seed, max_tokens=max_tokens, self_model=sm
            )
            resp = await lingua.chat_client.complete(req)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ProbeFailure("request_failed")

        if (resp.raw or {}).get("organ_resting"):
            return ProbeFailure("organ_resting")

        if not resp.from_content or not resp.text.strip():
            return ProbeFailure("no_content")

        if adapter_expected is not None:
            try:
                expected = adapter_expected()
            except Exception:
                return ProbeFailure("adapter_not_applied")
            if expected and not resp.lora_applied:
                return ProbeFailure("adapter_not_applied")

        return ProbeSample(
            text=resp.text,
            seed=int(seed),
            finish_reason=resp.finish_reason,
            completion_tokens=int(resp.completion_tokens),
        )

    return sample
