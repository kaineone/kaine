# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline calibration tool for the KAINE self-rhythm oscillator.

Subcommands
-----------
undriven    : map (tau_rec, own_drive) to the emergent oscillation frequency.
driven      : measure earned entrainment to a simulated maternal drive across
              300-second windows.

Results are printed as plain-text tables; `--json PATH` writes the raw records.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Iterable

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt, welch

from kaine.modules.womb_drive import MaternalDriveProvider
from kaine.modules.womb_signal import WombParams, heartbeat_phase
from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator

STEP_HZ: float = 20.0


class SimClock:
    """Minimal clock for offline simulations."""

    def __init__(self, offset: float = 97200.0) -> None:
        self.t: float = 0.0
        self.offset: float = offset

    def womb_seconds(self) -> float:
        return self.offset + self.t


def _dominant_frequency(x: np.ndarray, fs: float) -> float:
    """Return the dominant non-zero frequency of a mean-centred signal."""
    x0 = x - x.mean()
    nperseg = min(len(x0), int(60.0 * fs))
    if nperseg < 2:
        return 0.0
    freqs, psd = welch(x0, fs=fs, nperseg=nperseg)
    mask = freqs > 0.0
    freqs_pos = freqs[mask]
    psd_pos = psd[mask]
    if len(psd_pos) == 0 or psd_pos.sum() <= 0.0:
        return 0.0
    return float(freqs_pos[np.argmax(psd_pos)])


def window_metrics(
    t: np.ndarray,
    rate: np.ndarray,
    beat: np.ndarray,
    tau_rec: float,
    seed: int,
    params: WombParams,
    step_hz: float = STEP_HZ,
) -> dict:
    """PLV and frequency metrics for one 300-second window.

    The rate signal is zero-phase band-pass filtered (0.4–2.0 Hz), Hilbert
    transformed, and the first/last 2 s are trimmed before computing PLV.
    PLV is also computed against 19 surrogate beats; the maximum surrogate
    PLV is reported.
    """
    sos = butter(2, (0.4, 2.0), btype="band", fs=step_hz, output="sos")
    filtered = sosfiltfilt(sos, rate - rate.mean())
    phase_rate = np.angle(hilbert(filtered))
    edge = int(2.0 * step_hz)

    if edge * 2 >= len(phase_rate):
        trim = slice(None)
    else:
        trim = slice(edge, -edge)

    d_phase = phase_rate[trim]
    d_beat = beat[trim]
    plv = float(abs(np.mean(np.exp(1j * (d_phase - d_beat)))))

    surrogate_max = 0.0
    times = t[trim]
    for k in range(19):
        surr_seed = seed + 1000 + k
        surr_beat = 2.0 * math.pi * np.asarray(
            [heartbeat_phase(surr_seed, float(ti), params) for ti in times]
        )
        surr_plv = float(abs(np.mean(np.exp(1j * (d_phase - surr_beat)))))
        if surr_plv > surrogate_max:
            surrogate_max = surr_plv

    dominant_hz = _dominant_frequency(rate, step_hz)
    return {
        "plv": plv,
        "surrogate_max": surrogate_max,
        "passes": plv > surrogate_max,
        "dominant_hz": dominant_hz,
        "tau_rec": float(tau_rec),
    }


def simulate_undriven(
    taus: Iterable[float],
    owns: Iterable[float],
    minutes: float,
    seed: int,
) -> list[dict]:
    """Run the oscillator without external drive for several (tau, own) pairs.

    The first 30 s are discarded, then Welch's method is used to estimate the
    dominant non-zero frequency and the fraction of power within +/-0.15 Hz of
    that peak.
    """
    dt = 1.0 / STEP_HZ
    total_steps = int(minutes * 60.0 / dt)
    discard_steps = int(30.0 / dt)
    records: list[dict] = []

    for tau in taus:
        for own in owns:
            osc = make_self_rhythm_oscillator(
                seed=seed,
                eta=0.0,
                tau_rec=tau,
                tau_min=min(0.3, tau),
                tau_max=max(2.0, tau),
                step_hz=STEP_HZ,
            )
            if osc is None:
                raise RuntimeError("snnTorch is not available")

            rates = np.empty(total_steps, dtype=float)
            for i in range(total_steps):
                osc.step(own, external_drive=None)
                rates[i] = osc.last_rate

            x = rates[discard_steps:]
            peak_hz = _dominant_frequency(x, STEP_HZ)
            freqs, psd = welch(x - x.mean(), fs=STEP_HZ, nperseg=min(len(x), int(60.0 * STEP_HZ)))
            band = (freqs >= peak_hz - 0.15) & (freqs <= peak_hz + 0.15)
            pos_total = float(psd[freqs > 0.0].sum())
            fraction = float(psd[band].sum() / pos_total) if pos_total > 0.0 else 0.0

            records.append(
                {
                    "tau": float(tau),
                    "own": float(own),
                    "dominant_hz": peak_hz,
                    "fraction": fraction,
                    "mean_rate": float(x.mean()),
                    "std_rate": float(x.std()),
                    "minutes": float(minutes),
                    "seed": seed,
                }
            )

    return records


