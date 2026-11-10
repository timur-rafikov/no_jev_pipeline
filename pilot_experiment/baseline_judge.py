"""Baseline judge run: full trace, no inserted claim, single forward pass, Yes/No logits.

Measures how well a small judge reads the ORIGINAL outcome of each pilot trace before any
claim is inserted. Labels are BFCL grades (not verified visible outcomes), so read the numbers
as agreement with BFCL, not accuracy against truth.

  python3 baseline_judge.py render                 # no model; prompt text + length estimate
  python3 baseline_judge.py tokens --model ID      # needs tokenizer only (small download)
  python3 baseline_judge.py run --model ID         # needs weights; resumable; writes results
  python3 baseline_judge.py summarize --results F  # metrics from a results file

No API calls and no paid compute: `run` executes locally with torch.
"""
import argparse
import json
import math
import statistics
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUESTION = ('Above is a recorded conversation between a user and an AI agent that can call tools. '
            'Did the agent successfully complete everything the user asked for, as shown by the '
            'tool results? Answer with exactly one word: Yes or No.')


LABELS = {'user': 'USER', 'assistant': 'AGENT', 'tool': 'TOOL RESULT'}


def render_trace(messages, mode='full'):
    """full: every message verbatim. nosys: drop system/developer (tool specs). compact: nosys plus
    plain role labels and '(no output)' for empty tool results. Dialogue text is never edited."""
    parts = []
    for m in messages:
        if mode != 'full' and m['role'] in ('system', 'developer'):
            continue
        content = m.get('content')
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if mode == 'compact':
            if m['role'] == 'tool' and content.strip() in ('None', ''):
                content = '(no output)'
            parts.append(f"{LABELS.get(m['role'], m['role'].upper())}: {content}")
        else:
            parts.append(f"[{m['role']} {m['id']}]\n{content}")
    return '\n\n'.join(parts)


def build_prompt(messages, mode='full'):
    return render_trace(messages, mode) + '\n\n' + QUESTION


def load_traces(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def chat_inputs(tokenizer, text, thinking=False):
    chat = [{'role': 'user', 'content': text}]
    kwargs = dict(tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors='pt')
    try:  # reasoning switch where the template supports it
        return tokenizer.apply_chat_template(chat, enable_thinking=thinking, **kwargs)
    except TypeError:
        return tokenizer.apply_chat_template(chat, **kwargs)


def answer_token_ids(tokenizer):
    ids = {}
    for label, variants in (('yes', ['Yes', ' Yes', 'yes']), ('no', ['No', ' No', 'no'])):
        found = set()
        for v in variants:
            toks = tokenizer.encode(v, add_special_tokens=False)
            if len(toks) == 1:
                found.add(toks[0])
        if not found:
            raise ValueError('no_single_token_for_' + label)
        ids[label] = sorted(found)
    return ids


def cmd_render(args):
    rows = load_traces(args.traces)
    sizes = []
    for r in rows:
        text = build_prompt(r['messages'])
        sizes.append(len(text))
    print(json.dumps({'traces': len(rows), 'chars_min': min(sizes), 'chars_median': int(statistics.median(sizes)),
                      'chars_max': max(sizes),
                      'rough_tokens_median_at_3.5_chars': int(statistics.median(sizes) / 3.5),
                      'rough_tokens_max_at_3.0_chars': int(max(sizes) / 3.0)}, indent=2))
    print('\n--- prompt tail of first trace ---\n' + build_prompt(rows[0]['messages'])[-700:])


def cmd_tokens(args):
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model)
    rows = load_traces(args.traces)
    out = []
    for r in rows:
        n = int(chat_inputs(tok, build_prompt(r['messages']))['input_ids'].shape[-1])
        out.append({'case_id': r['case_id'], 'label': r['source_gold'], 'n_tokens': n})
    (HERE / 'token_counts.json').write_text(json.dumps(out, indent=1))
    ns = [o['n_tokens'] for o in out]
    print(json.dumps({'min': min(ns), 'median': int(statistics.median(ns)), 'max': max(ns),
                      'total': sum(ns), 'answer_token_ids': answer_token_ids(tok)}, indent=2))


