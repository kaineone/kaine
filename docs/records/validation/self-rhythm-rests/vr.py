# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json,sys,re,numpy as np
import pathlib
REPO=pathlib.Path(__file__).resolve().parents[4]
src=open(REPO/'openspec/changes/archive/2026-10-03-gestation-viability-watch/validation/viability_rules.py').read()
ns={}
exec(src.split("for f in sorted")[0].replace("import json, glob, numpy as np",""),{'np':np},ns)
verdict=ns['verdict']
d=json.load(open(''+__import__('sys').argv[1]+''));C=[c['label'] for c in d['spec']['conds']]
for i,c in enumerate(C):
    ms=[(ta,row[i]) for t,row,ta in d['markers']]
    v=verdict(ms)
    print(f"{c:26s} {v}")
