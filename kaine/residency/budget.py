# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from kaine import hostmem

_GiB = 1 << 30
_MiB = 1 << 20


@dataclass(frozen=True)
class MemoryDomain:
    """One memory domain with a derived, non-negative residency budget."""

    name: str
    total_bytes: int | None
    available_bytes: int | None
    reserve_bytes: int
    provenance: str
    unknown_reason: str | None = None
    budget_bytes: int | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.available_bytes is None:
            object.__setattr__(self, "budget_bytes", None)
            if self.unknown_reason is None:
                object.__setattr__(self, "unknown_reason", "available bytes unknown")
        else:
            object.__setattr__(
                self,
                "budget_bytes",
                max(0, self.available_bytes - self.reserve_bytes),
            )


@dataclass(frozen=True)
class ResidencyBudget:
    """Host-wide residency budget: one system domain and zero or more devices."""

    topology: str
    system: MemoryDomain
    devices: tuple[MemoryDomain, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        """Return a JSON-round-trippable dict representation."""
        return json.loads(
            json.dumps(
                {
                    "topology": self.topology,
                    "system": asdict(self.system),
                    "devices": [asdict(d) for d in self.devices],
                    "notes": list(self.notes),
                }
            )
        )


def default_reserve_bytes(total_bytes: int | None) -> int:
    """Host RAM reserve: at least 1 GiB and 10% of total when known."""
    reserve = _GiB if total_bytes is None else int(total_bytes * 0.1)
    return max(_GiB, reserve)


def cgroup_available_bytes(
    root: Path = Path("/sys/fs/cgroup"),
    self_cgroup: Path = Path("/proc/self/cgroup"),
) -> tuple[int | None, str]:
    """Return the cgroup's remaining memory and a provenance string.

    Supports cgroup v2 (memory.max - memory.current) and v1
    (memory.limit_in_bytes - memory.usage_in_bytes).  Walks from the process's
    own cgroup up to the root, clamping the remaining memory at each level to
    zero and returning the tightest limit.  Never raises.
    """
    root = Path(root)

    def _rel(path: Path, base: Path) -> str:
        try:
            rel = path.relative_to(base)
        except ValueError:
            rel = Path(".")
        if rel == Path("."):
            return "/"
        return "/" + str(rel).replace("\\", "/")

    def _walk_v2(start: Path, nested: bool) -> tuple[int | None, str]:
        min_remaining: int | None = None
        min_level = ""
        current = start
        while True:
            try:
                max_text = (current / "memory.max").read_text(encoding="utf-8").strip()
                if max_text == "max":
                    pass
                else:
                    limit = int(max_text)
                    current_bytes = int(
                        (current / "memory.current").read_text(encoding="utf-8").strip()
                    )
                    remaining = max(0, limit - current_bytes)
                    level = _rel(current, root)
                    if min_remaining is None or remaining < min_remaining:
                        min_remaining = remaining
                        min_level = level
            except Exception:
                pass
            if current == root:
                break
            current = current.parent
        if min_remaining is not None:
            if nested:
                return (min_remaining, f"cgroup v2 limit at {min_level}")
            return (min_remaining, "cgroup v2")
        return (None, "cgroup v2: no limit")

    def _walk_v1(start: Path, nested: bool) -> tuple[int | None, str]:
        mem_root = root / "memory"
        min_remaining: int | None = None
        min_level = ""
        current = start
        while True:
            try:
                limit = int(
                    (current / "memory.limit_in_bytes").read_text(encoding="utf-8").strip()
                )
                if limit >= 1 << 60:
                    pass
                else:
                    usage = int(
                        (current / "memory.usage_in_bytes").read_text(encoding="utf-8").strip()
                    )
                    remaining = max(0, limit - usage)
                    level = _rel(current, mem_root)
                    if min_remaining is None or remaining < min_remaining:
                        min_remaining = remaining
                        min_level = level
            except Exception:
                pass
            if current == mem_root:
                break
            current = current.parent
        if min_remaining is not None:
            if nested:
                return (min_remaining, f"cgroup v1 limit at {min_level}")
            return (min_remaining, "cgroup v1")
        return (None, "cgroup v1: no limit")

    start_v2: Path | None = None
    start_v1: Path | None = None
    try:
        for line in Path(self_cgroup).read_text(encoding="utf-8").splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            _id, controllers, path_part = parts
            if controllers == "":
                start_v2 = root / path_part.lstrip("/")
                break
            if "memory" in controllers.split(","):
                start_v1 = (root / "memory") / path_part.lstrip("/")
                break
    except Exception:
        pass

    if start_v2 is not None and start_v2.exists():
        return _walk_v2(start_v2, nested=start_v2 != root)
    if start_v1 is not None and start_v1.exists():
        mem_root = root / "memory"
        return _walk_v1(start_v1, nested=start_v1 != mem_root)

    if (root / "memory.max").exists() or (root / "memory.current").exists():
        return _walk_v2(root, nested=False)
    if (root / "memory" / "memory.limit_in_bytes").exists():
        return _walk_v1(root / "memory", nested=False)
    return (None, "cgroup: no readable v2 or v1 controls")


def compute_budget(
    *,
    system_pool: hostmem.Pool,
    accelerators: Sequence[hostmem.MemoryClassification] = (),
    reserve_bytes: int | None = None,
    cgroup_available: int | None = None,
) -> ResidencyBudget:
    """Derive a pure residency budget from injected host memory figures."""
    notes: list[str] = []

    # System domain.
    available = system_pool.available_bytes
    if cgroup_available is not None:
        if available is None:
            available = cgroup_available
        else:
            available = min(available, cgroup_available)
        provenance = f"{system_pool.provenance} + cgroup clamp"
    else:
        provenance = system_pool.provenance

    reserve = (
        reserve_bytes
        if reserve_bytes is not None
        else default_reserve_bytes(system_pool.total_bytes)
    )
    system_domain = MemoryDomain(
        name="system",
        total_bytes=system_pool.total_bytes,
        available_bytes=available,
        reserve_bytes=reserve,
        provenance=provenance,
        unknown_reason=system_pool.unknown_reason,
    )

    # Topology.
    if not accelerators:
        topology = "cpu_only"
    elif any(a.state == "unified" for a in accelerators):
        topology = "unified"
        notes.append(
            "Unified host: device memory figures are ignored because the pool is shared."
        )
    elif all(a.state == "discrete" for a in accelerators):
        topology = "discrete"
    else:
        topology = "unknown"
        notes.append(
            "Unknown accelerator state gives no device-memory guarantees; budgeting conservatively."
        )

    # Device domains: only discrete accelerators, and never on unified hosts.
    devices: list[MemoryDomain] = []
    if topology != "unified":
        for index, accel in enumerate(accelerators):
            if accel.state != "discrete":
                continue
            for pool in accel.pools:
                if pool.kind != "vram":
                    continue
                dev_reserve = (
                    max(_MiB * 256, int(pool.total_bytes * 0.05))
                    if pool.total_bytes is not None
                    else _MiB * 256
                )
                devices.append(
                    MemoryDomain(
                        name=f"device:{index}",
                        total_bytes=pool.total_bytes,
                        available_bytes=pool.available_bytes,
                        reserve_bytes=dev_reserve,
                        provenance=pool.provenance,
                        unknown_reason=pool.unknown_reason,
                    )
                )

    return ResidencyBudget(
        topology=topology,
        system=system_domain,
        devices=tuple(devices),
        notes=tuple(notes),
    )


def probe_budget(*, reserve_bytes: int | None = None) -> ResidencyBudget:
    """Live wrapper: inspect the host and derive a residency budget."""
    system_pool = hostmem.system_memory_pool()
    cgroup_available, _ = cgroup_available_bytes()

    accel = hostmem.classify_accelerator_memory(0)
    extra_notes: list[str] = []
    accelerators: list[hostmem.MemoryClassification] = []

    if accel.state == "unknown" and not accel.pools:
        extra_notes.append(
            "Accelerator probe returned unknown with no pools; treating host as cpu_only."
        )
    else:
        accelerators.append(accel)
        extra_notes.append(
            "Only accelerator 0 is classified; per-device budgets for further "
            "accelerators are not derived yet."
        )

    budget = compute_budget(
        system_pool=system_pool,
        accelerators=accelerators,
        reserve_bytes=reserve_bytes,
        cgroup_available=cgroup_available,
    )

    return ResidencyBudget(
        topology=budget.topology,
        system=budget.system,
        devices=budget.devices,
        notes=budget.notes + tuple(extra_notes),
    )
