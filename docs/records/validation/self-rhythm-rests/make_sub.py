# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json, pathlib
HERE=pathlib.Path(__file__).resolve().parent
d=json.load(open(HERE/'all.json'))
keep=['valF_v:70 seed0','valF_v:jittered beat','valF_v:foreign 0->1','valF_v:foreign 2->3','valF_v:no drive','valF_v:80 seed0','valF_v:60 seed0','valC_c:foreign 5->6']
d['conds']=[c for c in d['conds'] if c['label'] in keep]; print(len(d['conds']))
json.dump(d,open(HERE/'sub.json','w'))
