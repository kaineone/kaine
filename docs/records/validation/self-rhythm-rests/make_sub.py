# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json, pathlib
HERE=pathlib.Path(__file__).resolve().parent
with open(HERE/'all.json') as _f: d=json.load(_f)
keep=['valF_v:70 seed0','valF_v:jittered beat','valF_v:foreign 0->1','valF_v:foreign 2->3','valF_v:no drive','valF_v:80 seed0','valF_v:60 seed0','valC_c:foreign 5->6']
d['conds']=[c for c in d['conds'] if c['label'] in keep]; print(len(d['conds']))
with open(HERE/'sub.json','w') as _f: json.dump(d,_f)
