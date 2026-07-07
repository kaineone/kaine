# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared LoRA-adapter merge contract + no-op fallback.

Leaf module holding the small surface shared between the merge orchestrator
(`kaine.lifecycle.manager`) and the real PEFT-backed merger
(`kaine.lifecycle.adapter_merge`): the `AdapterMerger` Protocol and the no-op
`FakeAdapterMerger`. Both live here — depending only on the standard library —
so the two collaborators import them from a common leaf instead of from each
other, keeping the dependency direction one-way
(`adapter_merge` -> this; `manager` -> this / `manager` -> `adapter_merge`).

`kaine.lifecycle.manager` re-exports both names, so
`kaine.lifecycle.manager.AdapterMerger` / `.FakeAdapterMerger` (and the
`kaine.lifecycle` package re-exports) remain the public import path.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class AdapterMerger(Protocol):
    """Merges two parents' LoRA adapter paths into a single adapter set.

    `merger_from_name("auto")` — the shipped default — selects the real
    `TiesDareAdapterMerger` (`kaine.lifecycle.adapter_merge`) whenever the
    PEFT extra (`kaine[training]`) is importable, and falls back to this
    module's no-op `FakeAdapterMerger` otherwise. `FakeAdapterMerger` also
    remains available as an explicit dev/no-extra selection.
    """

    def merge(
        self, adapters_a: list[str], adapters_b: list[str]
    ) -> tuple[list[str], dict[str, Any]]:
        ...


class FakeAdapterMerger:
    """No-op merger: unions the two adapter path lists WITHOUT performing
    any real weight merge.

    This is the fallback used when the PEFT extra (`kaine[training]`) is
    absent, or when an operator explicitly selects
    `adapter_merger = "fake"`. When the extra is present,
    `merger_from_name("auto")` (the shipped default) selects the real
    `TiesDareAdapterMerger` instead. When this stub actually runs with
    adapters on both sides (i.e. a genuine fork/merge), it logs so the
    no-op is visible rather than silent; it stays quiet for the
    empty/trivial case that dominates default deployments.
    """

    def merge(
        self, adapters_a: list[str], adapters_b: list[str]
    ) -> tuple[list[str], dict[str, Any]]:
        combined: list[str] = []
        seen: set[str] = set()
        for src in (adapters_a, adapters_b):
            for path in src:
                if path not in seen:
                    combined.append(path)
                    seen.add(path)
        if adapters_a and adapters_b:
            log.info(
                "FakeAdapterMerger: no real merger configured — unioning %d "
                "adapter path(s) without merging weights (enable "
                "[lifecycle.adapter_merge] + the PEFT extra for a real merge)",
                len(combined),
            )
        return combined, {"adapter_merge_skipped": "no merger configured"}
