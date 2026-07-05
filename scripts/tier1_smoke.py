# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tier-1 infra smoke: initialize ALL modules against the live services,
let background loops run briefly, then shut down — WITHOUT running the
cognitive cycle. Verifies plumbing (service connections, model loads, loop
health), not cognition. Not the entity boot.

Run: .venv/bin/python scripts/tier1_smoke.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback

import httpx

from kaine.bus.config import load_bus_config
from kaine.bus.client import AsyncBus
from kaine.cycle.__main__ import _load_kaine_config
from kaine.boot import build_registry


def _service_checks() -> list[str]:
    out: list[str] = []
    checks = [
        ("model server /v1/models", "http://127.0.0.1:11434/v1/models"),
        ("speaches /v1/models", "http://127.0.0.1:8000/v1/models"),
        ("chatterbox /", "http://127.0.0.1:8883/"),
        ("qdrant /readyz", "http://127.0.0.1:6533/readyz"),
    ]
    for name, url in checks:
        try:
            r = httpx.get(url, timeout=8.0)
            out.append(f"  [{r.status_code}] {name}")
        except Exception as exc:
            out.append(f"  [ERR] {name}: {type(exc).__name__}: {exc}")
    return out


async def main() -> int:
    print("=== Tier-1 infra smoke (no cognitive cycle) ===\n")
    print("Service reachability:")
    for line in _service_checks():
        print(line)
    print()

    cfg = _load_kaine_config()
    for k in list(cfg.setdefault("modules", {})):
        cfg["modules"][k] = True
    cfg.setdefault("oscillator", {})["enabled"] = True

    # Collect background-loop exceptions that would otherwise be swallowed.
    loop = asyncio.get_running_loop()
    bg_errors: list[str] = []

    def _handler(loop, context):
        msg = context.get("exception") or context.get("message")
        bg_errors.append(f"{type(context.get('exception')).__name__ if context.get('exception') else 'msg'}: {msg}")

    loop.set_exception_handler(_handler)

    bus = AsyncBus(load_bus_config())
    await bus.audit()
    registry = build_registry(bus, cfg)
    modules = list(registry.all_modules())
    print(f"build_registry: {len(modules)} modules constructed\n")

    init_ok, init_err = [], []
    for m in modules:
        try:
            await asyncio.wait_for(m.initialize(), timeout=60.0)
            init_ok.append(m.name)
        except Exception as exc:
            init_err.append((m.name, f"{type(exc).__name__}: {exc}"))
            traceback.print_exc()

    print(f"initialized OK ({len(init_ok)}): {sorted(init_ok)}")
    if init_err:
        print(f"initialize FAILED ({len(init_err)}):")
        for n, e in init_err:
            print(f"  - {n}: {e}")
    print()

    print("running loops for 5s...")
    await asyncio.sleep(5.0)

    shut_ok, shut_err = [], []
    for m in reversed(modules):
        try:
            await asyncio.wait_for(m.shutdown(), timeout=30.0)
            shut_ok.append(m.name)
        except Exception as exc:
            shut_err.append((m.name, f"{type(exc).__name__}: {exc}"))

    print(f"\nshutdown OK ({len(shut_ok)})")
    if shut_err:
        print(f"shutdown FAILED ({len(shut_err)}):")
        for n, e in shut_err:
            print(f"  - {n}: {e}")

    if bg_errors:
        print(f"\nbackground-loop errors ({len(bg_errors)}):")
        for e in bg_errors[:20]:
            print(f"  - {e}")

    try:
        await bus.close()
    except Exception:
        pass

    ok = not init_err and not shut_err and not bg_errors
    print("\n=== RESULT:", "GREEN" if ok else "ISSUES FOUND", "===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
