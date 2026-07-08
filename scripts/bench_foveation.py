# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host benchmark for attention-driven foveation (topos-foveation, task 1.7).

Foveation replaces one uniform whole-frame encode with a small amount of spatial
bookkeeping plus TWO encodes (a downsampled peripheral gist + a native foveal
crop). Before it may ship enabled, that cost MUST be shown to fit the vision tick
on the actual host — this script measures it. It is a dry performance probe, NOT
an entity boot: no cognitive cycle, no Volition, no outward action, nothing
persisted. Frames live in memory and are released, exactly as in perception.

What it measures, per stage, on the real DINOv2 encoder and (optionally) a real
native screen grab:

  1. baseline    — one whole-frame encode (today's shipped path).
  2. saliency    — spatial saliency + fovea select + foveate (peripheral+foveal
                   view derivation). Pure numpy/cv2, no encoder.
  3. foveated    — the two encodes (peripheral + foveal) + the saliency work: the
                   full per-tick foveation cost.
  4. grab        — one native screen grab via ffmpeg (only with --screen), so the
                   native-resolution capture cost is included honestly.

It then compares the foveated per-tick cost against the vision-tick budget
(1 / vision_sample_hz) and prints whether foveation fits, with the margin. Real
measurement or an explicit "couldn't measure X because Y" — no fabricated numbers.

Run: .venv/bin/python scripts/bench_foveation.py
     .venv/bin/python scripts/bench_foveation.py --iters 60 --screen
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import tomllib
from pathlib import Path
from typing import Any, Optional

import numpy as np

CONFIG_PATH = Path("config/kaine.toml")


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _pct(samples: list[float], q: float) -> float:
    if not samples:
        return float("nan")
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


def _fovea_knobs(topos_cfg: dict[str, Any]) -> dict[str, Any]:
    grid = topos_cfg.get("foveation_grid") or [12, 12]
    pw = int(topos_cfg.get("peripheral_width", 320))
    ph = int(topos_cfg.get("peripheral_height", 180))
    fs = int(topos_cfg.get("foveal_size", 224))
    lo = float(topos_cfg.get("foveation_arousal_size_min", 0.12))
    hi = float(topos_cfg.get("foveation_arousal_size_max", 0.5))
    return {
        "grid": (int(grid[0]), int(grid[1])),
        "peripheral_size": (pw, ph),
        "foveal_size": (fs, fs),
        "size_range": (lo, hi),
    }


def _open_native_source(cfg: dict[str, Any]) -> tuple[Optional[Any], str]:
    """Open ONE persistent native screen-capture source (ffmpeg stays running, as
    in production), or explain why not. The caller times steady-state read()s and
    releases it — spawning ffmpeg per frame would measure process startup, not the
    per-tick read the running system actually pays."""
    try:
        from kaine.modules.topos.screen import (
            ScreenCaptureSource,
            ScreenTarget,
            detect_screen_size,
            screen_capture_spec,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return None, f"screen module unavailable ({type(exc).__name__}: {exc})"

    scr = ((cfg.get("perception_feed") or {}).get("screen")) or {}
    target = ScreenTarget(
        kind=str(scr.get("target", "fullscreen")).lower(),
        display=str(scr.get("display", ":0.0")),
        framerate=int(scr.get("framerate", 10)),
        cursor=bool(scr.get("cursor", True)),
    )
    size = detect_screen_size(target)
    if size is None:
        return None, "could not detect native screen size (no xrandr / not X11?)"
    try:
        spec = screen_capture_spec(target)
        src = ScreenCaptureSource(spec, width=size[0], height=size[1], native=True)
        if not src.open():
            return None, "ffmpeg screen capture failed to start"
        return src, f"native {size[0]}x{size[1]}"
    except Exception as exc:
        return None, f"screen open error ({type(exc).__name__}: {exc})"


async def _run(cfg: dict[str, Any], iters: int, use_screen: bool) -> dict[str, Any]:
    from kaine.modules.topos.foveation import (
        SpatialSaliency,
        combine_saliency,
        foveate,
        select_fovea,
    )

    topos_cfg = cfg.get("topos") or {}
    knobs = _fovea_knobs(topos_cfg)
    out: dict[str, Any] = {"knobs": knobs, "grab": {}, "iters": iters}

    # --- source frame: a real native grab if asked, else a seeded synthetic ---
    frame: Optional[np.ndarray] = None
    screen_src: Optional[Any] = None
    if use_screen:
        screen_src, reason = _open_native_source(cfg)
        out["grab"]["reason"] = reason
        if screen_src is not None:
            # Time steady-state per-frame read()s off the running ffmpeg (the real
            # per-tick native-grab cost), then keep the freshest frame to encode.
            grab_samples: list[float] = []
            for _ in range(2):  # warm up: discard the first buffered frames
                screen_src.read()
            for _ in range(min(iters, 30)):
                t0 = time.perf_counter()
                ok, f2 = screen_src.read()
                dt = (time.perf_counter() - t0) * 1000.0
                if not ok or f2 is None:
                    break
                grab_samples.append(dt)
                frame = f2
            out["grab"]["samples_ms"] = grab_samples
    if frame is None:
        if screen_src is not None:
            screen_src.release()
            screen_src = None
        w = int(topos_cfg.get("capture_width", 640))
        h = int(topos_cfg.get("capture_height", 480))
        from kaine.modules.topos.feed import SeededProceduralSource, SeededSchedule

        src = SeededProceduralSource(SeededSchedule(seed=0, width=w, height=h))
        src.open()
        ok, frame = src.read()
        if not ok or frame is None:
            out["error"] = "no frame source produced a frame"
            return out
        out["source"] = f"seeded synthetic {w}x{h}"
    else:
        out["source"] = out["grab"].get("reason", "native")
    out["frame_shape"] = tuple(int(x) for x in frame.shape)
    if screen_src is not None:
        screen_src.release()  # done sampling; the encode benchmark reuses `frame`

    # --- encoder ---
    model_id = topos_cfg.get("encoder_model_id")
    device_pref = topos_cfg.get("device", "auto")
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
        out["error"] = (
            f"vision encoder unavailable ({type(exc).__name__}: {exc}); "
            "install the .[vision] extra + the encoder model to measure this"
        )
        return out

    try:
        saliency = SpatialSaliency(grid=knobs["grid"])
        saliency.observe(frame)  # prime prev-tiles

        def _saliency_and_views() -> tuple[np.ndarray, np.ndarray]:
            bottom_up = saliency.observe(frame)
            combined = combine_saliency(bottom_up, None)
            target = select_fovea(combined, arousal=0.4, size_range=knobs["size_range"])
            return foveate(
                frame,
                target,
                peripheral_size=knobs["peripheral_size"],
                foveal_size=knobs["foveal_size"],
            )

        warmup = min(5, max(1, iters // 10))
        for _ in range(warmup):
            await encoder.encode(frame)
            p, fo = _saliency_and_views()
            await encoder.encode(p)
            await encoder.encode(fo)

        baseline, sal, foveated = [], [], []
        for _ in range(iters):
            t0 = time.perf_counter()
            await encoder.encode(frame)
            baseline.append((time.perf_counter() - t0) * 1000.0)

            t0 = time.perf_counter()
            p, fo = _saliency_and_views()
            sal.append((time.perf_counter() - t0) * 1000.0)

            t0 = time.perf_counter()
            p, fo = _saliency_and_views()
            await encoder.encode(p)
            await encoder.encode(fo)
            foveated.append((time.perf_counter() - t0) * 1000.0)

        out["baseline_ms"] = baseline
        out["saliency_ms"] = sal
        out["foveated_ms"] = foveated
        out["ran"] = True
    except Exception as exc:
        out["error"] = f"encode error ({type(exc).__name__}: {exc})"
    finally:
        try:
            await encoder.shutdown()
        except Exception:
            pass
    return out


def _summary(name: str, samples: list[float]) -> str:
    if not samples:
        return f"  {name:<12} —  (no samples)"
    return (
        f"  {name:<12} mean {statistics.mean(samples):7.2f} ms   "
        f"p50 {_pct(samples, 0.50):7.2f}   p95 {_pct(samples, 0.95):7.2f}   "
        f"n={len(samples)}"
    )


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=40, help="timed iterations")
    parser.add_argument(
        "--screen",
        action="store_true",
        help="grab a real native screen frame (X11 ffmpeg) instead of a seeded one",
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    topos_cfg = cfg.get("topos") or {}
    vision_hz = float(topos_cfg.get("vision_sample_hz", 10.0))
    budget_ms = 1000.0 / vision_hz if vision_hz > 0 else float("inf")

    print("KAINE foveation benchmark (topos-foveation task 1.7)")
    print("Dry probe — no entity boot, no Volition, nothing persisted.\n")

    res = await _run(cfg, args.iters, args.screen)
    print(f"source:      {res.get('source', '?')}")
    print(f"frame shape: {res.get('frame_shape', '?')}")
    print(f"knobs:       {res['knobs']}")
    if "device" in res:
        print(f"encoder:     {res.get('model_id')} on {res.get('device')}")
    print()

    if not res.get("ran"):
        print(f"NOT MEASURED: {res.get('error') or res.get('grab', {}).get('reason')}")
        return 1

    print(_summary("baseline", res["baseline_ms"]))
    print(_summary("saliency", res["saliency_ms"]))
    print(_summary("foveated", res["foveated_ms"]))
    grab_samples = res.get("grab", {}).get("samples_ms", [])
    if grab_samples:
        print(_summary("native grab", grab_samples))
        print(
            "    (grab p95 tracks the capture framerate — time spent WAITING for "
            "ffmpeg's next\n     frame, not CPU work; grab p50 is the actual "
            "per-tick read/copy cost.)"
        )
    print()

    base_p95 = _pct(res["baseline_ms"], 0.95)
    fov_p95 = _pct(res["foveated_ms"], 0.95)
    # The CPU the tick actually pays for the grab is the read/copy (p50), NOT the
    # blocking wait for the next frame (p95 ≈ frame period), which overlaps the
    # sampling cadence rather than stealing compute from the tick.
    grab_p50 = _pct(grab_samples, 0.50) if grab_samples else 0.0
    grab_p50 = grab_p50 if grab_p50 == grab_p50 else 0.0  # nan-safe
    compute_p95 = fov_p95 + grab_p50

    print(f"vision tick budget (1/{vision_hz:g} Hz): {budget_ms:.2f} ms")
    print(
        f"per-tick foveation compute p95 = {compute_p95:.2f} ms "
        f"(foveated {fov_p95:.2f}"
        + (f" + grab-read {grab_p50:.2f}" if grab_samples else "")
        + f")  vs baseline encode p95 {base_p95:.2f} ms"
    )
    if compute_p95 <= budget_ms:
        print(
            f"VERDICT: FITS — foveation compute uses "
            f"{100 * compute_p95 / budget_ms:.0f}% of the tick "
            f"({budget_ms - compute_p95:.2f} ms headroom)."
        )
        return 0
    print(
        f"VERDICT: OVER BUDGET by {compute_p95 - budget_ms:.2f} ms — dial back the "
        "native grab resolution, the encoder, or vision_sample_hz before enabling."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
