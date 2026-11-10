"""Class-balanced `prepare` for v6 batches.

assemble_v6.prepare takes executions in sha256(seed|id) order, so the batch inherits the
pool's class mix (about 77% BFCL failures). This module builds a batch with equal numbers of
`source_gold` success and failure executions, interleaved so that any prefix (`run --limit`,
`--target-families`) stays balanced. assemble_v6.py is deliberately not edited: its hash is part
of every frozen manifest. Batches written here load, run, export and verify with the existing
commands.

`source_gold` is the BFCL grade (simulator state vs ground truth), not an outcome checked to be
visible in the trace text. Balancing on it fixes the class mix only; it does not make the label
reliable.
"""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import assemble_v6 as a
import pipeline_v6 as p
from client import save

CLASSES = ('success', 'failure')


def balanced_select(eligible, count, seed, unique_tasks=True):
    """Interleave classes in hash order; count/2 per class, each prefix balanced."""
    if count <= 0 or count % len(CLASSES):
        raise ValueError('balanced_count_must_be_positive_and_even')
    quota = count // len(CLASSES)
    queues = {c: sorted((r for r in eligible if r['source_gold'] == c),
                        key=lambda r: p.digest([seed, r['id']])) for c in CLASSES}
    cursor = dict.fromkeys(CLASSES, 0)
    picked = {c: [] for c in CLASSES}
    seen = set()
    order = []
    while any(len(picked[c]) < quota for c in CLASSES):
        progressed = False
        for c in CLASSES:
            if len(picked[c]) >= quota:
                continue
            queue = queues[c]
            while cursor[c] < len(queue):
                r = queue[cursor[c]]
                cursor[c] += 1
                if unique_tasks and r['task_id'] in seen:
                    continue
                seen.add(r['task_id'])
                picked[c].append(r)
                order.append(r)
                progressed = True
                break
        if not progressed:
            short = {c: len(picked[c]) for c in CLASSES if len(picked[c]) < quota}
            raise ValueError('insufficient_class_records_' + json.dumps(short, sort_keys=True))
    return order


def availability(eligible, unique_tasks=True):
    by_class = {c: [r for r in eligible if r['source_gold'] == c] for c in CLASSES}
    return {'executions': {c: len(v) for c, v in by_class.items()},
            'tasks': {c: len({r['task_id'] for r in v}) for c, v in by_class.items()},
            'max_balanced_count': 2 * min(len({r['task_id'] for r in v}) if unique_tasks else len(v)
                                          for v in by_class.values())}


def prepare_balanced(name, count, seed, max_bytes=0, unique_tasks=True, exclude_history=True,
                     input_path=None, dry_run=False):
    batch = a.batch_path(name)
    if batch.exists():
        raise ValueError('batch_already_exists')
    if count < 0 or max_bytes < 0:
        raise ValueError('negative_selection_limit')
    records = a.legacy.read_jsonl(input_path) if input_path else a.legacy.source_pool()
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate_source_id')
    if any(r.get('source_gold') not in CLASSES for r in records):
        raise ValueError('source_gold_missing_cannot_balance')
    excluded = a.executed_tasks() if exclude_history else set()
    eligible, reasons = [], Counter()
    for r in records:
        try:
            p.source_check(r)
        except ValueError as e:
            reasons['structural_' + str(e)] += 1
            continue
        if r['task_id'] in excluded:
            reasons['already_used_task'] += 1
            continue
        if max_bytes and len(p.canonical(r['messages']).encode()) > max_bytes:
            reasons['declared_length_scope'] += 1
            continue
        eligible.append(r)
    stats = availability(eligible, unique_tasks)
    if dry_run:
        return {'dry_run': True, 'eligible_executions': len(eligible),
                'scope_exclusions': dict(reasons), **stats}
    chosen = balanced_select(eligible, count, seed, unique_tasks)
    selected = [{**r, 'case_id': f'{name}_{i + 1:04d}', 'cohort': name} for i, r in enumerate(chosen)]
    batch.mkdir(parents=True)
    a.legacy.write_jsonl(batch / 'selected_records.jsonl', selected)
    source = {'input_sha256': a.file_hash(input_path)} if input_path else {
        'dataset': 'HuanzhiMao/BFCL-Result', 'release': '2025-11-03',
        'commit': json.loads((a.ROOT / 'source_commit.json').read_text())['sha'],
        'raw_files': {path.name: a.file_hash(path) for path in sorted((a.ROOT / 'raw').glob('*.jsonl'))}}
    manifest = {'protocol': p.protocol_state(), 'runtime_hashes': a.runtime_hashes(), 'source': source,
        'seed': seed, 'selection_order': 'class-interleaved; within class sha256(canonical([seed,source_id]))',
        'max_message_bytes': max_bytes, 'unique_tasks': unique_tasks,
        'excluded_task_ids': sorted(excluded), 'scope_exclusions': dict(reasons),
        'eligible_executions': len(eligible), 'source_executions': len(records),
        'source_tasks': len({r['task_id'] for r in records}), 'semantic_preselection': False,
        'gold_used_for_selection': True,
        'class_balance': {'by': 'source_gold (BFCL grade, not verified visible outcome)',
                          'target': {c: count // len(CLASSES) for c in CLASSES},
                          'selected': dict(Counter(r['source_gold'] for r in selected)),
                          'available': stats},
        'split_seed': a.legacy.SPLIT_SEED,
        'selected': [{'case_id': r['case_id'], 'source_id': r['id'], 'task_id': r['task_id'],
                      'record_hash': p.digest(r)} for r in selected],
        'novelty_limit': 'Available executed history and documented prior IDs; earlier missing archives cannot be checked.'}
    save(batch / 'manifest.json', manifest)
    save(batch / 'start_accounting.json', a.Client(a.ROOT).accounting())
    return {'selected': len(selected), 'class_counts': manifest['class_balance']['selected'],
            'eligible_executions': len(eligible), 'scope_exclusions': dict(reasons), **stats}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--count', type=int, required=True, help='total, even; half per class')
    parser.add_argument('--seed', required=True)
    parser.add_argument('--max-bytes', type=int, default=0)
    parser.add_argument('--allow-seen', action='store_true')
    parser.add_argument('--allow-same-task', action='store_true')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='report class availability, write nothing')
    args = parser.parse_args()
    with (a.ROOT / '.run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = prepare_balanced(args.batch, args.count, args.seed, args.max_bytes,
                                  not args.allow_same_task, not args.allow_seen, args.input, args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
