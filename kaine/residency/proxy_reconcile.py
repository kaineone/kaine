# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging

import httpx

from kaine.residency.ledger import Ledger, State

logger = logging.getLogger(__name__)


async def query_proxy_models(base_url: str) -> dict[str, str]:
    """Query llama-swap for loaded model status.

    Calls GET {base_url}/api/models/status
    Returns a dict mapping model alias to status string (e.g. "loaded", "idle").
    On connection error or non-200 response, returns empty dict and logs a warning.
    Uses httpx.AsyncClient with timeout=5.0 and trust_env=False.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.get(f"{base_url}/api/models/status")
            if resp.status_code != 200:
                logger.warning(
                    "proxy status returned %d", resp.status_code,
                )
                return {}
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("proxy status query failed: %s", exc)
        return {}


async def unload_proxy_model(base_url: str, model: str) -> bool:
    """Ask llama-swap to unload a specific model.

    Calls POST {base_url}/api/models/unload/{model}
    Returns True on success (2xx), False on any error.
    Uses httpx.AsyncClient with timeout=10.0 and trust_env=False.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(f"{base_url}/api/models/unload/{model}")
            if resp.is_success:
                return True
            logger.warning("proxy unload %s returned %d", model, resp.status_code)
            return False
    except httpx.HTTPError as exc:
        logger.warning("proxy unload %s failed: %s", model, exc)
        return False


async def reconcile_proxy(
    ledger: Ledger,
    base_url: str,
    llm_proxy: str,
) -> None:
    """Sync ledger state with the llama-swap proxy.

    When llm_proxy is "none", returns immediately (no-op).
    When llm_proxy is "llama-swap":
    1. Query proxy for loaded models.
    2. For each model the proxy reports as "loaded":
       - If the ledger entry is COLD or ABSENT, call ledger.mark_resident(name).
    3. For each model in the ledger that is RESIDENT but NOT reported by the proxy
       (or reported as not "loaded"):
       - Call ledger.mark_cold(name).
    Only operates on entries that exist in the ledger (never creates new entries).
    """
    if llm_proxy == "none":
        return

    proxy_status = await query_proxy_models(base_url)
    loaded_names = {name for name, status in proxy_status.items() if status == "loaded"}

    for name, entry in ledger.entries().items():
        if name in loaded_names and entry.state in (State.COLD, State.ABSENT):
            ledger.mark_resident(name)
        elif entry.state == State.RESIDENT and name not in loaded_names:
            ledger.mark_cold(name)


async def unload_for_admission(
    ledger: Ledger,
    base_url: str,
    llm_proxy: str,
    name: str,
    needed_bytes: int,
) -> bool:
    """Unload proxy models to free footprint for a new admission.

    When llm_proxy is "none", returns False.
    When llm_proxy is "llama-swap":
    1. Get eviction candidates from the ledger.
    2. For each candidate, call unload_proxy_model.
    3. On successful unload, call ledger.mark_cold(candidate).
    4. Return True if enough headroom was freed, False otherwise.
    """
    if llm_proxy == "none":
        return False

    candidates = ledger.eviction_candidates(needed_bytes)
    if not candidates:
        return False

    for candidate in candidates:
        ok = await unload_proxy_model(base_url, candidate)
        if ok:
            ledger.mark_cold(candidate)

    return ledger.headroom >= needed_bytes
