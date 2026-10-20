# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Replicated passes (three in a row) per condition from runval.py output files: rep3.py NAME [NAME...] reads NAME.out.json."""
import json, sys
for k in sys.argv[1:]:
    with open(f"{k}.out.json") as fh:
        d = json.load(fh)
    C = d["spec"]["conds"]; M = d["markers"]
    print("==", k)
    for i, c in enumerate(C):
        ms = [(t, row[i]) for t, row in M if row[i] is not None]
        run = 0; first3 = None; singles = 0; n = 0
        for t, m in ms:
            if m["marker"] is None: run = 0; continue
            n += 1
            if m["marker"]:
                singles += 1; run += 1
                if run >= 3 and first3 is None: first3 = t
            else:
                run = 0
        print(f"  {c['label']:16s} replicated pass {('%.1fh' % first3) if first3 is not None else 'never':>6} | single passes {singles}/{n} ({100*singles/max(1,n):.1f}%)")
