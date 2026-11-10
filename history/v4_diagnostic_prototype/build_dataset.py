"""Resumable v4 dataset assembly. Dry-run unless `run --run` is explicit.

prepare freezes a deterministic source manifest; run uses the shared historical budget;
export admits only reviewed families and assigns every task to a single stable split.
"""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import re
import client as transport
from client import Client, BudgetError, save
from prepare_data import MODELS, normalize
import pipeline_v4 as p

ROOT = Path(__file__).resolve().parent
SPLIT_SEED = 'bfcl-judge-task-split-v1'


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write_jsonl(path, rows):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(''.join(p.canonical(row) + '\n' for row in rows))
    tmp.replace(path)


def batch_path(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
        raise ValueError('batch_name_must_be_a_simple_identifier')
    return ROOT / 'batches' / name


def historical_tasks():
    ids = {'multi_turn_base_' + str(n) for n in [27,41,46,82,122,163,158,194,179,197,99,15]}
    paths = [ROOT / 'selected_records.jsonl'] + list((ROOT / 'batches').glob('*/selected_records.jsonl'))
    for path in paths:
        if path.exists():
            ids.update(r['task_id'] for r in read_jsonl(path))
    return ids


def source_pool():
    records = []
    for model in MODELS:
        data = read_jsonl(ROOT / 'raw' / (model + '_result.jsonl'))
        scores = read_jsonl(ROOT / 'raw' / (model + '_score.jsonl'))
        failed = {s['id']: s for s in scores[1:]}
        if (len(failed) != len(scores)-1 or len(data) != scores[0]['total_count']
                or len(data)-len(failed) != scores[0]['correct_count']
                or any(s.get('valid') is not False for s in failed.values())
                or not set(failed) <= {r['id'] for r in data}):
            raise ValueError('invalid_source_score_index')
        for raw in data:
            records.append(normalize(raw, model, 'failure' if raw['id'] in failed else 'success'))
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate_execution_id')
    return records


def prepare(name, count, seed, max_bytes=36000, unique_tasks=False, exclude_history=False):
    batch = batch_path(name)
    if batch.exists():
        raise ValueError('batch_already_exists_use_run_or_export')
    if count < 0 or max_bytes < 0:
        raise ValueError('negative_selection_limit')
    excluded = historical_tasks() if exclude_history else set()
    pool = source_pool()
    candidates = []
    reasons = Counter()
    for record in pool:
        try:
            p.source_check(record)
        except ValueError as error:
            reasons['structural_' + str(error)] += 1
            continue
        if record['task_id'] in excluded:
            reasons['seen_task'] += 1
            continue
        if max_bytes and len(p.canonical(record['messages']).encode()) > max_bytes:
            reasons['context_scope'] += 1
            continue
        candidates.append(record)
    candidates.sort(key=lambda r: hashlib.sha256((seed + '|' + r['id']).encode()).hexdigest())
    selected, seen = [], set()
    for record in candidates:
        if unique_tasks and record['task_id'] in seen:
            continue
        selected.append({**record, 'case_id': f'{name}_{len(selected)+1:04d}', 'cohort': name})
        seen.add(record['task_id'])
        if count and len(selected) == count:
            break
    if count and len(selected) < count:
        raise ValueError(f'insufficient_scope_only_{len(selected)}_available')
    batch.mkdir(parents=True)
    write_jsonl(batch / 'selected_records.jsonl', selected)
    manifest = {'protocol': p.protocol_state(), 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'source_commit': json.loads((ROOT/'source_commit.json').read_text())['sha'],
                'source_release': '2025-11-03', 'seed': seed, 'max_message_bytes': max_bytes,
                'unique_tasks': unique_tasks, 'excluded_task_ids': sorted(excluded),
                'gold_used_for_selection': False, 'semantic_preselection': False,
                'source_executions': len(pool), 'source_tasks': len({r['task_id'] for r in pool}),
                'scope_exclusions': dict(reasons), 'eligible_executions': len(candidates),
                'eligible_tasks': len({r['task_id'] for r in candidates}),
                'selected': [{'case_id': r['case_id'], 'source_id': r['id'], 'task_id': r['task_id'],
                              'record_hash': p.digest(r)} for r in selected],
                'split_seed': SPLIT_SEED, 'selection_order': 'sha256(seed|execution_id)',
                'novelty_limitation': 'Available records and documented historical task IDs only.'}
    save(batch / 'manifest.json', manifest)
    save(batch / 'start_accounting.json', Client(ROOT).accounting())
    return {'selected': len(selected), 'eligible_executions': len(candidates),
            'eligible_tasks': manifest['eligible_tasks'], 'scope_exclusions': dict(reasons)}


def load_batch(batch):
    manifest = json.loads((batch / 'manifest.json').read_text())
    if manifest['protocol'] != p.protocol_state():
        raise ValueError('frozen_protocol_changed')
    if manifest['runner_sha256'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('frozen_runner_changed')
    records = read_jsonl(batch / 'selected_records.jsonl')
    if [p.digest(r) for r in records] != [r['record_hash'] for r in manifest['selected']]:
        raise ValueError('frozen_selection_changed')
    return manifest, records


def cached(client, payload):
    priced, _ = client.priced(payload)
    receipt = client.logs / (p.digest(priced) + '.json')
    if not receipt.exists():
        return False
    row = json.loads(receipt.read_text())
    if row.get('parsed') is not None:
        return True
    recovered = receipt.with_name(receipt.stem + '.recovery1.json')
    return recovered.exists() and json.loads(recovered.read_text()).get('parsed') is not None


def pair_reserve(client, record, feedback):
    generation = p.generation_payload(record, feedback)
    gen = 0 if cached(client, generation) else client.priced(generation)[1]
    stub = p.review_payload(record, None)
    # Actual candidate adds <= two copies of final text + fixed annotation overhead.
    review = client.priced(stub)[1] + (2*len(record['messages'][-1]['content'].encode())+4096) * float(client.models[p.REVIEWER]['pricing']['prompt']) * 1.05
    return gen + review


def run_record(record, client, batch, resume_errors=False):
    folder = batch / 'results'
    folder.mkdir(exist_ok=True)
    path = folder / (record['case_id'] + '.json')
    row = json.loads(path.read_text()) if path.exists() else {
        'case_id': record['case_id'], 'source_id': record['id'], 'task_id': record['task_id'],
        'source_hash': p.digest(record), 'protocol': p.VERSION, 'status': 'pending',
        'attempts': [], 'ready_for_judge_run': False}
    if row['source_hash'] != p.digest(record) or row['protocol'] != p.VERSION:
        raise ValueError('result_source_or_protocol_changed')
    if row['status'] in ('accepted', 'rejected', 'quarantined'):
        return row
    if row['status'] == 'operational_error' and not resume_errors:
        return row
    feedback = None
    try:
        p.source_check(record)
        for attempt in range(2):
            if attempt < len(row['attempts']) and row['attempts'][attempt].get('decision'):
                entry = row['attempts'][attempt]
                decision = entry['decision']
            else:
                if attempt == len(row['attempts']):
                    row['attempts'].append({'attempt': attempt})
                entry = row['attempts'][attempt]
                if 'generation' not in entry:
                    if pair_reserve(client, record, feedback) > client.accounting()['remaining_usd']:
                        raise BudgetError('generation_review_pair_does_not_fit')
                    generated, gh = client.request(p.generation_payload(record, feedback),
                        {'case': record['case_id'], 'stage': 'generation', 'attempt': attempt, 'protocol': p.VERSION})
                    entry.update(generation=generated, generation_request=gh)
                    save(path, row)  # Retain paid output even if parsing/materialization later fails.
                p.validate_schema(entry['generation'], p.GEN_SCHEMA)
                deletion = entry['generation']['deletion']
                entry['family'] = None if deletion is None else p.materialize(record, deletion)
                if 'review' not in entry:
                    review, rh = client.request(p.review_payload(record, entry['family']),
                        {'case': record['case_id'], 'stage': 'review', 'attempt': attempt, 'protocol': p.VERSION})
                    entry.update(review=review, review_request=rh)
                    save(path, row)  # Raw review survives validation errors as well.
                decision = p.decide(record, entry['family'], entry['review'])
                entry['decision'] = decision
            row.update(decision)
            row.pop('error', None)
            row.pop('error_type', None)
            review = entry['review']
            # One concrete edit repair, never a retry to change the outcome label.
            if (attempt == 1 or decision['status'] == 'accepted' or
                    not review['suggested_deletion'] or
                    any(x in decision['reasons'] for x in ('source_gold_disagreement', 'source_gold_missing', 'outcome_unknown', 'outcome_changed'))):
                save(path, row)
                break
            feedback = {'problem': review['edit_reason'],
                        'previous_deletion': entry['generation']['deletion'],
                        'suggested_deletion': review['suggested_deletion'],
                        'instruction': 'Propose one corrected edit; all original constraints still apply.'}
            row['status'] = 'pending'
            save(path, row)
    except BudgetError as error:
        row.update(status='budget_deferred', error=str(error))
    except Exception as error:
        # No exception text from transport: it might contain request details or credentials.
        row.update(status='operational_error', error_type=type(error).__name__)
        if type(error) is ValueError:
            row['error'] = str(error)
    save(path, row)
    return row


def task_split(task_id):
    bucket = int(hashlib.sha256((SPLIT_SEED + '|' + task_id).encode()).hexdigest()[:8], 16) % 100
    return 'train' if bucket < 80 else 'validation' if bucket < 90 else 'test'


def export(batch):
    manifest, records = load_batch(batch)
    accepted, candidates, rows = [], [], []
    for record in records:
        path = batch/'results'/(record['case_id']+'.json')
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if row['source_hash'] != p.digest(record):
            raise ValueError('export_source_hash_mismatch')
        rows.append(row)
        completed = [a for a in row['attempts'] if 'decision' in a]
        if not completed:
            continue
        entry = completed[-1]
        if entry['decision'] != p.decide(record, entry['family'], entry['review']):
            raise ValueError('decision_replay_mismatch')
        if row['status'] in ('accepted', 'rejected', 'quarantined') and row['status'] != entry['decision']['status']:
            raise ValueError('row_decision_mismatch')
        if entry['family'] is None:
            continue
        p.mechanical_check(record, entry['family'])
        for variant in entry['family']['variants']:
            item = {'sample_id': record['id']+'::'+variant['condition'], 'family_id': record['id'],
                    'task_id': record['task_id'], 'split': task_split(record['task_id']),
                    'protocol': p.VERSION, 'source_hash': entry['family']['source_hash'],
                    'source_gold': record['source_gold'], 'visible_outcome': entry['decision']['original_outcome'],
                    'selection_status': row['status'], 'ready_for_judge_run': False, **variant}
            candidates.append(item)
            if row['status'] == 'accepted':
                accepted.append(item)
    if len({r['sample_id'] for r in accepted}) != len(accepted):
        raise ValueError('duplicate_exported_sample')
    groups = {}
    for r in accepted:
        groups.setdefault(r['family_id'], []).append(r)
    for group in groups.values():
        if len(group) != 5 or len({r['split'] for r in group}) != 1 or len({p.digest(r['judge_payload']['trace']) for r in group}) != 1:
            raise ValueError('incomplete_or_inconsistent_family')
    out = batch/'exports'
    out.mkdir(exist_ok=True)
    write_jsonl(out/'all_results.jsonl', rows)
    write_jsonl(out/'candidate_inputs.jsonl', candidates)
    write_jsonl(out/'accepted_inputs.jsonl', accepted)
    for split in ('train','validation','test'):
        write_jsonl(out/(split+'.jsonl'), [r for r in accepted if r['split']==split])
    start = json.loads((batch/'start_accounting.json').read_text())
    account = Client(ROOT).accounting()
    summary = {'protocol':p.VERSION, 'selected':len(records), 'processed':len(rows),
        'statuses':dict(Counter(r['status'] for r in rows)), 'candidate_families':len(candidates)//5,
        'candidate_variants':len(candidates), 'accepted_families':len(accepted)//5,
        'accepted_variants':len(accepted), 'accounting':account,
        'confirmed_usd_since_batch_prepare':account['actual_usd']-start['actual_usd'],
        'cost_scope_note':'Shared ledger delta; diagnostic requests during this batch are included.',
        'unresolved_reserved_delta_usd':account['unresolved_reserved_usd']-start['unresolved_reserved_usd'],
        'Jev_calls':0, 'judge_experiment_run':False, 'ready_for_judge_run':False}
    save(batch/'SUMMARY.json',summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    s = sub.add_parser('prepare')
    s.add_argument('--batch',required=True); s.add_argument('--count',type=int,default=0)
    s.add_argument('--seed',required=True); s.add_argument('--max-bytes',type=int,default=36000)
    s.add_argument('--unique-tasks',action='store_true'); s.add_argument('--exclude-history',action='store_true')
    s = sub.add_parser('run')
    s.add_argument('--batch',required=True); s.add_argument('--run',action='store_true')
    s.add_argument('--limit',type=int); s.add_argument('--target-families',type=int)
    s.add_argument('--resume-errors',action='store_true')
    s = sub.add_parser('export'); s.add_argument('--batch',required=True)
    args = parser.parse_args()
    with (ROOT/'.run.lock').open('w') as lock:
        # Shared with v3 runners: concurrent runs cannot overspend the shared ledger.
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.command=='prepare':
            result=prepare(args.batch,args.count,args.seed,args.max_bytes,args.unique_tasks,args.exclude_history)
        elif args.command=='export':
            result=export(batch_path(args.batch))
        else:
            batch=batch_path(args.batch); _,records=load_batch(batch); client=Client(ROOT)
            if not args.run:
                result={'selected':len(records),'paid_calls':False,'accounting':client.accounting()}
            else:
                for record in records[:args.limit]:
                    current=export(batch)
                    if args.target_families and current['accepted_families']>=args.target_families:
                        break
                    row=run_record(record,client,batch,args.resume_errors)
                    print(json.dumps({'case':record['case_id'],'status':row['status'],
                                      'reasons':row.get('reasons'),'accounting':client.accounting()}),flush=True)
                    if row['status']=='budget_deferred':
                        break
                result=export(batch)
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