def cmd_run(args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device = args.device or ('cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu')
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.bfloat16).to(device).eval()
    ids = answer_token_ids(tok)
    out_path = Path(args.results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)['case_id'] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    rows = load_traces(args.traces)[:args.limit]
    with out_path.open('a') as f:
        for r in rows:
            if r['case_id'] in done:
                continue
            enc = chat_inputs(tok, build_prompt(r['messages'], args.simplify))
            n = int(enc['input_ids'].shape[-1])
            if n > args.max_tokens:
                row = {'case_id': r['case_id'], 'label': r['source_gold'], 'n_tokens': n, 'skipped': 'too_long'}
            else:
                t0 = time.time()
                with torch.inference_mode():
                    logits = model(**{k: v.to(device) for k, v in enc.items()}, logits_to_keep=1).logits[0, -1].float()
                lp = torch.log_softmax(logits, -1)
                lyes = torch.logsumexp(lp[ids['yes']], 0).item()
                lno = torch.logsumexp(lp[ids['no']], 0).item()
                row = {'case_id': r['case_id'], 'label': r['source_gold'], 'n_tokens': n,
                       'logp_yes': lyes, 'logp_no': lno, 'p_yes_norm': 1 / (1 + math.exp(lno - lyes)),
                       'mass_yes_no': math.exp(lyes) + math.exp(lno), 'seconds': round(time.time() - t0, 1)}
            f.write(json.dumps(row) + '\n'); f.flush()
            print(json.dumps(row), flush=True)


