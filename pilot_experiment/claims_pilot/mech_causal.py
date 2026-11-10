"""Interventions on the last-token residual stream (the position that outputs Yes/No).

1. Patching: take the last-token state of layer L from a run WITH a contradicting claim (donor)
   and write it into the run WITHOUT a claim (recipient, same trace). Recovery(L) = shift of the
   recipient's Yes-No log-odds as a fraction of the donor-vs-recipient gap. Where recovery
   becomes ~1 the claim's effect has already been collected at the last position; before that
   it still lives at the claim tokens.
2. Steering: add t * d to the last-token state at layer L of the no-claim run, d = difference of
   means for the claim content (claim-success minus claim-failure) or for the true outcome.
   Which direction moves the output, and by how much, separates "claim code" from "fact code".

  python mech_causal.py --model Qwen/Qwen3-14B --traces traces_46.jsonl --data out --out out/causal.json
"""
import argparse, json
import numpy as np
import torch
import claims_lib as C


def layer_module(model, L):
    return model.model.layers[L]


def run_with(model, enc, ids, L, fn):
    """forward with fn(h_last) -> new h_last applied to the output of layer L at the last position."""
    def hook(mod, inp, out):
        h = out[0] if isinstance(out, tuple) else out
        h = h.clone()
        h[:, -1, :] = fn(h[:, -1, :]).to(h.dtype)
        return (h,) + tuple(out[1:]) if isinstance(out, tuple) else h
    handle = layer_module(model, L).register_forward_hook(hook)
    try:
        return C.logit_diff(model, enc, ids)
    finally:
        handle.remove()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True); ap.add_argument('--traces', required=True)
    ap.add_argument('--data', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--layers', default='0,4,8,12,16,20,24,28,32,36,39')
    a = ap.parse_args()
    layers = [int(x) for x in a.layers.split(',')]
    tok, model = C.load_model(a.model)
    ids = C.answer_ids(tok)
    traces = {r['case_id']: r for r in C.load_traces(a.traces)}
    S = np.load(f'{a.data}/states.npz')['last'].astype(np.float32)
    meta = json.load(open(f'{a.data}/states_meta.json'))
    index = {(m['case_id'], m['cond']): i for i, m in enumerate(meta)}
    truth = np.array([m['truth'] == 'success' for m in meta])
    content = np.array([-1 if m['content'] is None else int(m['content'] == 'success') for m in meta])
    dirs = {}
    for L in layers:
        X = S[:, L + 1]
        dirs[L] = {'claim': X[content == 1].mean(0) - X[content == 0].mean(0),
                   'truth': X[truth].mean(0) - X[~truth].mean(0)}
    res = {'patch': [], 'steer': []}
    for cid, r in traces.items():
        body, prompt = C.build(r['messages'])
        enc, _ = C.tokenize(tok, prompt, body)
        base = meta[index[(cid, 'none')]]['logit_diff']
        opposite = 'failure' if r['visible_class'] == 'success' else 'success'
        for s in C.SOURCES:
            j = index[(cid, f'{s}_{opposite}')]
            donor_ld = meta[j]['logit_diff']
            for L in layers:
                v = torch.from_numpy(S[j, L + 1]).cuda()
                ld = run_with(model, enc, ids, L, lambda h, v=v: v[None])
                res['patch'].append({'case_id': cid, 'truth': r['visible_class'], 'source': s, 'layer': L,
                                     'base': base, 'donor': donor_ld, 'patched': ld})
        for L in layers:
            for name, d in dirs[L].items():
                dv = torch.from_numpy(d).cuda()
                for t in (-1.0, 1.0):
                    ld = run_with(model, enc, ids, L, lambda h, dv=dv, t=t: h + t * dv[None])
                    res['steer'].append({'case_id': cid, 'truth': r['visible_class'], 'dir': name, 't': t,
                                         'layer': L, 'base': base, 'steered': ld})
        print(cid, flush=True)
    json.dump(res, open(a.out, 'w'))


if __name__ == '__main__':
    main()
