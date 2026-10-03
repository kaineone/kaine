import json, numpy as np, sys
def load(k): return json.load(open(f'{k}.out.json'))
def summarize(k):
    d=load(k); C=d['spec']['conds']; M=d['markers']
    out=[]
    for i,c in enumerate(C):
        ms=[(t,row[i]) for t,row in M if row[i] is not None]
        passes=[(t,m) for t,m in ms if m['marker']]
        first=passes[0][0] if passes else None
        early=[m for t,m in ms if t<=6]
        late=[m for t,m in ms if t>=48]
        share_late=np.mean([bool(m['marker']) for m in late]) if late else float('nan')
        fw_late=np.mean([m['fw'] for m in late]) if late else float('nan')
        pull_late=np.nanmean([m['pull'] if m['pull'] is not None else np.nan for m in late]) if late else float('nan')
        out.append(dict(label=c['label'], first=first, any_early=any(bool(m['marker']) for m in early), share_late=share_late, fw_late=fw_late, beat=c['bpm']/60, pull_late=pull_late, n=len(ms), plv1h=np.median([m['plv'] for t,m in ms if t<=1.5]) if ms else None))
    return out
for k in sys.argv[1:]:
    print('==', k)
    for r in summarize(k):
        print(f"  {r['label']:16s} first pass {('%.1fh'%r['first']) if r['first'] is not None else 'never':>6} | any pass <=6h {r['any_early']} | pass share 48-96h {r['share_late']:.2f} | f_w 48-96h {r['fw_late']:.2f} (beat {r['beat']:.2f}) | pull {r['pull_late']:.2f} | PLV hour1 {r['plv1h'] if r['plv1h'] is None else round(r['plv1h'],2)}")
