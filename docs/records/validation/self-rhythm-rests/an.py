# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json,sys,numpy as np
d=json.load(open(sys.argv[1])); C=d['spec']['conds']; M=d['markers']
for i,c in enumerate(C):
    ms=[(t,row[i],ta) for t,row,ta in M if row[i] is not None]
    run=0;first=None;firsta=None;singles=0;n=0;pulls=[]
    for t,m,ta in ms:
        if m['pull'] is not None: pulls.append((ta,m['pull']))
        if m['marker'] is None: run=0; continue
        n+=1
        if m['marker']:
            singles+=1;run+=1
            if run>=3 and first is None: first=t;firsta=ta
        else: run=0
    # viability (paper A.7): P = pulls in last 12 awake h; need >=8
    verdict=None
    for j,(ta,_) in enumerate(pulls):
        P=[(a,p) for a,p in pulls[:j+1] if ta-a<=12]
        marker_true = first is not None and firsta<=ta
        if marker_true: break
        med=np.median([p for _,p in P]) if len(P)>=8 else None
        sl=np.polyfit([a for a,_ in P],[p for _,p in P],1)[0] if len(P)>=8 else None
        if ta>=60: verdict=('R3',ta);break
        if ta>=48 and med is not None and med<0.3: verdict=('R2',ta);break
        if ta>=24 and med is not None and med<0.12 and sl<=0.002: verdict=('R1',ta);break
        if ta>=6 and not pulls[:j+1]: verdict=('R0',ta);break
    if verdict is None and not pulls and ms and ms[-1][2]>=6: verdict=('R0',6)
    ff='%.1fh wall / %.1fh awake'%(first,firsta) if first is not None else 'never'
    print(f"{c['label']:26s} rep3 {ff:24s} single {singles}/{n} ({100*singles/max(1,n):.1f}%) viab={verdict} lastfw={ms[-1][1]['fw'] if ms else None:.3f} fbeat={ms[-1][1]['fbeat'] if ms else None:.3f}")
