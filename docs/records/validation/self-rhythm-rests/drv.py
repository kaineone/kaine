# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
import json,sys
import proto_rest
spec=json.load(open(sys.argv[1])); 
if len(sys.argv)>4: spec['hours']=float(sys.argv[4])
rests = sys.argv[3]=='rest'
rows=proto_rest.run(spec['conds'],spec['hours'],rests=rests,**spec.get('kw',{}))
json.dump(dict(spec=spec,rows=rows,markers=proto_rest.run.markers),open(sys.argv[2],'w'))
print('done')
