# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hardware timing benchmark for biological multi-rate timing (Phase 3).

Measures, on the ACTUAL accelerator, the two costs that bound the entity's
subjective rates — WITHOUT booting an entity:

  1. Sustained per-tick cost of the cognitive cycle's plumbing
     (``CognitiveCycle.tick()``), to bound the workspace ``processing_rate_hz``.
  2. Per-vision-encode cost (the GPU-expensive DINOv2 forward on one seeded
     frame), to bound the perception ``vision_sample_hz``.

It then prints a recommendation block: a safe workspace-tick value in the
**3-10 Hz** band and a safe vision-sample rate toward **~10 Hz**, each with the
measured headroom/margin, so the operator can decide whether to raise the
shipped defaults (this script NEVER changes them — it only recommends).

THIS IS NOT AN ENTITY BOOT. It is a dry performance probe. Explicitly:

  * The cognitive cycle is driven in DETERMINISTIC mode for N ticks.
  * NO language organ / NO real LLM: lingua + vox are force-disabled in the
    config copy this script builds, so no organ module is constructed and no
    chat client is created. (The organ never participates in tick() anyway —
    it reacts to bus events in its own loop — but disabling it removes any
    chance of an outward utterance.)
  * NO Volition side-effects: the cycle is built with ``volition=None``, so the
    tick can never select or publish an effector intent. Nothing is spoken,
    nothing acts outward. We measure cognitive PLUMBING cost only.
  * The vision encode is timed directly on a seeded synthetic frame — never a
    real camera, never persisted.

Real measurement or an honest "couldn't measure X because Y" — no fabricated
numbers. If a required service/model is unavailable the affected section is
skipped with a clear reason and the other section still runs.

Run: .venv/bin/python scripts/timing_benchmark.py
     .venv/bin/python scripts/timing_benchmark.py --ticks 300 --encodes 50
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time
import traceback
from typing import Any, Optional

from kaine.boot import build_registry, make_coherence_scorer
from kaine.bus.client import AsyncBus
from kaine.bus.config import load_bus_config
from kaine.cycle.__main__ import _load_kaine_config
from kaine.cycle.engine import CognitiveCycle
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)

# Workspace-tick band the conscious-access literature makes defensible
# (design.md §4 / §8). The recommendation stays inside this band.
TICK_BAND_LOW_HZ = 3.0
TICK_BAND_HIGH_HZ = 10.0
# Vision biological target band (design.md §8: raise toward ~10 Hz).
VISION_TARGET_HZ = 10.0
# Safety margin: only recommend a rate the host can sustain with this much
# headroom over the measured p95 cost (so transient spikes don't overrun).
SAFETY_HEADROOM = 1.3


def _pct(values: list[float], q: float) -> float:
    """Percentile (linear interpolation) of a list of floats."""
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _stats_ms(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "mean": statistics.fmean(samples) if samples else float("nan"),
        "p50": _pct(samples, 0.50),
        "p95": _pct(samples, 0.95),
        "max": max(samples) if samples else float("nan"),
    }


# --------------------------------------------------------------------------
# 1. Sustained per-tick cost
# --------------------------------------------------------------------------


