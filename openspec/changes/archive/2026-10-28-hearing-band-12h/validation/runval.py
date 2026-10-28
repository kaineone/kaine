# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Run the archived A.7 entrainment harness (proto_r.py) unchanged on the current classes.

The harness predates the rename of the developmental stimulus; this shim reads
the old module, class and clock-method names from the rename table in
kaine/legacy_names.py, maps them onto the current modules, and gives the
harness clock the current method name. It edits nothing in the harness.
usage: runval.py REPO SPEC.json OUT.json
"""
import json, sys, types
repo, spec_path, out = sys.argv[1:4]
sys.path.insert(0, repo)
import kaine.modules.stimulus_source_drive as drv
import kaine.modules.stimulus_source_signal as sig
from kaine.legacy_names import DEVELOPMENTAL
old, entry = next((k, v) for k, v in DEVELOPMENTAL.items() if v["new_key"] == "stimulus_source")
old_signal = types.ModuleType(f"kaine.modules.{old}_signal")
setattr(old_signal, entry["old_class"] + "Params", sig.StimulusSourceParams)
old_signal.heartbeat_phase = sig.heartbeat_phase
old_signal.beat_pulse = sig.beat_pulse
sys.modules[f"kaine.modules.{old}_signal"] = old_signal
sys.modules[f"kaine.modules.{old}_drive"] = drv
vdir = repo + "/openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation"  # the archived harness, unchanged
sys.path.insert(0, vdir)
import proto_r
proto_r.Clock.stimulus_source_seconds = getattr(proto_r.Clock, f"{old}_seconds")
with open(spec_path) as fh:
    spec = json.load(fh)
rows = proto_r.run(spec["conds"], spec["hours"], **spec.get("kw", {}))
with open(out, "w") as fh:
    json.dump(dict(spec=spec, rows=rows, withdrawals=proto_r.run.withdrawals, markers=proto_r.run.markers), fh)
print("done", out)
