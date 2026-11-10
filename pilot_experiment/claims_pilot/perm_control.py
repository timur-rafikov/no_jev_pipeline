"""Label-permutation control for the truth probe: shuffle the outcome label across TRACES (all
conditions of a trace keep the same shuffled label) and re-run the grouped-CV probe."""
import json, sys
import numpy as np
from mech_analyze import probe

data = sys.argv[1]
meta = json.load(open(f'{data}/states_meta.json'))
ids = sorted({m['case_id'] for m in meta})
truth = {c: next(m['truth'] == 'success' for m in meta if m['case_id'] == c) for c in ids}
grp = np.array([m['case_id'] for m in meta])
rng = np.random.default_rng(0)
out = {}
for pos in ('last', 'claim'):
    S = np.load(f'{data}/states.npz')[pos].astype(np.float32)
    for l in (20, 32):
        accs = []
        for _ in range(10):
            perm = dict(zip(ids, rng.permutation([truth[c] for c in ids])))
            y = np.array([int(perm[c]) for c in grp])
            accs.append(float(((probe(S[:, l], y, grp) > 0) == y).mean()))
        out[f'{pos}_L{l}'] = {'mean': float(np.mean(accs)), 'max': float(np.max(accs)), 'all': accs}
        print(pos, l, round(np.mean(accs), 3), round(np.max(accs), 3), flush=True)
json.dump(out, open(f'{data}/perm_control.json', 'w'), indent=1)
