"""Linear probes and difference-of-means directions on the stored residual stream.

Separates three things at the last prompt token (the position that predicts Yes/No):
  truth     - the visible outcome of the trace (success / failure)
  claim     - what the inserted claim says
  decision  - what the judge will answer (sign of the Yes-No log-odds)
Because truth and claim are crossed (every trace gets both claim contents), the probes are
identifiable separately. All CV is grouped by trace (no trace appears in train and test).

  python mech_analyze.py --data out --out out/mech.json
"""
import argparse, json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def probe(X, y, groups, C=0.01, folds=5):
    """grouped-CV decision function (positive class = 1)."""
    out = np.zeros(len(y))
    for tr, te in GroupKFold(folds).split(X, y, groups):
        m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(X[tr], y[tr])
        out[te] = m.decision_function(X[te])
    return out


def transfer(X, y, src, train_srcs, test_src, C=0.01):
    tr = np.isin(src, train_srcs); te = src == test_src
    m = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=2000)).fit(X[tr], y[tr])
    return float((m.predict(X[te]) == y[te]).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--position', default='last', choices=['last', 'claim'])
    ap.add_argument('--step', type=int, default=2)
    a = ap.parse_args()
    S = np.load(f'{a.data}/states.npz')[a.position].astype(np.float32)        # (N, L+1, D)
    meta = json.load(open(f'{a.data}/states_meta.json'))
    N, L1, _ = S.shape
    truth = np.array([m['truth'] == 'success' for m in meta]).astype(int)
    content = np.array([-1 if m['content'] is None else int(m['content'] == 'success') for m in meta])
    cons = np.array([m['consistency'] for m in meta])
    src = np.array([m['source'] or 'none' for m in meta])
    ld = np.array([m['logit_diff'] for m in meta])
    dec = (ld > 0).astype(int)
    grp = np.array([m['case_id'] for m in meta])
    has_claim = content >= 0
    res = {'layers': [], 'n': int(N), 'position': a.position,
           'judge_accepts': {k: float(dec[cons == k].mean()) for k in ('none', 'consistent', 'contradicting')}}
    for l in range(0, L1, a.step):
        X = S[:, l]
        row = {'layer': l}
        s_truth = probe(X, truth, grp)
        row['truth_acc'] = float(((s_truth > 0) == truth).mean())
        for k in ('none', 'consistent', 'contradicting'):
            row[f'truth_acc_{k}'] = float(((s_truth[cons == k] > 0) == truth[cons == k]).mean())
        Xc, yc, gc = X[has_claim], content[has_claim], grp[has_claim]
        s_claim = probe(Xc, yc, gc)
        row['claim_acc'] = float(((s_claim > 0) == yc).mean())
        for s in ('agent', 'user', 'tool'):          # leave-one-source-out: shared claim code?
            others = [t for t in ('agent', 'user', 'tool') if t != s]
            row[f'claim_transfer_to_{s}'] = transfer(Xc, yc, src[has_claim], others, s)
        s_dec = probe(X, dec, grp) if 0 < dec.sum() < N else np.zeros(N)
        row['decision_acc'] = float(((s_dec > 0) == dec).mean()) if 0 < dec.sum() < N else None
        # among contradicting rows: which probe does the judge's decision follow?
        k = cons == 'contradicting'
        full = np.zeros(N); full[has_claim] = s_claim
        row['contra_truth_probe_says_truth'] = float(((s_truth[k] > 0) == truth[k]).mean())
        row['contra_claim_probe_says_claim'] = float(((full[k] > 0) == content[k]).mean())
        row['contra_judge_follows_claim'] = float((dec[k] == content[k]).mean())
        row['contra_judge_follows_truth'] = float((dec[k] == truth[k]).mean())
        # difference-of-means directions
        dT = X[truth == 1].mean(0) - X[truth == 0].mean(0)
        dC = Xc[yc == 1].mean(0) - Xc[yc == 0].mean(0)
        row['cos_truth_claim'] = float(dT @ dC / (np.linalg.norm(dT) * np.linalg.norm(dC) + 1e-9))
        row['norm_truth_dir'] = float(np.linalg.norm(dT)); row['norm_claim_dir'] = float(np.linalg.norm(dC))
        pT, pC = X @ dT / np.linalg.norm(dT), X @ dC / np.linalg.norm(dC)
        row['corr_logit_truthproj'] = float(np.corrcoef(pT, ld)[0, 1])
        row['corr_logit_claimproj'] = float(np.corrcoef(pC[has_claim], ld[has_claim])[0, 1])
        res['layers'].append(row)
        print(l, {k: round(v, 3) for k, v in row.items() if isinstance(v, float) and k.endswith(('acc', 'truth', 'claim'))}, flush=True)
    json.dump(res, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