async def _benchmark_tick(cfg: dict[str, Any], ticks: int) -> dict[str, Any]:
    """Drive CognitiveCycle.tick() for `ticks` ticks; return per-tick stats.

    Wires the real modules (as tier1_smoke does) but with the language organ
    disabled and Volition removed, so this is cognitive plumbing only — no LLM,
    no effector activation, no outward action.
    """
    out: dict[str, Any] = {"ran": False, "reason": "", "samples_ms": []}

    bus_cfg = load_bus_config()
    try:
        bus = AsyncBus(bus_cfg)
        await bus.audit()
    except Exception as exc:
        out["reason"] = f"bus unavailable ({type(exc).__name__}: {exc})"
        return out

    # Force-disable the organ + voice output so no LLM/effector path exists.
    bench_cfg = {**cfg, "modules": dict(cfg.get("modules") or {})}
    for k in list(bench_cfg["modules"]):
        bench_cfg["modules"][k] = True
    bench_cfg["modules"]["lingua"] = False
    bench_cfg["modules"]["vox"] = False
    # Deterministic mode: logical clock, canonical ordering — the plumbing path
    # the research runs use, and reproducible.
    bench_cfg["experiment"] = {**(cfg.get("experiment") or {}), "deterministic": True}
    bench_cfg.setdefault("oscillator", {})
    bench_cfg["oscillator"] = {**bench_cfg["oscillator"], "enabled": True}

    registry = None
    cycle = None
    init_modules: list[Any] = []
    try:
        registry = build_registry(bus, bench_cfg)
        init_modules = list(registry.all_modules())
        init_ok, init_err = [], []
        for m in init_modules:
            try:
                await asyncio.wait_for(m.initialize(), timeout=120.0)
                init_ok.append(m.name)
            except Exception as exc:
                init_err.append((m.name, f"{type(exc).__name__}: {exc}"))
                traceback.print_exc()
        out["modules_initialized"] = sorted(init_ok)
        out["modules_failed"] = [n for n, _ in init_err]
        if init_err:
            print(f"  WARN: {len(init_err)} module(s) failed to initialize:")
            for n, e in init_err:
                print(f"    - {n}: {e}")

        syn_cfg = bench_cfg.get("syneidesis") or {}
        coherence = make_coherence_scorer(bench_cfg)
        syneidesis = Syneidesis(
            strategy=RuleBasedSalience(
                novelty=NoveltyTracker(window=int(syn_cfg.get("novelty_window", 32))),
                goal_scorer=StaticGoalScorer(),
                thymos_modulator=StaticThymosModulator(),
            ),
            top_k=int(syn_cfg.get("top_k", 5)),
            publication_threshold=float(syn_cfg.get("publication_threshold", 0.35)),
            coherence=coherence,
        )
        cycle_cfg = bench_cfg.get("cycle") or {}
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syneidesis,
            registry=registry,
            processing_rate_hz=float(cycle_cfg.get("processing_rate_hz", 3.333)),
            experiential_rate_hz=float(cycle_cfg.get("experiential_rate_hz", 3.333)),
            # NO Volition: the tick can never select/publish an effector intent.
            volition=None,
            collect_phases=coherence is not None,
            entity_clock=registry.entity_clock,
            deterministic=True,
        )

        # Let the background loops settle so streams have realistic content.
        await asyncio.sleep(2.0)

        # Warm-up ticks (JIT, GPU kernels, caches) excluded from the stats.
        warmup = min(10, max(1, ticks // 20))
        for _ in range(warmup):
            await cycle.tick()

        samples: list[float] = []
        for _ in range(ticks):
            t0 = time.perf_counter()
            await cycle.tick()
            samples.append((time.perf_counter() - t0) * 1000.0)

        out["ran"] = True
        out["samples_ms"] = samples
        out["warmup_ticks"] = warmup
    except Exception as exc:
        out["reason"] = f"tick benchmark error ({type(exc).__name__}: {exc})"
        traceback.print_exc()
    finally:
        for m in reversed(init_modules):
            try:
                await asyncio.wait_for(m.shutdown(), timeout=30.0)
            except Exception:
                # Best-effort teardown after the benchmark result is already
                # recorded in `out`; a module failing to shut down cleanly
                # shouldn't invalidate the timing measurement.
                pass
        try:
            await bus.close()
        except Exception:
            # Best-effort teardown; same rationale as above.
            pass
    return out


# --------------------------------------------------------------------------
# 2. Per-vision-encode cost
# --------------------------------------------------------------------------


async def _benchmark_vision(cfg: dict[str, Any], encodes: int) -> dict[str, Any]:
    """Time the Topos DINOv2 encode of one seeded frame over `encodes` iters."""
    out: dict[str, Any] = {"ran": False, "reason": "", "samples_ms": []}

    topos_cfg = cfg.get("topos") or {}
    width = int(topos_cfg.get("capture_width", 640))
    height = int(topos_cfg.get("capture_height", 480))
    model_id = topos_cfg.get("encoder_model_id")
    device_pref = topos_cfg.get("device", "auto")

    # Build one seeded frame (never a camera; never persisted).
    try:
        from kaine.modules.topos.feed import SeededProceduralSource, SeededSchedule

        source = SeededProceduralSource(
            SeededSchedule(seed=0, width=width, height=height)
        )
        source.open()
        ok, frame = source.read()
        if not ok or frame is None:
            out["reason"] = "seeded frame source produced no frame"
            return out
    except Exception as exc:
        out["reason"] = f"could not build seeded frame ({type(exc).__name__}: {exc})"
        return out

    try:
        from kaine.modules.topos.encoder import DINOv2Encoder

        kw: dict[str, Any] = {"device_preference": device_pref}
        if model_id:
            kw["model_id"] = str(model_id)
        encoder = DINOv2Encoder(**kw)
        await encoder.load()
        out["device"] = getattr(encoder, "device", "unknown")
        out["model_id"] = encoder.model_id
    except Exception as exc:
        out["reason"] = (
            f"vision encoder unavailable ({type(exc).__name__}: {exc}); "
            "install the .[vision] extra + the encoder model to measure this"
        )
        return out

    try:
        # Warm-up encodes (model load, GPU kernels) excluded from the stats.
        warmup = min(5, max(1, encodes // 10))
        for _ in range(warmup):
            await encoder.encode(frame)

        samples: list[float] = []
        for _ in range(encodes):
            t0 = time.perf_counter()
            await encoder.encode(frame)
            samples.append((time.perf_counter() - t0) * 1000.0)
        out["ran"] = True
        out["samples_ms"] = samples
        out["warmup_encodes"] = warmup
    except Exception as exc:
        out["reason"] = f"encode error ({type(exc).__name__}: {exc})"
    finally:
        try:
            await encoder.shutdown()
        except Exception:
            # Best-effort teardown after samples are already recorded in
            # `out`; an encoder shutdown failure shouldn't invalidate the
            # timing measurement.
            pass
    return out


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _recommend_tick(p95_ms: float) -> dict[str, Any]:
    """Recommend a workspace-tick rate in the 3-10 Hz band from p95 cost."""
    if math.isnan(p95_ms) or p95_ms <= 0:  # NaN / no-measurement guard
        return {"recommended_hz": None, "reason": "no measurement"}
    # Max sustainable rate with the safety headroom over p95 cost.
    sustainable = 1000.0 / (p95_ms * SAFETY_HEADROOM)
    # Clamp into the defensible band.
    rec = max(TICK_BAND_LOW_HZ, min(TICK_BAND_HIGH_HZ, sustainable))
    return {
        "max_sustainable_hz": sustainable,
        "recommended_hz": rec,
        "band": (TICK_BAND_LOW_HZ, TICK_BAND_HIGH_HZ),
        "headroom_factor": SAFETY_HEADROOM,
    }


def _recommend_vision(p95_ms: float) -> dict[str, Any]:
    """Recommend a vision-sample rate toward ~10 Hz from per-encode p95 cost."""
    if math.isnan(p95_ms) or p95_ms <= 0:
        return {"recommended_hz": None, "reason": "no measurement"}
    sustainable = 1000.0 / (p95_ms * SAFETY_HEADROOM)
    # Recommend toward the ~10 Hz biological target, never above what's safe.
    rec = min(VISION_TARGET_HZ, sustainable)
    return {
        "max_sustainable_hz": sustainable,
        "recommended_hz": rec,
        "target_hz": VISION_TARGET_HZ,
        "headroom_factor": SAFETY_HEADROOM,
    }


def _print_section(title: str, stats: dict[str, float]) -> None:
    print(f"  {title}:")
    print(f"    samples : {stats['n']}")
    print(f"    mean    : {stats['mean']:.2f} ms")
    print(f"    p50     : {stats['p50']:.2f} ms")
    print(f"    p95     : {stats['p95']:.2f} ms")
    print(f"    max     : {stats['max']:.2f} ms")


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=200, help="ticks to time")
    parser.add_argument("--encodes", type=int, default=40, help="encodes to time")
    parser.add_argument(
        "--skip-tick", action="store_true", help="skip the per-tick benchmark"
    )
    parser.add_argument(
        "--skip-vision", action="store_true", help="skip the vision-encode benchmark"
    )
    args = parser.parse_args(argv)

    print("=== KAINE timing benchmark (biological-timing-and-dilation Phase 3) ===")
    print("Dry performance probe — NOT an entity boot. Organ/LLM disabled,")
    print("Volition removed (no outward action). Measures plumbing + encode cost.\n")

    cfg = _load_kaine_config()

    tick_res: dict[str, Any] = {"ran": False, "reason": "skipped"}
    vision_res: dict[str, Any] = {"ran": False, "reason": "skipped"}

    if not args.skip_tick:
        print(f"[1/2] Sustained per-tick cost ({args.ticks} ticks, deterministic)...")
        tick_res = await _benchmark_tick(cfg, args.ticks)
        if tick_res["ran"]:
            tstats = _stats_ms(tick_res["samples_ms"])
            _print_section("per-tick wall time", tstats)
        else:
            print(f"  SKIPPED: {tick_res['reason']}")
        print()

    if not args.skip_vision:
        print(f"[2/2] Per-vision-encode cost ({args.encodes} encodes)...")
        vision_res = await _benchmark_vision(cfg, args.encodes)
        if vision_res["ran"]:
            vstats = _stats_ms(vision_res["samples_ms"])
            print(
                f"  encoder: {vision_res.get('model_id')} on "
                f"{vision_res.get('device')}"
            )
            _print_section("per-encode wall time", vstats)
        else:
            print(f"  SKIPPED: {vision_res['reason']}")
        print()

    # ---- recommendation block ----
    print("=" * 70)
    print("RECOMMENDATION (advisory only — shipped defaults are NOT changed)")
    print("=" * 70)

    if tick_res["ran"]:
        tstats = _stats_ms(tick_res["samples_ms"])
        rec = _recommend_tick(tstats["p95"])
        print("Workspace tick (processing_rate_hz), 3-10 Hz band:")
        print(f"  measured p95 per-tick cost : {tstats['p95']:.2f} ms")
        print(
            f"  max sustainable rate       : {rec['max_sustainable_hz']:.2f} Hz "
            f"(p95 x {SAFETY_HEADROOM} headroom)"
        )
        print(f"  RECOMMENDED                : {rec['recommended_hz']:.3f} Hz")
        cur = float((cfg.get("cycle") or {}).get("processing_rate_hz", 3.333))
        print(f"  shipped default (unchanged): {cur:.3f} Hz")
    else:
        print("Workspace tick: NOT MEASURED — " + tick_res["reason"])
    print()

    if vision_res["ran"]:
        vstats = _stats_ms(vision_res["samples_ms"])
        rec = _recommend_vision(vstats["p95"])
        print("Vision sampling (vision_sample_hz / capture_interval_s), toward ~10 Hz:")
        print(f"  measured p95 per-encode cost: {vstats['p95']:.2f} ms")
        print(
            f"  max sustainable rate        : {rec['max_sustainable_hz']:.2f} Hz "
            f"(p95 x {SAFETY_HEADROOM} headroom)"
        )
        print(f"  RECOMMENDED                 : {rec['recommended_hz']:.3f} Hz")
        cur_int = float((cfg.get("topos") or {}).get("capture_interval_s", 1.0))
        print(
            f"  shipped default (unchanged) : {1.0 / cur_int:.3f} Hz "
            f"(capture_interval_s = {cur_int:.3f})"
        )
    else:
        print("Vision sampling: NOT MEASURED — " + vision_res["reason"])
    print()
    print("Bring these numbers to the operator before raising any shipped default.")

    # Honest exit: non-zero only when EVERYTHING was skipped (nothing measured).
    measured = tick_res["ran"] or vision_res["ran"]
    return 0 if measured else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
