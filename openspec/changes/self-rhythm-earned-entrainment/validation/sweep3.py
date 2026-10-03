# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Generator retune: find mean-field params whose undriven oscillation spans ~0.5-1.6 Hz across tau_r
with a robust band-passed amplitude near the maternal range (1.0-1.35 Hz). Vectorised over configs x tau."""
import itertools, json, sys, math
import numpy as np
from scipy.signal import butter, sosfiltfilt, welch
taus = np.array([0.35, 0.45, 0.55, 0.65, 0.8, 1.0, 1.3, 1.7, 2.2, 3.0])
grid = list(itertools.product([1.5, 2.0, 2.5, 3.0], [3.0, 4.0, 6.0, 8.0], [-0.2, -0.25, -0.3, -0.35, -0.4], [0.02, 0.03, 0.05], [0.08, 0.1, 0.12]))
cols = [(g, t) for g in grid for t in taus]
B = len(cols); print("columns", B, flush=True)
w = np.array([c[0][0] for c in cols]); U = np.array([c[0][1] for c in cols]); m = np.array([c[0][2] for c in cols])
ta = np.array([c[0][3] for c in cols]); k = np.array([c[0][4] for c in cols]); tr = np.array([c[1] for c in cols])
rng = np.random.default_rng(0); sub = 10; dt = 0.05 / sub; n = 2400
a = np.full(B, 0.05); s = np.ones(B); out = np.empty((n, B), dtype=np.float32)
own = 0.4; og = 0.02
for i in range(n):
    for _ in range(sub):
        x = w * s * a + m + og * own + 0.02 * rng.standard_normal(B) * math.sqrt(0.001 / dt)
        a = a + dt * (-a + 1.0 / (1.0 + np.exp(-np.clip(x / k, -60, 60)))) / ta
        s = np.clip(s + dt * ((1.0 - s) / tr - U * s * a), 0.0, 1.0)
    out[i] = a
sos = butter(2, [0.3, 2.0], btype="band", fs=20.0, output="sos")
X = out[400:].astype(float)
res = {}
for j, (g, t) in enumerate(cols):
    x = X[:, j] - X[:, j].mean()
    if x.std() < 1e-4:
        f, amp, frac = 0.0, 0.0, 0.0
    else:
        ff, P = welch(x, fs=20.0, nperseg=1200); P[0] = 0; kk = int(np.argmax(P)); f = float(ff[kk])
        frac = float(P[(ff >= f - 0.1) & (ff <= f + 0.1)].sum() / P.sum()); amp = float(sosfiltfilt(sos, x).std())
    res.setdefault(g, []).append((float(t), f, amp, frac))
known = (2.0, 4.0, -0.3, 0.05, 0.1)
print("known config:", [(t, round(f, 2), round(a_, 3), round(fr, 2)) for t, f, a_, fr in res[known]])
cov = []
for g, rows in res.items():
    osc = [(t, f, a_) for t, f, a_, fr in rows if fr >= 0.3 and 0.3 <= f <= 2.0 and a_ > 0.03]
    if osc:
        fs = [f for _, f, _ in osc]; cov.append((max(fs) - min(fs), max(fs), g, [(t, round(f, 2), round(a_, 3)) for t, f, a_ in osc]))
cov.sort(key=lambda r: -r[0])
print("widest oscillating ranges:")
for r in cov[:10]: print("  span %.2f top %.2f" % (r[0], r[1]), r[2], r[3])
good = []
for g, rows in res.items():
    osc = [(t, f, amp) for t, f, amp, frac in rows if frac >= 0.4 and 0.3 <= f <= 2.0 and amp > 0.05]
    if len(osc) < 3: continue
    fs = [f for _, f, _ in osc]; fmin, fmax = min(fs), max(fs)
    near = [amp for _, f, amp in osc if 1.0 <= f <= 1.4]; slow = [amp for _, f, amp in osc if 0.5 <= f <= 0.9]
    if fmin <= 0.6 and fmax >= 1.45 and near and slow:
        ratio = min(near) / max(slow)
        good.append((ratio, g, [(t, round(f, 2), round(a_, 3)) for t, f, a_ in osc]))
good.sort(key=lambda x: -x[0])
for r in good[:12]: print(round(r[0], 2), r[1], r[2])
with open(sys.argv[1], "w") as fh:
    json.dump([[r[0], r[1], r[2]] for r in good], fh)
print("good", len(good))
