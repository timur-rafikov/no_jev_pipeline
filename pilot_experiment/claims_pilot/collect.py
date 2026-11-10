"""Behaviour + activations. For every trace x condition: log-odds of Yes vs No.
Residual-stream states (all layers) at the last token and at the claim-end token are stored for
the inline rendering (and 'none'), for the probe / SAE / intervention scripts.

  python collect.py --model Qwen/Qwen3-14B --traces ../visible_pilot/traces_46.jsonl --out out
"""
import argparse, json, time
from pathlib import Path
import numpy as np
import claims_lib as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True); ap.add_argument('--traces', required=True)
    ap.add_argument('--out', required=True); ap.add_argument('--limit', type=int)
    a = ap.parse_args()
    import torch
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tok, model = C.load_model(a.model)
    ids = C.answer_ids(tok)
    rows = C.load_traces(a.traces)[:a.limit]
    last, claim, meta, t0 = [], [], [], time.time()
    with (out / 'behav.jsonl').open('w') as f:
        for r in rows:
            truth = r['visible_class']
            for c in C.conditions():
                body, prompt = C.build(r['messages'], c['source'], c['content'], c['rendering'])
                enc, pos = C.tokenize(tok, prompt, body)
                keep = c['rendering'] == 'inline'
                res = C.logit_diff(model, enc, ids, want_states=keep)
                ld, hs = res if keep else (res, None)
                row = {'case_id': r['case_id'], 'task_id': r['task_id'], 'agent_model': r['model'], 'truth': truth,
                       **c, 'consistency': C.consistency(truth, c['content']), 'logit_diff': ld,
                       'n_tokens': int(enc['input_ids'].shape[-1]), 'claim_pos': pos}
                f.write(json.dumps(row) + '\n')
                if keep:
                    H = torch.stack([h[0] for h in hs])            # (L+1, T, D)
                    last.append(H[:, -1].float().cpu().numpy().astype(np.float16))
                    claim.append(H[:, pos].float().cpu().numpy().astype(np.float16))
                    meta.append(row)
            print(r['case_id'], f'{time.time() - t0:.0f}s', flush=True)
    np.savez(out / 'states.npz', last=np.stack(last), claim=np.stack(claim))
    (out / 'states_meta.json').write_text(json.dumps(meta))
    print('done', len(meta), 'state rows')


if __name__ == '__main__':
    main()
