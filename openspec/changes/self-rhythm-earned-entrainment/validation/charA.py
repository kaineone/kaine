import itertools, math, sys, numpy as np
from scipy.signal import butter, sosfiltfilt, welch
G = dict(w=2.5, U=8.0, m=-0.25, ta=0.02, k=0.08)
taus = np.array([0.9, 1.0, 1.15, 1.3, 1.5, 1.7, 1.95, 2.2, 2.6, 3.0, 3.5])
owns = [0.1, 0.4, 0.7]; cols = [(o, t) for o in owns for t in taus]; B = len(cols)
o = np.array([c[0] for c in cols]); tr = np.array([c[1] for c in cols])
rng = np.random.default_rng(1); sub = 10; dt = 0.05 / sub; n = 3600
a = np.full(B, 0.05); s = np.ones(B); out = np.empty((n, B))
for i in range(n):
    for _ in range(sub):
        x = G['w'] * s * a + G['m'] + 0.02 * o + 0.02 * rng.standard_normal(B) * math.sqrt(0.001 / dt)
        a = a + dt * (-a + 1 / (1 + np.exp(-np.clip(x / G['k'], -60, 60)))) / G['ta']
        s = np.clip(s + dt * ((1 - s) / tr - G['U'] * s * a), 0, 1)
    out[i] = a
sos = butter(2, [0.3, 2.0], btype="band", fs=20.0, output="sos")
for j, (ow, t) in enumerate(cols):
    x = out[400:, j] - out[400:, j].mean()
    ff, P = welch(x, fs=20.0, nperseg=1200); P[0] = 0; kk = int(np.argmax(P))
    print(f"own {ow:.1f} tau {t:.2f}: f {ff[kk]:.2f} Hz  frac {P[(ff>=ff[kk]-0.1)&(ff<=ff[kk]+0.1)].sum()/P.sum():.2f}  amp {sosfiltfilt(sos, x).std():.3f}")
