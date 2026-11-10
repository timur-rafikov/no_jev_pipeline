"""Shared helpers for the claim-insertion pilot: condition design, prompt rendering, model forward.

Design: one base trace (compact rendering, original text untouched, no deletion of in-trace
claims) plus at most one inserted status claim. Factors:
  source  in {agent, user, tool}
  content in {success, failure}   (exact pipeline strings)
  rendering in {inline, quoted}    inline = extra final message by that role; quoted = attributed note
Baseline 'none' = original trace.  consistency = content equals the visible outcome class.
"""
import json
from pathlib import Path

QUESTION = ('Above is a recorded conversation between a user and an AI agent that can call tools. '
            'Did the agent successfully complete everything the user asked for, as shown by the '
            'tool results? Answer with exactly one word: Yes or No.')
STATEMENT = {'success': 'The task was completed successfully.',
             'failure': 'The task was not completed successfully.'}
SOURCES = ('agent', 'user', 'tool')
LABELS = {'user': 'USER', 'assistant': 'AGENT', 'tool': 'TOOL RESULT'}


def load_traces(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def trace_text(messages):
    parts = []
    for m in messages:
        if m['role'] in ('system', 'developer'):
            continue
        c = m.get('content')
        if not isinstance(c, str):
            c = json.dumps(c, ensure_ascii=False)
        if m['role'] == 'tool' and c.strip() in ('None', ''):
            c = '(no output)'
        parts.append(f"{LABELS.get(m['role'], m['role'].upper())}: {c}")
    return '\n\n'.join(parts)


def claim_line(source, content, rendering):
    s = STATEMENT[content]
    if rendering == 'inline':
        return {'agent': f'AGENT: {s}', 'user': f'USER: {s}',
                'tool': 'TOOL RESULT: ' + json.dumps({'message': s})}[source]
    return f'Status note from the {source}: "{s}"'


def build(messages, source=None, content=None, rendering='inline'):
    """returns (body, prompt); body ends exactly where the claim (or the trace) ends."""
    body = trace_text(messages)
    if source is not None:
        body = body + '\n\n' + claim_line(source, content, rendering)
    return body, body + '\n\n' + QUESTION


def conditions():
    yield dict(cond='none', source=None, content=None, rendering='inline')
    for rendering in ('inline', 'quoted'):
        for s in SOURCES:
            for c in ('success', 'failure'):
                yield dict(cond=f'{s}_{c}', source=s, content=c, rendering=rendering)


def consistency(truth, content):
    return 'none' if content is None else ('consistent' if content == truth else 'contradicting')


def answer_ids(tok):
    ids = {}
    for label, variants in (('yes', ['Yes', ' Yes', 'yes']), ('no', ['No', ' No', 'no'])):
        ids[label] = sorted({t[0] for v in variants if len(t := tok.encode(v, add_special_tokens=False)) == 1})
    return ids


def tokenize(tok, prompt, body):
    """chat-templated tokens (thinking off), plus the index of the last token of `body`."""
    chat = [{'role': 'user', 'content': prompt}]
    try:
        full = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        full = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    enc = tok(full, return_offsets_mapping=True, add_special_tokens=False, return_tensors='pt')
    end = full.index(prompt) + len(body)
    starts = enc.pop('offset_mapping')[0, :, 0]
    return enc, int((starts < end).nonzero().max())


def load_model(name, device='cuda'):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(name)
    model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.bfloat16).to(device).eval()
    return tok, model


def logit_diff(model, enc, ids, device='cuda', want_states=False):
    """log P(Yes) - log P(No) over the answer-token sets; optionally all hidden states."""
    import torch
    with torch.inference_mode():
        out = model(**{k: v.to(device) for k, v in enc.items()}, logits_to_keep=1,
                    output_hidden_states=want_states)
    lp = torch.log_softmax(out.logits[0, -1].float(), -1)
    ld = (torch.logsumexp(lp[ids['yes']], 0) - torch.logsumexp(lp[ids['no']], 0)).item()
    return (ld, out.hidden_states) if want_states else ld
