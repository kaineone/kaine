"""Class vs prototype: same seed, one condition, 1 h driven at eta 1 (sign -1), 70 bpm.

Run from anywhere: python fidelity.py (the class and the prototype must use the same generator
parameters; pass them to both if you change the defaults)."""
import sys, math, numpy as np
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3])); sys.path.insert(0, str(HERE))
from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator
import kaine, proto_r
from kaine.modules.womb_drive import MaternalDriveProvider
from kaine.modules.womb_signal import WombParams
cond = dict(bpm=70, scale=0.5, gain=0.03, eta=1.0, sign=-1, own=0.4, tau0=2.1)
GEN = dict(w=2.5, U=8.0, margin=-0.25, tau_a=0.02, k=0.08, own_gain=0.02, tau_min=0.9, tau_max=2.3)
rows = proto_r.run([cond], 1.0, win_s=300.0, withdraw_period=1e12, **GEN)
proto_tau = [r[1][0]["tau"] for r in rows]
clock = proto_r.Clock(97200.0); p = WombParams(heartbeat_bpm=70); prov = MaternalDriveProvider(clock, p, seed=0, scale=0.5)
osc = make_self_rhythm_oscillator(seed=0, eta=1.0)  # class defaults are the final settings
taus = []
for i in range(72000):
    clock.t = i * 0.05
    osc.step(0.4, external_drive=float(prov()))
    if i % 6000 == 5999: taus.append(osc.tau_rec)
print("proto tau per 5 min:", [round(x, 3) for x in proto_tau])
print("class tau per 5 min:", [round(x, 3) for x in taus])
