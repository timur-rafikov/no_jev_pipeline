"""Pretrained SAEs (adamkarvonen/qwen3-14b-saes, resid_post, 16k width, L0=80) on last-token states.

Feature-level view of the same question: which SAE features separate the claim content, which
separate the true outcome, do they overlap, and do a handful of features carry the decision.
Features are not auto-labelled; all prompts end at the same token so max-activating text is not
available from this pass.

  python sae_analyze.py --data out --out out/sae.json
"""
import argparse, json
import numpy as np
import torch
from huggingface_hub import hf_hub_download

REPO = 'adamkarvonen/qwen3-14b-saes'
FAMILY = 'Qwen3-14B'


def load_sae(layer, trainer=0):
    base = f'saes_Qwen_{FAMILY}_batch_top_k/resid_post_layer_{layer}/trainer_{trainer}'
    sd = torch.load(hf_hub_download(REPO, f'{base}/ae.pt'), map_location='cpu')
    cfg = json.load(open(hf_hub_download(REPO, f'{base}/config.json')))
    return sd, cfg


def encode(sd, x):
    """BatchTopK SAE used as JumpReLU with its stored scalar threshold."""
    pre = (x - sd['b_dec']) @ sd['encoder.weight'].T + sd['encoder.bias']
    thr = sd['threshold'] if 'threshold' in sd else 0.0
    return torch.where(pre > thr, torch.relu(pre), torch.zeros_like(pre))


def auroc_cols(F, y):
    """AUROC of each column of F for binary y, via ranks."""
    r = F.argsort(0).argsort(0).float() + 1
    n1, n0 = int(y.sum()), int((1 - y).sum())
    return ((r[y.bool()].sum(0) - n1 * (n1 + 1) / 2) / (n1 * n0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--layers', default='10,20,30'); ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--family', default='Qwen3-14B', help='e.g. Qwen3-32B; repo is adamkarvonen/<family lower>-saes')
    a = ap.parse_args()
    global REPO, FAMILY
    FAMILY = a.family; REPO = f'adamkarvonen/{a.family.lower()}-saes'
    S = torch.from_numpy(np.load(f'{a.data}/states.npz')['last'].astype(np.float32))
    meta = json.load(open(f'{a.data}/states_meta.json'))
    truth = torch.tensor([m['truth'] == 'success' for m in meta]).float()
    cl = torch.tensor([-1 if m['content'] is None else int(m['content'] == 'success') for m in meta])
    has = cl >= 0
    res = {}
    for layer in map(int, a.layers.split(',')):
        sd, cfg = load_sae(layer)
        print('keys', list(sd.keys()), flush=True)
        # resid_post of layer N = hidden_states[N + 1]
        X = S[:, layer + 1]
        keep = X.norm(dim=-1) < 10 * X.norm(dim=-1).median()      # SAE was trained without huge-norm tokens
        F = encode(sd, X.float())
        recon = (((F @ sd['decoder.weight'].T + sd['b_dec']) - X).pow(2).sum(1) / X.pow(2).sum(1)).mean()
        at = auroc_cols(F, truth); ac = auroc_cols(F[has], cl[has].float())
        dt = (at - 0.5).abs(); dc = (ac - 0.5).abs()
        topT = dt.argsort(descending=True)[:a.top]; topC = dc.argsort(descending=True)[:a.top]
        res[layer] = {
            'rel_recon_error': float(recon), 'mean_active_features': float((F > 0).sum(1).float().mean()),
            'keep_frac': float(keep.float().mean()),
            'top_truth': [{'feat': int(i), 'auroc': float(at[i]), 'mean_success': float(F[truth == 1, i].mean()),
                           'mean_failure': float(F[truth == 0, i].mean())} for i in topT],
            'top_claim': [{'feat': int(i), 'auroc': float(ac[i]), 'mean_claim_success': float(F[has][cl[has] == 1, i].mean()),
                           'mean_claim_failure': float(F[has][cl[has] == 0, i].mean())} for i in topC],
            'overlap_top50_truth_claim': len(set(dt.argsort(descending=True)[:50].tolist()) & set(dc.argsort(descending=True)[:50].tolist())),
            'n_features_auroc_gt_0.8_claim': int((dc > 0.3).sum()), 'n_features_auroc_gt_0.8_truth': int((dt > 0.3).sum()),
        }
        print(layer, {k: v for k, v in res[layer].items() if not isinstance(v, list)}, flush=True)
    json.dump(res, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
