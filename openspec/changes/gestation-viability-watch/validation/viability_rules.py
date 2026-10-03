# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Score candidate gestation-viability rules against the validation runs."""
import json, glob, numpy as np
def verdict(ms, K=3):
    """ms: [(t_hours, marker_dict_or_None)] per withdrawal in order. Returns (t, rule) of the first unviable verdict, else None."""
    run=0; replicated=False; hist=[]
    for t,m in ms:
        ok=bool(m and m['marker']); run=run+1 if ok else 0; replicated |= run>=K
        hist.append((t,m))
        conclusive=[x for _,x in hist if x and x['pull'] is not None]
        if t>=6 and not conclusive: return (t,'R0 no conclusive measurement')
        last=[(tt,x['pull']) for tt,x in hist if x and x['pull'] is not None and tt> t-12]
        if t>=24 and not replicated and len(last)>=8:
            ts=np.array([a for a,_ in last]); ps=np.array([b for _,b in last]); slope=np.polyfit(ts,ps,1)[0]
            if np.median(ps)<0.12 and slope<=0.002: return (t,f'R1 pull {np.median(ps):.2f} slope {slope:+.3f}/h')
        if t>=48 and not replicated and len(last)>=8 and np.median([b for _,b in last])<0.3: return (t,'R2 pull too slow')
    return None
for f in sorted(glob.glob('valF/*.out.json')+glob.glob('valC/*.out.json')+glob.glob('val/*.out.json')):
    with open(f) as fh:
        d=json.load(fh)
    C=[c['label'] for c in d['spec']['conds']]
    for i,c in enumerate(C):
        ms=[(t,row[i]) for t,row in d['markers']]
        print(f"{f:28s} {c:18s} -> {verdict(ms)}")
