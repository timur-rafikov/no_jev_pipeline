"""Regex/rule filter for traces whose failure (or success) is visible in the text.

No model calls, no cost. Works on the normalized records (`messages` with roles user / assistant /
tool, as in selected_records.jsonl and traces_*.jsonl). A trace is split into turns (a user
message and everything up to the next user message). A turn FAILS visibly if its final assistant
message
  - is a call list that no tool result follows (calls announced, nothing executed),
  - is empty or `[]`,
  - repeats the same call 4+ times (degenerate loop), or
  - admits inability ("cannot", "not found", "does not exist", ...) AND a tool error appeared in
    the turn.
A turn CONTRADICTS if a tool error appeared but the final message claims success without any
admission. Rules (validated on 83 hand-read BFCL failures, see README of this folder):
  loud failure    : >= 1 failed turn
  strict (high P) : >= 2 failed turns
  clean success   : 0 failed turns, 0 contradicting turns, 0 tool errors in the trace

  python visible_filter.py --input traces.jsonl [--min-failed 1] [--show]
"""
import argparse
import collections
import json
import re

ADMIT = re.compile(r"\b(cannot|can't|could not|couldn't|unable to|not found|does not exist|doesn't exist|no such|"
                   r"failed|not possible|no (?:valid )?(?:booking|order|file|ticket)|"
                   r"please (?:provide|specify|confirm|verify|check)|invalid|already (?:exists|closed|resolved))\b", re.I)
SUCCESS = re.compile(r"\b(successfully|has been (?:created|placed|posted|sent|booked|cancel+ed|resolved|added|set|"
                     r"filled|started)|is now)\b", re.I)
ERROR = re.compile(r'"error"|^Error during execution|Error:', re.I)
CALL = re.compile(r'\b[a-zA-Z_]\w*\(')


def text(msg):
    c = msg.get('content')
    return (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)) or ''


def split_turns(messages):
    turns, cur = [], None
    for m in messages:
        if m['role'] in ('system', 'developer'):
            continue
        if m['role'] == 'user':
            cur = [m]
            turns.append(cur)
        elif cur is not None:
            cur.append(m)
    return turns


def turn_features(turn):
    asst = [m for m in turn if m['role'] == 'assistant']
    tools = [text(m) for m in turn if m['role'] == 'tool']
    final = text(asst[-1]).strip() if asst else ''
    calls = collections.Counter(re.findall(r'\w+\([^)]*\)', final))
    errors = sum(bool(ERROR.search(t)) for t in tools)
    admit = bool(ADMIT.search(final)) and not final.startswith('[')
    return {
        'unexecuted': bool(CALL.search(final)) and not tools and (final.startswith('[') or final.endswith(']')),
        'empty': final in ('', '[]'),
        'loop': max(calls.values(), default=0) >= 4,
        'admits': admit, 'errors': errors,
        'claims_success': bool(SUCCESS.search(final)) and not ADMIT.search(final),
    }


def failed(f):
    return f['unexecuted'] or f['empty'] or f['loop'] or (f['admits'] and f['errors'] > 0)


def contradicts(f):
    return f['errors'] > 0 and f['claims_success']


def classify(messages):
    feats = [turn_features(t) for t in split_turns(messages)]
    n_failed = sum(failed(f) for f in feats)
    n_contra = sum(contradicts(f) for f in feats)
    n_err = sum(f['errors'] for f in feats)
    return {'turns': len(feats), 'failed_turns': n_failed, 'contradicting_turns': n_contra, 'tool_errors': n_err,
            'loud_failure': n_failed >= 1, 'strict_failure': n_failed >= 2,
            'clean_success': n_failed == 0 and n_contra == 0 and n_err == 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True)
    ap.add_argument('--min-failed', type=int, default=1)
    ap.add_argument('--show', action='store_true', help='print one line per trace')
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.input) if l.strip()]
    stats = collections.Counter()
    for r in rows:
        c = classify(r['messages'])
        gold = r.get('source_gold') or r.get('visible_class') or '?'
        stats[(gold, 'loud' if c['failed_turns'] >= a.min_failed else 'clean' if c['clean_success'] else 'other')] += 1
        if a.show:
            print(r.get('case_id') or r['id'], gold, c)
    print(dict(stats))


if __name__ == '__main__':
    main()
