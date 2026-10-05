# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Memory budget derivation: one source of truth per memory domain."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine.hostmem import (
    MemoryClassification,
    Pool,
    classify_accelerator_memory,
    system_memory_pool,
)

logger = logging.getLogger(__name__)

GIB = 1 << 30


def default_reserve_bytes(physical_total_bytes: int) -> int:
    """Default reserve: at least 1 GiB, or 10 % of physical RAM."""
    return max(GIB, physical_total_bytes // 10)


@dataclass(frozen=True)
class CgroupMemory:
    limit_bytes: int | None
    usage_bytes: int | None
    provenance: str


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def cgroup_memory(
    *,
    proc_cgroup_path: str = "/proc/self/cgroup",
    cgroup_root: str = "/sys/fs/cgroup",
) -> CgroupMemory:
    """Read cgroup memory limit and usage; never raises.

    Handles cgroup v2 (single hierarchy) and v1 (memory controller). Any
    missing file or parse error gives ``None`` for that figure and records why.
    """
    root = Path(cgroup_root)
    proc_path = Path(proc_cgroup_path)

    v2_path: str | None = None
    v1_path: str | None = None

    try:
        lines = proc_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        return CgroupMemory(
            limit_bytes=None,
            usage_bytes=None,
            provenance=f"could not read {proc_cgroup_path}: {exc}",
        )

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _, controllers, path = parts
        if controllers == "":
            # cgroup v2
            v2_path = path if path != "/" else ""
        else:
            for controller in controllers.split(","):
                if controller == "memory":
                    v1_path = path if path != "/" else ""
                    break

    # A hybrid host lists both hierarchies; the memory controller is bound to
    # v1 there, so a v1 memory line wins over the v2 unified line.
    if v2_path is not None and v1_path is None:
        target = root / v2_path.lstrip("/") if v2_path else root
        provenance = f"v2 {target / 'memory.max'}, {target / 'memory.current'}"
        try:
            raw_max = (target / "memory.max").read_text(encoding="utf-8").strip()
        except Exception:
            raw_max = None
        if raw_max == "max":
            limit = None
            provenance += "; limit=max (no limit)"
        else:
            limit = _read_int(target / "memory.max")
            if limit is None:
                provenance += "; limit unreadable"
        usage = _read_int(target / "memory.current")
        if usage is None:
            provenance += "; usage unreadable"
        return CgroupMemory(limit_bytes=limit, usage_bytes=usage, provenance=provenance)

    if v1_path is not None:
        target = root / "memory" / v1_path.lstrip("/")
        limit = _read_int(target / "memory.limit_in_bytes")
        usage = _read_int(target / "memory.usage_in_bytes")
        provenance = (
            f"v1 {target / 'memory.limit_in_bytes'}, {target / 'memory.usage_in_bytes'}"
        )
        if limit is None:
            provenance += "; limit unreadable"
        if usage is None:
            provenance += "; usage unreadable"
        if limit is not None and limit >= 2**60:
            limit = None
            provenance += "; limit=huge treated as unlimited"
        return CgroupMemory(limit_bytes=limit, usage_bytes=usage, provenance=provenance)

    return CgroupMemory(
        limit_bytes=None,
        usage_bytes=None,
        provenance="no memory cgroup line found",
    )


def _fmt_gib(n: int | None) -> str:
    if n is None:
        return "unknown"
    return f"{n / GIB:.2f}"


@dataclass(frozen=True)
class Domain:
    name: str
    kind: str
    total_bytes: int | None
    available_bytes: int | None
    reserve_bytes: int
    budget_bytes: int | None
    derivation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "total_bytes": self.total_bytes,
            "available_bytes": self.available_bytes,
            "reserve_bytes": self.reserve_bytes,
            "budget_bytes": self.budget_bytes,
            "derivation": self.derivation,
        }


def _device_pool(classification: MemoryClassification) -> Pool | None:
    for pool in classification.pools:
        if pool.kind == "vram":
            return pool
    return None


def _device_reserve(device_total_bytes: int | None, reserve_bytes: int | None) -> int:
    if reserve_bytes is not None:
        return reserve_bytes
    if device_total_bytes is None:
        return GIB
    return default_reserve_bytes(device_total_bytes)


