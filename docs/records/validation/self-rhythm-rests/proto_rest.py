# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Batched prototype of option R: Tabak-style mean-field generator + weak afferent maternal drive
+ Righetti-style phase-projected plasticity on ln(tau_r). Uses the real MaternalDriveProvider and
heartbeat_phase. Each batch column is one condition. Reports per-window band-limited PLV vs the true
beat and the max over K foreign-mother surrogates, dominant frequency, and tau_r."""
import math, sys, json
import numpy as np
from scipy.signal import butter, sosfiltfilt, hilbert, welch
from pathlib import Path
# The repository root (this file lives in openspec/changes/<change>/validation/).
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from kaine.modules.stimulus_source_drive import MaternalDriveProvider
from kaine.modules.stimulus_source_signal import StimulusSourceParams as WombParams, heartbeat_phase

class JitterBeat:
    """Arrhythmic control: beat phase advancing with renewal (gamma) intervals of the same
    mean rate and coefficient of variation `cv`; the drive is the bounded pulse at that phase."""
    def __init__(self, clock, params, seed, scale, cv=0.3):
        from kaine.modules.stimulus_source_signal import beat_pulse
        self._pulse = beat_pulse; self.clock = clock; self.scale = scale
        self.rng = np.random.default_rng(seed + 555); self.mean = 60.0 / params.heartbeat_bpm; self.cv = cv
        self.t0 = clock.stimulus_source_seconds(); self.next = self.t0 + self._draw(); self.k = 0
    def _draw(self):
        k = 1.0 / self.cv ** 2
        return float(self.rng.gamma(k, self.mean / k))
    def phase(self, t):
        while t >= self.next:
            self.t0 = self.next; self.next = self.t0 + self._draw(); self.k += 1
        return self.k + (t - self.t0) / (self.next - self.t0)
    def __call__(self):
        return self.scale * 0.4 * float(self._pulse(self.phase(self.clock.stimulus_source_seconds()) % 1.0))

class Clock:
    def __init__(self, off): self.t = 0.0; self.off = off
    def stimulus_source_seconds(self): return self.off + self.t

def run(conds, hours, *, w=2.0, k=0.1, tau_a=0.05, U=4.0, margin=-0.3, own_gain=0.05, sub=10, win_s=300.0, K=19,
        mean_tau=10.0, seed=0, offset=97200.0, rests=True, record_every=1, withdraw_period=1800.0, withdraw_s=20.0, tau_min=0.9, tau_max=3.0):
    """conds: list of dicts with keys bpm, scale (None = no drive), gain (afferent), eta, sign, own, tau0, beat_mode
    ('own'|'foreign'|'jitter'), foreign_seed."""
    B = len(conds); rng = np.random.default_rng(seed)
    clock = Clock(offset)
    provs, params = [], []
    for c in conds:
        p = WombParams(heartbeat_bpm=c["bpm"]); params.append(p)
        drive_seed = c.get("drive_seed", seed)
        if c["scale"] is None:
            provs.append(None)
        elif c.get("beat_mode") == "jitter":
            provs.append(JitterBeat(clock, p, drive_seed, c["scale"]))
        else:
            provs.append(MaternalDriveProvider(clock, p, seed=drive_seed, scale=c["scale"]))
    gain = np.array([c["gain"] for c in conds]); eta = np.array([c["eta"] for c in conds]); sign = np.array([c.get("sign", 1.0) for c in conds])
    own0 = np.array([c["own"] for c in conds]); own = own0.copy(); own_mode = [c.get("own_mode", "const") for c in conds]
    ln_tau = np.log(np.array([c.get("tau0", 1.2) for c in conds]))
    a = np.full(B, 0.05); s = np.ones(B); ext_m = np.zeros(B); a_m = np.zeros(B); s_m = np.ones(B)
    dt_step = 0.05; dt = dt_step / sub; alpha = dt_step / mean_tau
    n_steps = int(hours * 3600 * 20)
    ACT, REST = (2996.0, 1410.0) if rests else (1e18, 0.0)
    cyc = ACT + REST
    def is_rest(t): return (t % cyc) >= ACT
    # withdrawal intervals: first at awake 1770 s, then 1800 s after each start, deferred until >=360 s since the
    # last rest ended (300 s driven window + 60 s settling) and >=30 s before the next rest begins.
    wd_flags = np.zeros(n_steps, dtype=bool)
    ta = 0.0
    ta_arr = np.empty(n_steps)
    for i in range(n_steps):
        tt = i * dt_step
        ta_arr[i] = ta
        if not is_rest(tt): ta += dt_step
    i = 0; due_ta = 1770.0
    while i < n_steps:
        tt = i * dt_step
        if (not is_rest(tt)) and ta_arr[i] >= due_ta:
            since_rest = tt % cyc; to_rest = ACT - (tt % cyc); first_ok = since_rest >= 360.0
            if first_ok and to_rest >= 30.0:
                n = int(withdraw_s * 20); wd_flags[i:i + n] = True
                due_ta = ta_arr[i] + withdraw_period; i += n; continue
        i += 1
    win = int(win_s * 20)
    sos = butter(2, [0.3, 2.0], btype="band", fs=20.0, output="sos")
    buf_a = np.empty((win, B)); buf_t = np.empty(win)
    rows = []

    hist_n = int((win_s + withdraw_s + 30.0) * 20); hist_a = np.zeros((hist_n, B)); hist_t = np.zeros(hist_n); hist_w = np.zeros(hist_n, dtype=bool); hp = 0
    markers = []; base = [[] for _ in range(B)]
    sos_w = butter(2, [0.3, 2.0], btype="band", fs=20.0, output="sos")
    for i in range(n_steps):
        clock.t = i * dt_step
        if i % 20 == 0:
            for b, m in enumerate(own_mode):
                if m == "rest": own[b] = 0.1 + 0.6 * float(np.clip(rng.normal(0.5, 0.15), 0, 1))
                elif m == "rand": own[b] = float(rng.uniform(0.1, 0.7))
        withdrawing = bool(wd_flags[i])
        tw = 0.0
        ext = np.array([0.0 if (pv is None or withdrawing) else float(pv()) for pv in provs])
        for _ in range(sub):
            x = w * s * a + margin + own_gain * own + gain * ext + 0.02 * rng.standard_normal(B) * math.sqrt(0.001 / dt)
            ainf = 1.0 / (1.0 + np.exp(-x / k))
            a = a + dt * (-a + ainf) / tau_a
            s = np.clip(s + dt * ((1.0 - s) / np.exp(ln_tau) - U * s * a), 0.0, 1.0)
        ext_m += alpha * (ext - ext_m); a_m += alpha * (a - a_m); s_m += alpha * (s - s_m)
        F = ext - ext_m; xq = a - a_m; yq = s - s_m; r = np.sqrt(xq * xq + yq * yq)
        q = np.where(r > 1e-9, yq / np.maximum(r, 1e-12), 0.0)
        has = np.array([pv is not None and not withdrawing for pv in provs])
        ln_tau = np.clip(ln_tau + np.where(has, sign * eta * F * q * dt_step, 0.0), math.log(tau_min), math.log(tau_max))
        hist_a[hp % hist_n] = a; hist_t[hp % hist_n] = clock.stimulus_source_seconds(); hist_w[hp % hist_n] = withdrawing; hp += 1
        if (not withdrawing) and hp > 1 and hist_w[(hp - 2) % hist_n] and hp >= hist_n:
            order = np.arange(hp - hist_n, hp) % hist_n
            A = hist_a[order]; T = hist_t[order]; W = hist_w[order]
            wd_idx = np.where(W)[0]; w0 = wd_idx[0]
            idle = np.arange(max(0, w0 - int(win_s * 20)), w0)
            mrow = []
            for b, c in enumerate(conds):
                xs = A[idle, b] - A[idle, b].mean(); xw = A[wd_idx, b] - A[wd_idx, b].mean()
                if xs.std() < 1e-6:
                    mrow.append(None); continue
                ph = np.angle(hilbert(sosfiltfilt(sos, xs)))[40:-40]; tt = T[idle][40:-40]
                beat_seed = c.get("score_seed", c.get("drive_seed", seed))
                beat = 2 * np.pi * np.asarray(heartbeat_phase(beat_seed, tt, params[b]))
                plv = float(abs(np.mean(np.exp(1j * (ph - beat)))))
                sur = max(float(abs(np.mean(np.exp(1j * (ph - 2 * np.pi * np.asarray(heartbeat_phase(beat_seed + 1000 + kk, tt, params[b]))))))) for kk in range(K))
                bp_d = sosfiltfilt(sos, xs); bp_w = sosfiltfilt(sos, xw) if len(xw) > 30 else xw
                sustain = bool(bp_w.std() >= 0.5 * bp_d.std() and bp_w.std() > 0)
                phw = np.unwrap(np.angle(hilbert(bp_w))); fw = float(np.polyfit(np.arange(len(phw)) / 20.0, phw, 1)[0] / (2 * np.pi))
                fbeat = float(np.polyfit(tt, np.unwrap(beat), 1)[0] / (2 * np.pi))
                if len(base[b]) < 3: base[b].append(fw)
                f0 = float(np.mean(base[b])) if len(base[b]) >= 3 else None
                pull = (1 - abs(fw - fbeat) / abs(f0 - fbeat)) if (f0 is not None and abs(f0 - fbeat) >= 0.05) else None
                marker = None if pull is None else bool(plv > sur and sustain and pull >= 0.5)
                mrow.append(dict(plv=plv, sur=sur, sustain=sustain, fw=fw, fbeat=fbeat, f0=f0, pull=pull, marker=marker))
            markers.append((round(clock.t / 3600, 3), mrow, round(float(ta_arr[i]) / 3600, 3)))
        j = i % win; buf_a[j] = a; buf_t[j] = clock.stimulus_source_seconds()
        if j == win - 1:
            ts = buf_t.copy(); row = []
            for b, c in enumerate(conds):
                xs = buf_a[:, b] - buf_a[:, b].mean()
                if xs.std() < 1e-6:
                    row.append(dict(plv=0.0, sur=0.0, f=0.0, tau=float(np.exp(ln_tau[b])))); continue
                ph = np.angle(hilbert(sosfiltfilt(sos, xs)))[40:-40]; tt = ts[40:-40]
                beat_seed = c.get("score_seed", c.get("drive_seed", seed))
                beat = 2 * np.pi * np.asarray(heartbeat_phase(beat_seed, tt, params[b]))
                plv = float(abs(np.mean(np.exp(1j * (ph - beat)))))
                sur = max(float(abs(np.mean(np.exp(1j * (ph - 2 * np.pi * np.asarray(heartbeat_phase(beat_seed + 1000 + kk, tt, params[b]))))))) for kk in range(K))
                f, P = welch(xs, fs=20.0, nperseg=min(len(xs), 1200)); P[0] = 0
                row.append(dict(plv=plv, sur=sur, f=float(f[np.argmax(P)]), tau=float(np.exp(ln_tau[b]))))
            rows.append((round(ts[-1] - offset, 1), row))
    run.withdrawals = []; run.markers = markers
    return rows

if __name__ == "__main__":
    spec = json.loads(sys.argv[1]); out = sys.argv[2]
    rows = run(spec["conds"], spec["hours"], **spec.get("kw", {}))
    with open(out, "w") as fh:
        json.dump(dict(spec=spec, rows=rows, withdrawals=run.withdrawals, markers=run.markers), fh)
    for t, row in rows:
        print("%6.2fh " % (t / 3600) + " | ".join("%s plv %.2f sur %.2f f %.2f tau %.2f" % (c.get("label", b), r["plv"], r["sur"], r["f"], r["tau"]) for b, (c, r) in enumerate(zip(spec["conds"], row))), flush=True)
