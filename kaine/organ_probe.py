# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Organ checks the runtime needs: the content gate and the revision reader.

They live here, not in ``kaine.setup``, so the boot and cycle packages can use
them without importing install-time code. ``kaine.setup.organ`` writes the revision
state the reader reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from kaine.storage import resolve

# Wall-clock ceiling for the content probe. Unlike verify_served_alias (a cheap
# /models list), this runs a REAL generation, so it gets a more generous default.
CONTENT_PROBE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class OrganContentResult:
    """Whether the served organ actually GENERATES non-empty content."""

    ok: bool
    detail: str
    sample: str = ""


async def verify_organ_generates(
    chat_url: str,
    model_id: str,
    *,
    api_key: Optional[str] = None,
    timeout_s: float = CONTENT_PROBE_TIMEOUT_S,
    client: Any = None,
) -> OrganContentResult:
    """Boot-time CONTENT gate: confirm the served organ returns NON-EMPTY text.

    ``verify_served_alias`` proves the server *lists* the right name; this proves
    the served model actually SPEAKS. A hybrid-thinking model whose chain-of-
    thought is not suppressed reasons to exhaustion and returns empty ``content``
    — it passes the alias check yet leaves the entity voiceless (the exact failure
    this gate exists to catch). So the gate sends one real completion through the
    production Lingua client (thinking suppressed by the organ default
    ``think=False``) and checks the visible text is non-empty.

    Never raises: an unreachable / erroring / mute organ returns ``ok=False`` with
    a remediation ``detail`` so the caller owns the boot policy. ``client`` is an
    optional injected chat client (duck-typed ``complete`` / ``aclose``) for tests.
    """
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

    own_client = client is None
    if own_client:
        client = OpenAIChatClient(base_url=chat_url, api_key=api_key, timeout_s=timeout_s)
    try:
        resp = await client.complete(
            ChatRequest(
                prompt="Reply with a single short word.",
                model=model_id,
                max_tokens=64,
            )
        )
    except Exception as exc:  # report ANY failure as a gate miss, never propagate
        return OrganContentResult(
            ok=False,
            detail=(
                f"organ '{model_id}' did not respond at {chat_url} "
                f"({type(exc).__name__}: {exc})"
            ),
        )
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception:
                # Best-effort teardown of a locally-created client; the
                # gate's own contract ("Never raises") already committed to
                # returning a result above regardless of transport cleanup,
                # and there's no result field to attach a close failure to.
                pass

    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        return OrganContentResult(
            ok=False,
            detail=(
                f"organ '{model_id}' is SERVED but MUTE — returned empty content. "
                "Most likely its chain-of-thought is not suppressed (the model "
                "reasons to exhaustion and emits no visible answer). Verify the "
                "Lingua client sends chat_template_kwargs.enable_thinking=false."
            ),
        )
    return OrganContentResult(
        ok=True,
        detail=(
            f"organ '{model_id}' generates content "
            f"({getattr(resp, 'completion_tokens', 0)} tok, "
            f"{round(getattr(resp, 'latency_ms', 0.0))}ms)"
        ),
        sample=text[:80],
    )


# Where the downloader records the resolved organ revision(s) so the cycle's
# run-manifest provenance path can pin the exact published snapshot. JSON map of
# ``<repo> -> <sha>``; optional/best-effort (a missing file never crashes boot).
ORGAN_REVISION_STATE_PATH = "state/model-server/organ_revisions.json"


def read_revision_state(path: Optional[str] = None) -> dict[str, str]:
    """Read the resolved organ revision map for provenance. ``{}`` if absent."""
    target = resolve(path or ORGAN_REVISION_STATE_PATH)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}
