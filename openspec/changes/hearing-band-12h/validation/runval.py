# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Run the archived A.7 entrainment harness (proto_r.py) unchanged on the current classes.

The harness predates the womb -> stimulus_source rename; this shim maps the old
module and class names onto the current ones and gives the harness clock the
current method name. It edits nothing in the harness.
usage: runval.py REPO SPEC.json OUT.json
"""
import json, sys, types
repo, spec_path, out = sys.argv[1:4]
sys.path.insert(0, repo)
import kaine.modules.stimulus_source_drive as drv
import kaine.modules.stimulus_source_signal as sig
old = types.ModuleType("kaine.modules.womb_signal")
old.WombParams = sig.StimulusSourceParams
old.heartbeat_phase = sig.heartbeat_phase
old.beat_pulse = sig.beat_pulse
sys.modules["kaine.modules.womb_signal"] = old
sys.modules["kaine.modules.womb_drive"] = drv
vdir = repo + "/openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation"  # the archived harness, unchanged
sys.path.insert(0, vdir)
import proto_r
proto_r.Clock.stimulus_source_seconds = proto_r.Clock.womb_seconds
spec = json.load(open(spec_path))
rows = proto_r.run(spec["conds"], spec["hours"], **spec.get("kw", {}))
with open(out, "w") as fh:
    json.dump(dict(spec=spec, rows=rows, withdrawals=proto_r.run.withdrawals, markers=proto_r.run.markers), fh)
print("done", out)
