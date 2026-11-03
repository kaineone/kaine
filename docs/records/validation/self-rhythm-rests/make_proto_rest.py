# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Builds proto_rest.py from the archived proto_r.py (developmental rests added) and merges the five
archived run specs into all.json. Run from anywhere: python make_proto_rest.py"""
import pathlib
REPO=pathlib.Path(__file__).resolve().parents[4]
with open(REPO/'openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation/proto_r.py') as _f: src=_f.read()
# header/imports
src=src.replace("sys.path.insert(0, str(Path(__file__).resolve().parents[4]))","sys.path.insert(0, str(Path(__file__).resolve().parents[4]))")
src=src.replace("from kaine.modules.womb_drive import MaternalDriveProvider","from kaine.modules.stimulus_source_drive import MaternalDriveProvider")
src=src.replace("from kaine.modules.womb_signal import WombParams, heartbeat_phase","from kaine.modules.stimulus_source_signal import StimulusSourceParams as WombParams, heartbeat_phase")
src=src.replace("from kaine.modules.womb_signal import beat_pulse","from kaine.modules.stimulus_source_signal import beat_pulse")
src=src.replace("def womb_seconds(self)","def stimulus_source_seconds(self)").replace("clock.womb_seconds()","clock.stimulus_source_seconds()")
# rest schedule: precompute withdrawal flags and rest flags per step
src=src.replace("    n_steps = int(hours * 3600 * 20)\n",
"""    n_steps = int(hours * 3600 * 20)
    ACT, REST = (2996.0, 1410.0) if rests else (1e18, 0.0)
    cyc = ACT + REST
    def is_rest(t): return (t % cyc) >= ACT
    # withdrawal intervals: first at awake 1770 s, then 1800 s after each start, deferred until >=360 s since the
    # last rest ended (300 s driven window + 60 s settling) and >=30 s before the next rest begins.
    wd_flags = np.zeros(n_steps, dtype=bool); awake_t = np.zeros(n_steps)
    ta = 0.0; due_ta = 1770.0; t = 0.0; wd_end_t = -1.0
    ta_arr = np.empty(n_steps)
    for i in range(n_steps):
        tt = i * dt_step
        ta_arr[i] = ta
        if not is_rest(tt): ta += dt_step
    i = 0; due_ta = 1770.0
    while i < n_steps:
        tt = i * dt_step
        if (not is_rest(tt)) and ta_arr[i] >= due_ta:
            since_rest = (tt % cyc) if rests else 1e9
            to_rest = (ACT - (tt % cyc)) if rests else 1e9
            first_ok = (since_rest >= 360.0) or (not rests and tt >= 360.0)
            if rests and tt < cyc: first_ok = since_rest >= 360.0
            if first_ok and to_rest >= 30.0:
                n = int(withdraw_s * 20); wd_flags[i:i + n] = True
                due_ta = ta_arr[i] + withdraw_period; i += n; continue
        i += 1
""")
src=src.replace("seed=0, offset=97200.0,","seed=0, offset=97200.0, rests=True,")
src=src.replace("        tw = clock.t % withdraw_period\n        withdrawing = withdraw_period - withdraw_s - 10.0 <= tw < withdraw_period - 10.0\n","        withdrawing = bool(wd_flags[i])\n        tw = 0.0\n")
# drop wd_buf block
a=src.index("        # record the 10 s before"); b=src.index("        ln_tau = np.clip(")
src=src[:a]+src[b:]
src=src.replace("markers.append((round(clock.t / 3600, 3), mrow))","markers.append((round(clock.t / 3600, 3), mrow, round(float(ta_arr[i]) / 3600, 3)))")
src=src.replace("    run.withdrawals = wd_rows; run.markers = markers","    run.withdrawals = []; run.markers = markers")
src=src.replace('# SPDX-License-Identifier: LicenseRef-CAL-0.2','# SPDX-License-Identifier: LicenseRef-CAL-0.5',1)
with open(REPO/'docs/records/validation/self-rhythm-rests/proto_rest.py','w') as _f: _f.write(src)
# --- second step: fix-up of the patched file, and the merged input spec ---
OUT=REPO/'docs/records/validation/self-rhythm-rests'
with open(OUT/'proto_rest.py') as _f: s=_f.read()
a=s.index("            since_rest = (tt % cyc)"); b=s.index("            if first_ok and to_rest")
s=s[:a]+"            since_rest = tt % cyc; to_rest = ACT - (tt % cyc); first_ok = since_rest >= 360.0\n"+s[b:]
s=s.replace("    rest_arr = np.array([is_rest(i * dt_step) for i in range(n_steps)])\n","")
with open(OUT/'proto_rest.py','w') as _f: _f.write(s)
import json
d=str(REPO/'openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation/runs')+'/'
allc=[];kw=None
for f in ['valF_v2_main','valC_true','valF_v4_specificity','valF_v3_controls','valC_controls']:
    with open(d+f+'.json') as _f: sp=json.load(_f)
    for c in sp['conds']: c=dict(c); c['label']=f[:6]+':'+c.get('label',''); allc.append(c)
    kw=sp['kw'] if kw is None else kw
    assert sp['kw']==kw,f
with open(OUT/'all.json','w') as _f: json.dump(dict(conds=allc,hours=96,kw=kw),_f); print(len(allc))
