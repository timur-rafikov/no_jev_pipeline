"""Behavioural analysis of the claim-insertion run.

Primary outcome: log-odds of Yes vs No (unsaturated), paired against the same trace without a
claim. Reports claim effect (success-claim minus failure-claim), consistent vs contradicting,
source differences, decision flips, and bootstrap CIs over traces (resampling traces, not rows).

  python analyze_behavior.py --behav out/behav.jsonl --out out/behav_summary.json
"""
import argparse, json, collections
import numpy as np

rng = np.random.default_rng(0)


def boot(vals_by_trace, fn=np.mean, B=4000):
    ids = list(vals_by_trace)
    arr = [np.asarray(vals_by_trace[i]) for i in ids]
    est = fn(np.concatenate(arr))
    bs = [fn(np.concatenate([arr[k] for k in rng.integers(0, len(arr), len(arr))])) for _ in range(B)]
    return float(est), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--behav', required=True); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.behav)]
    by = collections.defaultdict(dict)
    for r in rows:
        by[(r['case_id'])][(r['rendering'] if r['cond'] != 'none' else 'inline', r['cond'])] = r
    out = {'n_traces': len(by)}

    def paired(rendering, source, content, truth=None, agent=None):
        d = {}
        for cid, v in by.items():
            base = v[('inline', 'none')]
            if truth and base['truth'] != truth or agent and base['agent_model'] != agent:
                continue
            row = v[(rendering, f'{source}_{content}')]
            d[cid] = [row['logit_diff'] - base['logit_diff']]
        return d

    def flips(rendering, source, content, truth):
        n = f = 0
        for cid, v in by.items():
            base = v[('inline', 'none')]
            if base['truth'] != truth:
                continue
            row = v[(rendering, f'{source}_{content}')]
            n += 1; f += (row['logit_diff'] > 0) != (base['logit_diff'] > 0)
        return f, n

    out['baseline'] = {t: {'accept_rate': float(np.mean([v[('inline', 'none')]['logit_diff'] > 0 for v in by.values() if v[('inline', 'none')]['truth'] == t])),
                           'median_logit_diff': float(np.median([v[('inline', 'none')]['logit_diff'] for v in by.values() if v[('inline', 'none')]['truth'] == t]))}
                       for t in ('success', 'failure')}
    out['cells'] = []
    for rendering in ('inline', 'quoted'):
        for source in ('agent', 'user', 'tool'):
            for truth in ('success', 'failure'):
                for content in ('success', 'failure'):
                    m, lo, hi = boot(paired(rendering, source, content, truth))
                    fl, n = flips(rendering, source, content, truth)
                    out['cells'].append({'rendering': rendering, 'source': source, 'truth': truth, 'claim': content,
                                         'consistency': 'consistent' if truth == content else 'contradicting',
                                         'delta_logit_mean': m, 'ci': [lo, hi], 'decision_flips': f'{fl}/{n}'})
    # claim effect: (success claim - failure claim) per trace, by source/rendering/truth
    out['claim_effect'] = []
    for rendering in ('inline', 'quoted'):
        for source in ('agent', 'user', 'tool'):
            for truth in ('success', 'failure', 'all'):
                dif = {}
                for cid, v in by.items():
                    if truth != 'all' and v[('inline', 'none')]['truth'] != truth:
                        continue
                    dif[cid] = [v[(rendering, f'{source}_success')]['logit_diff'] - v[(rendering, f'{source}_failure')]['logit_diff']]
                m, lo, hi = boot(dif)
                out['claim_effect'].append({'rendering': rendering, 'source': source, 'truth': truth,
                                            'success_minus_failure_claim': m, 'ci': [lo, hi]})
    # fact sensitivity: success-trace minus failure-trace log-odds with no claim vs with contradicting claims
    s = [v[('inline', 'none')]['logit_diff'] for v in by.values() if v[('inline', 'none')]['truth'] == 'success']
    f = [v[('inline', 'none')]['logit_diff'] for v in by.values() if v[('inline', 'none')]['truth'] == 'failure']
    out['fact_gap_no_claim'] = float(np.mean(s) - np.mean(f))
    out['judge_follows_claim_when_contradicting'] = {}
    for rendering in ('inline', 'quoted'):
        for source in ('agent', 'user', 'tool'):
            n = k = 0
            for v in by.values():
                base = v[('inline', 'none')]
                opp = 'failure' if base['truth'] == 'success' else 'success'
                r = v[(rendering, f'{source}_{opp}')]
                n += 1; k += (r['logit_diff'] > 0) == (opp == 'success')
            out['judge_follows_claim_when_contradicting'][f'{rendering}/{source}'] = f'{k}/{n}'
    json.dump(out, open(a.out, 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ('cells', 'claim_effect')}, indent=1))
    for c in out['claim_effect']:
        print(c['rendering'], c['source'], c['truth'], round(c['success_minus_failure_claim'], 2), [round(x, 2) for x in c['ci']])


if __name__ == '__main__':
    main()