def derive_budgets(
    *,
    system_pool: Pool,
    cgroup: CgroupMemory,
    accelerators: tuple[tuple[str, MemoryClassification], ...] = (),
    reserve_bytes: int | None = None,
) -> tuple[Domain, ...]:
    """Derive one budget per memory domain.

    On unified-memory hosts the accelerator contributes no device domain; the
    system domain's derivation records that the device shares system memory. On
    discrete hosts each accelerator gets its own device domain. CPU-only hosts
    get only a system domain.
    """
    # System domain
    physical_total = system_pool.total_bytes
    physical_available = system_pool.available_bytes

    if reserve_bytes is not None:
        system_reserve = reserve_bytes
    elif physical_total is not None:
        system_reserve = default_reserve_bytes(physical_total)
    else:
        system_reserve = GIB

    # Total: clamp by cgroup limit when both known
    total: int | None
    if physical_total is not None and cgroup.limit_bytes is not None:
        total = min(physical_total, cgroup.limit_bytes)
    elif physical_total is not None:
        total = physical_total
    elif cgroup.limit_bytes is not None:
        total = cgroup.limit_bytes
    else:
        total = None

    # Available: pool.available, clamped by cgroup headroom
    available = physical_available
    if available is not None and cgroup.limit_bytes is not None and cgroup.usage_bytes is not None:
        available = min(available, cgroup.limit_bytes - cgroup.usage_bytes)
    elif available is None and cgroup.limit_bytes is not None and cgroup.usage_bytes is not None:
        available = cgroup.limit_bytes - cgroup.usage_bytes

    budget = None if available is None else max(0, available - system_reserve)

    derivation_parts: list[str] = [
        f"system memory total {_fmt_gib(total)} GiB, "
        f"available {_fmt_gib(available)} GiB, "
        f"reserve {_fmt_gib(system_reserve)} GiB; "
        f"budget = {_fmt_gib(budget)} GiB"
    ]

    device_domains: list[Domain] = []
    for device_name, classification in accelerators:
        state = classification.state
        if state == "unified":
            derivation_parts.append(
                f"{device_name} shares system memory; its device figures are ignored for admission"
            )
            continue
        if state == "unknown":
            derivation_parts.append(
                f"{device_name} memory state unknown; budgeting on system memory only"
            )
            continue

        # discrete
        vram_pool = _device_pool(classification)
        if vram_pool is None:
            derivation_parts.append(
                f"{device_name} discrete but no vram pool reported; budgeting on system memory only"
            )
            continue

        dev_total = vram_pool.total_bytes
        dev_available = vram_pool.available_bytes
        dev_reserve = _device_reserve(dev_total, reserve_bytes)
        dev_budget = (
            None
            if dev_available is None
            else max(0, dev_available - dev_reserve)
        )

        dev_derivation = (
            f"{device_name} vram total {_fmt_gib(dev_total)} GiB, "
            f"available {_fmt_gib(dev_available)} GiB, "
            f"reserve {_fmt_gib(dev_reserve)} GiB; "
            f"budget = {_fmt_gib(dev_budget)} GiB"
        )

        device_domains.append(
            Domain(
                name=device_name,
                kind="device",
                total_bytes=dev_total,
                available_bytes=dev_available,
                reserve_bytes=dev_reserve,
                budget_bytes=dev_budget,
                derivation=dev_derivation,
            )
        )

    system_domain = Domain(
        name="system",
        kind="system",
        total_bytes=total,
        available_bytes=available,
        reserve_bytes=system_reserve,
        budget_bytes=budget,
        derivation="; ".join(derivation_parts),
    )

    return (system_domain, *device_domains)


def current_budgets(*, reserve_bytes: int | None = None) -> tuple[Domain, ...]:
    """Derive budgets from the live host state."""
    system_pool = system_memory_pool()
    cgroup = cgroup_memory()

    accelerators: list[tuple[str, MemoryClassification]] = []
    try:
        import torch  # type: ignore[import]
    except Exception:
        torch = None  # type: ignore[misc]

    if torch is not None and torch.cuda.is_available():
        n = torch.cuda.device_count()
        for i in range(n):
            classification = classify_accelerator_memory(i, torch=torch)
            accelerators.append((f"cuda:{i}", classification))

    return derive_budgets(
        system_pool=system_pool,
        cgroup=cgroup,
        accelerators=tuple(accelerators),
        reserve_bytes=reserve_bytes,
    )