def cmd_think(args):
    """Reasoning run: sample a chain of thought, then read Yes/No logits right after </think>.

    Thinking is cut at </think> (or at the token budget) and closed by hand, so the probability
    is comparable to the no-reasoning runs. Sampling: temp 0.6, top_p 0.95, top_k 20, fixed seed.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    device = args.device or ('cuda' if torch.cuda.is_available() else 'cpu')
    tok = AutoTokenizer.from_pretrained(args.model)
    tok.padding_side = 'left'
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.bfloat16).to(device).eval()
    ids = answer_token_ids(tok)
    out_path = Path(args.results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)['case_id'] for l in out_path.read_text().splitlines()} if out_path.exists() else set()
    todo = [r for r in load_traces(args.traces)[:args.limit] if r['case_id'] not in done]
    prompts = []
    for r in todo:
        enc = chat_inputs(tok, build_prompt(r['messages'], args.simplify), thinking=True)
        prompts.append((r, tok.decode(enc['input_ids'][0], skip_special_tokens=False), int(enc['input_ids'].shape[-1])))
    prompts.sort(key=lambda x: x[2])
    torch.manual_seed(args.seed)
    with out_path.open('a') as f:
        for i in range(0, len(prompts), args.batch):
            chunk = prompts[i:i + args.batch]
            t0 = time.time()
            batch = tok([p[1] for p in chunk], return_tensors='pt', padding=True, add_special_tokens=False).to(device)
            with torch.inference_mode():
                gen = model.generate(**batch, max_new_tokens=args.max_new, do_sample=True, temperature=0.6,
                                     top_p=0.95, top_k=20, pad_token_id=tok.pad_token_id)
            new = gen[:, batch['input_ids'].shape[1]:]
            for (r, prompt, n), row_ids in zip(chunk, new):
                text = tok.decode(row_ids, skip_special_tokens=True)
                think_tokens = int((row_ids != tok.pad_token_id).sum())
                finished = '</think>' in text
                thinking = text.split('</think>')[0].rstrip()
                answer = text.split('</think>', 1)[1].strip() if finished else ''
                forced = prompt + thinking + '\n</think>\n\n'
                enc = tok(forced, return_tensors='pt', add_special_tokens=False).to(device)
                with torch.inference_mode():
                    logits = model(**enc, logits_to_keep=1).logits[0, -1].float()
                lp = torch.log_softmax(logits, -1)
                lyes = torch.logsumexp(lp[ids['yes']], 0).item()
                lno = torch.logsumexp(lp[ids['no']], 0).item()
                row = {'case_id': r['case_id'], 'label': r['source_gold'], 'n_tokens': n,
                       'think_tokens': think_tokens, 'finished_thinking': finished, 'own_answer': answer[:40],
                       'logp_yes': lyes, 'logp_no': lno, 'p_yes_norm': 1 / (1 + math.exp(lno - lyes)),
                       'mass_yes_no': math.exp(lyes) + math.exp(lno), 'thinking': thinking}
                f.write(json.dumps(row, ensure_ascii=False) + '\n'); f.flush()
            print(f'batch {i // args.batch + 1}: {len(chunk)} traces in {time.time() - t0:.0f}s', flush=True)


def auroc(pos, neg):
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def summarize(rows):
    ok = [r for r in rows if 'p_yes_norm' in r]
    pos = [r['p_yes_norm'] for r in ok if r['label'] == 'success']
    neg = [r['p_yes_norm'] for r in ok if r['label'] == 'failure']
    pred = lambda r: 'success' if r['p_yes_norm'] >= 0.5 else 'failure'
    tpr = sum(pred(r) == 'success' for r in ok if r['label'] == 'success') / max(1, len(pos))
    tnr = sum(pred(r) == 'failure' for r in ok if r['label'] == 'failure') / max(1, len(neg))
    ns = sorted(r['n_tokens'] for r in ok)
    lo = ns[len(ns) // 2] if ns else 0
    by_len = {}
    for name, sel in (('shorter_half', [r for r in ok if r['n_tokens'] < lo]),
                      ('longer_half', [r for r in ok if r['n_tokens'] >= lo])):
        p = [r['p_yes_norm'] for r in sel if r['label'] == 'success']
        n = [r['p_yes_norm'] for r in sel if r['label'] == 'failure']
        by_len[name] = {'n': len(sel), 'auroc': auroc(p, n)}
    return {'scored': len(ok), 'skipped': len(rows) - len(ok), 'auroc_vs_bfcl': auroc(pos, neg),
            'acc_success': tpr, 'acc_failure': tnr, 'balanced_acc': (tpr + tnr) / 2,
            'yes_rate': sum(pred(r) == 'success' for r in ok) / max(1, len(ok)),
            'mean_p_yes': {'success': statistics.mean(pos) if pos else None,
                           'failure': statistics.mean(neg) if neg else None},
            'median_yes_no_mass': statistics.median(r['mass_yes_no'] for r in ok) if ok else None,
            'by_length': by_len}


def cmd_summarize(args):
    rows = [json.loads(l) for l in Path(args.results).read_text().splitlines() if l.strip()]
    print(json.dumps(summarize(rows), indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('render', 'tokens', 'run', 'think', 'summarize'):
        s = sub.add_parser(name)
        s.add_argument('--traces', default=str(HERE / 'traces_50.jsonl'))
        s.add_argument('--results', default=str(HERE / 'baseline_results.jsonl'))
        if name in ('tokens', 'run', 'think'):
            s.add_argument('--model', required=True)
        if name in ('run', 'think'):
            s.add_argument('--device'); s.add_argument('--limit', type=int)
            s.add_argument('--simplify', choices=['full', 'nosys', 'compact'], default='full')
        if name == 'run':
            s.add_argument('--max-tokens', type=int, default=24000)
        if name == 'think':
            s.add_argument('--batch', type=int, default=6); s.add_argument('--max-new', type=int, default=3000)
            s.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    {'render': cmd_render, 'tokens': cmd_tokens, 'run': cmd_run, 'think': cmd_think, 'summarize': cmd_summarize}[args.cmd](args)


if __name__ == '__main__':
    main()
