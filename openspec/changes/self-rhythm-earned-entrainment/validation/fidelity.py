"""Class vs prototype: same seed, one condition, 1 h driven at eta 1 (sign -1), 70 bpm."""
import sys, math, numpy as np
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, "/home/elim/projects/kaine/.git/kaine-tools/analysis/self-rhythm-calibration")
from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator
import kaine, proto_r
print("kaine from", kaine.__file__)
from kaine.modules.womb_drive import MaternalDriveProvider
from kaine.modules.womb_signal import WombParams
cond = dict(bpm=70, scale=0.5, gain=0.1, eta=1.0, sign=-1, own=0.4, tau0=1.6)
rows = proto_r.run([cond], 1.0, win_s=300.0, withdraw_period=1e12)
proto_tau = [r[1][0]["tau"] for r in rows]
clock = proto_r.Clock(97200.0); p = WombParams(heartbeat_bpm=70); prov = MaternalDriveProvider(clock, p, seed=0, scale=0.5)
osc = make_self_rhythm_oscillator(seed=0, eta=1.0, plasticity_sign=-1.0, tau_rec=1.6)
taus = []
for i in range(72000):
    clock.t = i * 0.05
    osc.step(0.4, external_drive=float(prov()))
    if i % 6000 == 5999: taus.append(osc.tau_rec)
print("proto tau per 5 min:", [round(x, 3) for x in proto_tau])
print("class tau per 5 min:", [round(x, 3) for x in taus])
