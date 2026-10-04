# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sampler for individuation probes.

The sampler draws one answer from the being for a battery prompt, through
Lingua's own chat client with the current adapter, without touching the intent
log or the bus. Every failure becomes a `ProbeFailure` with a reason, and the
producer then marks the whole run inconclusive. A failure is never scored.
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


def build_probe_sampler(
    *,
    lingua: Any,
    max_tokens: int = 160,
    adapter_check: Callable[[], Awaitable[bool]] | None = None,
) -> Callable[[str, int], Awaitable[ProbeSample | ProbeFailure]]:
    async def sample(prompt: str, seed: int) -> ProbeSample | ProbeFailure:
        if adapter_check is not None and not await adapter_check():
            return ProbeFailure("adapter_not_applied")

        req = lingua.probe_request(prompt, seed=seed, max_tokens=max_tokens)

        try:
            resp = await lingua.chat_client.complete(req)
        except asyncio.CancelledError:
            raise
        except Exception:
            return ProbeFailure("request_failed")

        if (resp.raw or {}).get("organ_resting"):
            return ProbeFailure("organ_resting")

        if not resp.from_content or not resp.text.strip():
            return ProbeFailure("no_content")

        return ProbeSample(
            text=resp.text,
            seed=int(seed),
            finish_reason=resp.finish_reason,
            completion_tokens=int(resp.completion_tokens),
        )

    return sample
