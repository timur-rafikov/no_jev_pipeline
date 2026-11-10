"""Figures + causal summary for the claim pilot. python make_figures.py"""
import json, collections
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

O = 'out'
B = json.load(open(f'{O}/behav_summary.json'))
M = json.load(open(f'{O}/mech_last.json')); MC = json.load(open(f'{O}/mech_claimpos.json'))
fig, ax = plt.subplots(1, 3, figsize=(16, 4.2))

# 1 behaviour: delta log-odds vs no-claim, by truth x claim, per source (inline)
cells = [c for c in B['cells'] if c['rendering'] == 'inline']
labels, vals, errs, cols = [], [], [], []
for truth in ('success', 'failure'):
    for claim in ('success', 'failure'):
        for src in ('agent', 'user', 'tool'):
            c = next(x for x in cells if x['truth'] == truth and x['claim'] == claim and x['source'] == src)
            labels.append(f'{truth[:4]} trace\n{claim[:4]} claim\n{src}'); vals.append(c['delta_logit_mean'])
            errs.append([c['delta_logit_mean'] - c['ci'][0], c['ci'][1] - c['delta_logit_mean']])
            cols.append('#4c72b0' if truth == claim else '#c44e52')
ax[0].bar(range(len(vals)), vals, yerr=np.array(errs).T, color=cols, capsize=2)
ax[0].set_xticks(range(len(vals))); ax[0].set_xticklabels(labels, fontsize=5.5)
ax[0].axhline(0, c='k', lw=.6); ax[0].set_ylabel('Δ log-odds(Yes) vs no claim')
ax[0].set_title('Behaviour (blue = claim agrees with trace, red = contradicts)', fontsize=9)

# 2 probes by layer
L = [r['layer'] for r in M['layers']]
for key, lab in (('truth_acc', 'truth (all rows)'), ('truth_acc_contradicting', 'truth (contradicting rows only)'),
                 ('claim_acc', 'claim content'), ('decision_acc', "judge's decision")):
    ax[1].plot(L, [r[key] for r in M['layers']], label=lab)
ax[1].plot([r['layer'] for r in MC['layers']], [r['truth_acc_contradicting'] for r in MC['layers']], '--', c='C1',
           label='truth (contradicting), claim-end token')
ax[1].axhline(.5, c='gray', lw=.6); ax[1].set_xlabel('layer'); ax[1].set_ylabel('grouped-CV accuracy')
ax[1].set_title('Linear probes, last token (dashed: claim-end token)', fontsize=9); ax[1].legend(fontsize=6)

# 3 causal
try:
    Cz = json.load(open(f'{O}/causal.json'))
    P = collections.defaultdict(list)
    for r in Cz['patch']:
        P[(r['source'], r['layer'])].append((r['patched'] - r['base'], r['donor'] - r['base']))
    for s in ('agent', 'user', 'tool'):
        ls = sorted({k[1] for k in P if k[0] == s})
        ax[2].plot(ls, [sum(a for a, _ in P[(s, l)]) / sum(b for _, b in P[(s, l)]) for l in ls], marker='o', ms=3,
                   label=f'patch recovery, {s} claim')
    St = collections.defaultdict(list)
    for r in Cz['steer']:
        St[(r['dir'], r['t'], r['layer'])].append(r['steered'] - r['base'])
    ax[2].set_xlabel('layer'); ax[2].set_ylabel('fraction of donor-vs-recipient gap recovered')
    ax[2].set_title('Last-token patching (contradicting claim -> no-claim run)', fontsize=9); ax[2].legend(fontsize=6)
except FileNotFoundError:
    ax[2].set_title('causal results missing')
plt.tight_layout(); plt.savefig(f'{O}/claims_pilot.png', dpi=150)
print('saved')