def simulate_driven(
    bpms: Iterable[float],
    scale: float | Iterable[float],
    etas: Iterable[float],
    hours: float,
    seed: int,
    own: float,
    afferent_gain: float,
    plasticity_sign: float,
) -> list[dict]:
    """Run the oscillator with a simulated maternal drive and report per-window metrics.

    One row is emitted for every consecutive 300-second window.  The simulation
    is fully deterministic for a given seed.
    """
    scales = [scale] if isinstance(scale, (int, float)) else list(scale)

    dt = 1.0 / STEP_HZ
    total_steps = int(hours * 3600.0 / dt)
    window_steps = int(300.0 / dt)

    records: list[dict] = []

    for bpm in bpms:
        for eta in etas:
            for sc in scales:
                params = WombParams(heartbeat_bpm=bpm)
                clock = SimClock()
                prov = MaternalDriveProvider(clock, params, seed=seed, scale=sc)
                osc = make_self_rhythm_oscillator(
                    seed=seed,
                    eta=eta,
                    afferent_gain=afferent_gain,
                    plasticity_sign=plasticity_sign,
                    step_hz=STEP_HZ,
                )
                if osc is None:
                    raise RuntimeError("snnTorch is not available")

                ts = np.empty(window_steps, dtype=float)
                rates = np.empty(window_steps, dtype=float)
                beats = np.empty(window_steps, dtype=float)

                idx = 0
                for step_i in range(total_steps):
                    t = step_i * dt
                    clock.t = t
                    ext = float(prov())
                    osc.step(own, external_drive=ext)
                    rate = osc.last_rate
                    beat = 2.0 * math.pi * float(
                        heartbeat_phase(seed, clock.womb_seconds(), params)
                    )
                    tau_rec = osc.tau_rec

                    ts[idx] = t
                    rates[idx] = rate
                    beats[idx] = beat
                    idx += 1

                    if idx == window_steps:
                        metrics = window_metrics(
                            ts.copy(),
                            rates.copy(),
                            beats.copy(),
                            tau_rec,
                            seed,
                            params,
                            STEP_HZ,
                        )
                        metrics.update(
                            {
                                "bpm": float(bpm),
                                "eta": float(eta),
                                "scale": float(sc),
                                "hours": t / 3600.0,
                                "seed": seed,
                                "own": float(own),
                                "afferent_gain": float(afferent_gain),
                                "plasticity_sign": float(plasticity_sign),
                            }
                        )
                        records.append(metrics)
                        idx = 0

    return records


def _print_undriven(records: list[dict]) -> None:
    header = f"{'tau':>6} {'own':>6} {'dominant_hz':>12} {'fraction':>10} {'mean_rate':>10} {'std_rate':>10}"
    print(header)
    for r in records:
        print(
            f"{r['tau']:6.2f} {r['own']:6.2f} "
            f"{r['dominant_hz']:12.3f} {r['fraction']:10.3f} "
            f"{r['mean_rate']:10.4f} {r['std_rate']:10.4f}"
        )


def _print_driven(records: list[dict]) -> None:
    header = (
        f"{'hours':>7} {'plv':>7} {'surr_max':>9} {'passes':>7} "
        f"{'dominant_hz':>12} {'tau_rec':>8} {'bpm':>6} {'eta':>6}"
    )
    print(header)
    for r in records:
        print(
            f"{r['hours']:7.3f} {r['plv']:7.4f} {r['surrogate_max']:9.4f} "
            f"{str(r['passes']):>7} {r['dominant_hz']:12.3f} "
            f"{r['tau_rec']:8.4f} {r['bpm']:6.1f} {r['eta']:6.2f}"
        )


def _write_json(path: str, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline calibration for the KAINE self-rhythm oscillator."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_und = sub.add_parser("undriven", help="map intrinsic tau to frequency")
    p_und.add_argument("--tau", type=float, nargs="+", required=True)
    p_und.add_argument("--own", type=float, nargs="+", required=True)
    p_und.add_argument("--minutes", type=float, default=5.0)
    p_und.add_argument("--seed", type=int, default=0)
    p_und.add_argument("--json", type=str, default=None)

    p_drv = sub.add_parser("driven", help="measure earned entrainment to drive")
    p_drv.add_argument("--bpm", type=float, nargs="+", required=True)
    p_drv.add_argument("--scale", type=float, default=0.5)
    p_drv.add_argument("--eta", type=float, nargs="+", required=True)
    p_drv.add_argument("--hours", type=float, default=1.0)
    p_drv.add_argument("--seed", type=int, default=0)
    p_drv.add_argument("--own", type=float, default=0.1)
    p_drv.add_argument("--afferent-gain", type=float, default=0.05)
    p_drv.add_argument(
        "--plasticity-sign", type=float, choices=[1.0, -1.0], default=1.0
    )
    p_drv.add_argument("--json", type=str, default=None)

    args = parser.parse_args(argv)

    if args.command == "undriven":
        records = simulate_undriven(args.tau, args.own, args.minutes, args.seed)
        _print_undriven(records)
    else:
        records = simulate_driven(
            args.bpm,
            args.scale,
            args.eta,
            args.hours,
            args.seed,
            args.own,
            args.afferent_gain,
            args.plasticity_sign,
        )
        _print_driven(records)

    if args.json:
        _write_json(args.json, records)

    return 0


if __name__ == "__main__":
    sys.exit(main())
