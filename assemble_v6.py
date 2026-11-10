"""v6 production entry point: prepare, run/resume, verify and export. No API without --run."""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import re
from client import BudgetError, save
from budget_v6 import Client
import pipeline_v6 as p
import citation_fix_v6 as citation
import build_dataset as legacy

ROOT = Path(__file__).resolve().parent
TERMINAL = ('accepted', 'rejected', 'quarantined')


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def executed_tasks():
    """Exclude actual history, not never-run full-pool plans (which contain every task)."""
    seen = {'multi_turn_base_'+str(n) for n in [27,41,46,82,122,163,158,194,179,197,99,15]}
    for selection in [ROOT/'selected_records.jsonl', *ROOT.glob('batches/*/selected_records.jsonl')]:
        if not selection.exists():
            continue
        for record in legacy.read_jsonl(selection):
            result = selection.parent/'results'/(record['case_id']+'.json')
            if not result.exists():
                continue
            row = json.loads(result.read_text())
            if row.get('generation') or any(a.get('generation') for a in row.get('attempts', [])):
                seen.add(record['task_id'])
        
    extra = ROOT/'external_seen_tasks_v6.json'
    if extra.exists():
        seen.update(json.loads(extra.read_text()))
    return seen


def batch_path(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', name):
        raise ValueError('batch_name_must_be_a_simple_identifier')
    return ROOT/'batches'/name


def runtime_hashes():
    return {name: file_hash(ROOT/name) for name in
            ('assemble_v6.py', 'budget_v6.py', 'budget_v4.py', 'client.py', 'prepare_data.py',
             'build_dataset.py', 'models_snapshot_v6.json', 'external_seen_tasks_v6.json', 'citation_fix_v6.py')}


def prepare(name, count, seed, max_bytes=0, unique_tasks=True, exclude_history=True, input_path=None):
    batch = batch_path(name)
    if batch.exists():
        raise ValueError('batch_already_exists')
    if count < 0 or max_bytes < 0:
        raise ValueError('negative_selection_limit')
    records = legacy.read_jsonl(input_path) if input_path else legacy.source_pool()
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('duplicate_source_id')
    excluded = executed_tasks() if exclude_history else set()
    eligible, reasons = [], Counter()
    for r in records:
        try:
            p.source_check(r)
        except ValueError as e:
            reasons['structural_'+str(e)] += 1
            continue
        if r['task_id'] in excluded:
            reasons['already_used_task'] += 1
            continue
        if max_bytes and len(p.canonical(r['messages']).encode()) > max_bytes:
            reasons['declared_length_scope'] += 1
            continue
        eligible.append(r)
    eligible.sort(key=lambda r: p.digest([seed, r['id']]))
    selected, seen = [], set()
    for r in eligible:
        if unique_tasks and r['task_id'] in seen:
            continue
        selected.append({**r, 'case_id': f'{name}_{len(selected)+1:04d}', 'cohort': name})
        seen.add(r['task_id'])
        if count and len(selected) == count:
            break
    if count and len(selected) < count:
        raise ValueError('insufficient_eligible_records_'+str(len(selected)))
    if not selected:
        raise ValueError('empty_selection')
    batch.mkdir(parents=True)
    legacy.write_jsonl(batch/'selected_records.jsonl', selected)
    source = {'input_sha256': file_hash(input_path)} if input_path else {
        'dataset': 'HuanzhiMao/BFCL-Result', 'release': '2025-11-03',
        'commit': json.loads((ROOT/'source_commit.json').read_text())['sha'],
        'raw_files': {path.name: file_hash(path) for path in sorted((ROOT/'raw').glob('*.jsonl'))}}
    manifest = {'protocol': p.protocol_state(), 'runtime_hashes': runtime_hashes(), 'source': source,
        'seed': seed, 'selection_order': 'sha256(canonical([seed,source_id]))',
        'max_message_bytes': max_bytes, 'unique_tasks': unique_tasks,
        'excluded_task_ids': sorted(excluded), 'scope_exclusions': dict(reasons),
        'eligible_executions': len(eligible), 'source_executions': len(records),
        'source_tasks': len({r['task_id'] for r in records}), 'semantic_preselection': False,
        'gold_used_for_selection': False, 'split_seed': legacy.SPLIT_SEED,
        'selected': [{'case_id': r['case_id'], 'source_id': r['id'], 'task_id': r['task_id'],
                      'record_hash': p.digest(r)} for r in selected],
        'novelty_limit': 'Available executed history and documented prior IDs; earlier missing archives cannot be checked.'}
    save(batch/'manifest.json', manifest)
    save(batch/'start_accounting.json', Client(ROOT).accounting())
    return {'selected': len(selected), 'eligible_executions': len(eligible), 'scope_exclusions': dict(reasons)}


def load_batch(batch):
    manifest = json.loads((batch/'manifest.json').read_text())
    if manifest['protocol'] != p.protocol_state() or manifest['runtime_hashes'] != runtime_hashes():
        raise ValueError('frozen_protocol_or_runtime_changed')
    records = legacy.read_jsonl(batch/'selected_records.jsonl')
    actual = [{'case_id': r['case_id'], 'source_id': r['id'], 'task_id': r['task_id'],
               'record_hash': p.digest(r)} for r in records]
    if actual != manifest['selected']:
        raise ValueError('frozen_selection_changed')
    return manifest, records


def replay_decision(record, row):
    p.validate_schema(row['generation'], p.GEN_SCHEMA)
    deletion = row['generation']['deletion']
    if deletion is None:
        if row.get('family') is not None:
            raise ValueError('null_family_mismatch')
        return {'status': 'rejected', 'reasons': ['no_candidate'], 'label_policy': p.LABEL_POLICY}
    if row.get('family') != p.materialize(record, deletion):
        raise ValueError('family_mismatch')
    if 'review' not in row:
        return {'status':'awaiting_review','reasons':['current_primary_review_required'],'label_policy':p.LABEL_POLICY}
    try:
        review=effective_review(record,row,'review')
        audit=effective_review(record,row,'audit') if 'audit' in row else None
    except ValueError as error:
        return {'status':'quarantined','reasons':['invalid_citation_repair'],
            'validation_error':str(error),'label_policy':p.LABEL_POLICY}
    return p.decide(record, row['family'], review, audit)


def effective_review(record,row,stage):
    return (citation.apply(record,row[stage],row[stage+'_citation_fix'])
        if stage+'_citation_fix' in row else row[stage])


def repair_citations(record,row,stage,client,path):
    if stage+'_citation_fix' not in row and citation.issues(record,row[stage]):
        row[stage+'_citation_fix'],row[stage+'_citation_fix_request']=client.request(
            citation.payload(record,row[stage]),{'case':record['case_id'],'stage':stage+'_citation_format',
                'protocol':p.VERSION,'semantic_labels_change':False})
        save(path,row)


def audit_payload(record, family, row):
    payload=p.review_payload(record,family,auditor=True)
    if row.get('audit_length_retry'):
        payload['max_tokens']=24576
    return payload


def known_length_receipt(client, payload):
    if not hasattr(client,'priced') or not hasattr(client,'logs'):
        return None
    request=client.priced(payload)[0];rid=p.digest(request);path=client.logs/(rid+'.json')
    if not path.exists():return None
    receipt=json.loads(path.read_text());cost=receipt.get('actual_usd')
    choices=receipt.get('response',{}).get('choices',[])
    if (receipt.get('request')==request and receipt.get('status')=='operational_error'
            and type(cost) in (int,float) and cost>=0 and choices
            and choices[0].get('finish_reason')=='length' and receipt.get('parsed') is None):
        return rid
    return None


def request_audit(record, row, client, path):
    initial=p.review_payload(record,row['family'],auditor=True)
    for attempt in range(2):
        rid=known_length_receipt(client,initial) if not row.get('audit_length_retry') else None
        if rid:
            row['audit_length_retry']={'original_request_id':rid,'max_tokens':24576,
                'reason':'Known billed response exhausted the combined reasoning/output budget.'}
            row['superseded_request_ids']=sorted(set(row.get('superseded_request_ids',[])+[rid]))
            save(path,row)
        try:
            return client.request(audit_payload(record,row['family'],row),
                {'case':record['case_id'],'stage':'independent_audit','protocol':p.VERSION,
                 'length_retry':bool(row.get('audit_length_retry'))})
        except ValueError as error:
            if (str(error)!='incomplete_response_length' or row.get('audit_length_retry')
                    or not known_length_receipt(client,initial)):
                raise
    raise ValueError('audit_length_retry_exhausted')


def run_record(record, client, batch, resume_errors=False):
    folder = batch/'results'
    folder.mkdir(exist_ok=True)
    path = folder/(record['case_id']+'.json')
    row = json.loads(path.read_text()) if path.exists() else {
        'case_id': record['case_id'], 'source_id': record['id'], 'task_id': record['task_id'],
        'source_hash': p.digest(record), 'protocol': p.VERSION, 'status': 'pending'}
    if row['source_hash'] != p.digest(record) or row['protocol'] != p.VERSION:
        raise ValueError('result_identity_mismatch')
    if row['status'] in TERMINAL:
        if row['decision'] != replay_decision(record, row):
            raise ValueError('completed_decision_changed')
        return row
    if row['status'] == 'operational_error' and not resume_errors:
        return row
    try:
        p.source_check(record)
        if 'generation' not in row:
            row['generation'], row['generation_request'] = client.request(p.generation_payload(record),
                {'case': record['case_id'], 'stage': 'generation', 'protocol': p.VERSION})
            save(path, row)
        p.validate_schema(row['generation'], p.GEN_SCHEMA)
        deletion = row['generation']['deletion']
        row['family'] = None if deletion is None else p.materialize(record, deletion)
        save(path, row)
        if row['family'] is not None:
            if 'review' not in row:
                row['review'], row['review_request'] = client.request(p.review_payload(record, row['family']),
                    {'case': record['case_id'], 'stage': 'review', 'protocol': p.VERSION})
                save(path, row)
            repair_citations(record,row,'review',client,path)
            first = replay_decision(record,row)
            row['decision']=first
            save(path,row)
            if first['status'] == 'awaiting_audit' and 'audit' not in row:
                row['audit'], row['audit_request'] = request_audit(record,row,client,path)
                save(path, row)
            if 'audit' in row:
                repair_citations(record,row,'audit',client,path)
        row['decision'] = replay_decision(record, row)
        row['status'] = row['decision']['status']
        row.pop('error', None)
        row.pop('error_type', None)
    except BudgetError as e:
        row.update(status='budget_deferred', error=str(e))
    except Exception as e:
        row.update(status='operational_error', error_type=type(e).__name__)
        if type(e) is ValueError:
            row['error'] = str(e)
    save(path, row)
    return row


def export(batch):
    manifest, records = load_batch(batch)
    candidates, accepted, rows = [], [], []
    receipt_ids = set()
    alignment_path = ROOT/'SOURCE_ALIGNMENT_AUDIT.json'
    alignments = {r['source_id']: r['status'] for r in json.loads(alignment_path.read_text())['rows']} if alignment_path.exists() else {}
    for record in records:
        path = batch/'results'/(record['case_id']+'.json')
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if row['source_hash'] != p.digest(record) or row['protocol'] != p.VERSION:
            raise ValueError('export_identity_mismatch')
        rows.append(row)
        receipt_ids.update(row[k] for k in ('generation_request', 'review_request', 'audit_request',
            'review_citation_fix_request','audit_citation_fix_request') if k in row)
        receipt_ids.update(row.get('superseded_request_ids', []))
        if row['status'] in TERMINAL:
            if row['decision'] != replay_decision(record, row) or row['status'] != row['decision']['status']:
                raise ValueError('export_decision_mismatch')
        family = row.get('family')
        if family is None:
            continue
        p.mechanical_check(record, family)
        for variant in family['variants']:
            item = {'sample_id': record['id']+'::'+variant['condition'], 'family_id': record['id'],
                'task_id': record['task_id'], 'split': legacy.task_split(record['task_id']),
                'protocol': p.VERSION, 'source_hash': family['source_hash'],
                'benchmark_grade': record.get('source_gold'),
                'trace_label': row.get('decision', {}).get('original_outcome'),
                'label_policy': p.LABEL_POLICY, 'label_status': 'automatic_not_human_gold',
                'source_replay_alignment': alignments.get(record['id'], 'not_audited'),
                'selection_status': row['status'], 'ready_for_judge_run': False, **variant}
            candidates.append(item)
            if row['status'] == 'accepted':
                accepted.append(item)
    groups = {}
    for item in accepted:
        groups.setdefault(item['family_id'], []).append(item)
    if len({x['sample_id'] for x in accepted}) != len(accepted):
        raise ValueError('duplicate_samples')
    for group in groups.values():
        if (len(group) != 5 or {x['condition'] for x in group} != {c[0] for c in p.CONDITIONS}
            or len({p.digest(x['judge_payload']['trace']) for x in group}) != 1
            or len({x['split'] for x in group}) != 1):
            raise ValueError('invalid_family_export')
    out = batch/'exports'
    out.mkdir(exist_ok=True)
    for name, values in [('all_results', rows), ('candidate_inputs', candidates), ('accepted_inputs', accepted)]:
        legacy.write_jsonl(out/(name+'.jsonl'), values)
    for split in ('train', 'validation', 'test'):
        legacy.write_jsonl(out/(split+'.jsonl'), [x for x in accepted if x['split'] == split])
    receipts = [json.loads((ROOT/'requests'/(rid+'.json')).read_text()) for rid in sorted(receipt_ids)]
    cost = sum(r.get('actual_usd') or 0 for r in receipts)
    summary = {'protocol': p.VERSION, 'selected': len(records), 'processed': len(rows),
        'completed_final_protocol':sum(r['status'] in TERMINAL for r in rows),
        'pending_final_protocol':len(records)-sum(r['status'] in TERMINAL for r in rows),
        'current_primary_reviews':sum('review' in r for r in rows),
        'current_independent_audits':sum('audit' in r for r in rows),
        'statuses': dict(Counter(r['status'] for r in rows)), 'candidate_families': len(candidates)//5,
        'candidate_variants': len(candidates), 'accepted_families': len(accepted)//5,
        'accepted_variants': len(accepted), 'calls_referenced': len(receipts),
        'batch_receipt_cost_usd': cost, 'cost_per_processed_source_usd': cost/len(rows) if rows else None,
        'cost_per_accepted_family_usd': cost/len(groups) if groups else None,
        'acceptance_labels': dict(Counter(g[0]['trace_label'] for g in groups.values())),
        'accounting': Client(ROOT).accounting(), 'Jev_calls': 0,
        'judge_experiment_run': False, 'ready_for_judge_run': False,
        'quality_claim': 'Two blind LLM reviews, not a human-validated accuracy guarantee.'}
    save(batch/'SUMMARY.json', summary)
    return summary


def verify(batch):
    manifest, records = load_batch(batch)
    client = Client(ROOT)
    before = client.accounting()
    counts = Counter()
    if 'raw_files' in manifest['source']:
        for name, expected in manifest['source']['raw_files'].items():
            if file_hash(ROOT/'raw'/name) != expected:
                raise ValueError('raw_source_changed')
        source = {r['id']: r for r in legacy.source_pool()}
    else:
        source = None
    class NoTransport(Client):
        def request(self, *args, **kwargs):
            raise AssertionError('completed_replay_attempted_API')
    for record in records:
        if source is not None:
            if record != {**source[record['id']], 'case_id': record['case_id'], 'cohort': record['cohort']}:
                raise ValueError('normalization_changed')
        path = batch/'results'/(record['case_id']+'.json')
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        for stage in ('generation', 'review', 'audit'):
            if stage not in row:
                continue
            payload = (p.generation_payload(record) if stage == 'generation' else
                audit_payload(record,row['family'],row) if stage=='audit' else p.review_payload(record,row['family']))
            receipt = json.loads((ROOT/'requests'/(row[stage+'_request']+'.json')).read_text())
            if (receipt['request'] != client.priced(payload)[0] or receipt['parsed'] != row[stage]
                or p.digest(receipt['request']) != receipt['request_hash']):
                raise ValueError('receipt_mismatch')
            counts['receipts_verified'] += 1
        if row.get('audit_length_retry'):
            original=p.review_payload(record,row['family'],True)
            if known_length_receipt(client,original)!=row['audit_length_retry']['original_request_id']:
                raise ValueError('invalid_length_retry_provenance')
            counts['length_retries_verified']+=1
        for stage in ('review','audit'):
            key=stage+'_citation_fix'
            if key in row:
                receipt=json.loads((ROOT/'requests'/(row[key+'_request']+'.json')).read_text())
                if receipt['request']!=client.priced(citation.payload(record,row[stage]))[0] or receipt['parsed']!=row[key]:
                    raise ValueError('citation_repair_receipt_mismatch')
                effective_review(record,row,stage)
                counts['citation_repairs_verified']+=1
        if row['status'] in TERMINAL:
            run_record(record, NoTransport(ROOT), batch)
            counts['completed_resumes_without_API'] += 1
        if row.get('family'):
            p.mechanical_check(record, row['family'])
            counts['families_verified'] += 1
        counts['sources_verified'] += 1
    if client.accounting() != before:
        raise ValueError('offline_verification_spent_money')
    report = {'passed': True, **counts, 'paid_calls': 0, 'protocol_locked': True,
              'selection_and_sources_verified': True, 'raw_stage_receipts_match': True,
              'result': export(batch)}
    save(batch/'OFFLINE_VERIFICATION.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    s = sub.add_parser('prepare')
    s.add_argument('--batch', required=True); s.add_argument('--count', type=int, default=0)
    s.add_argument('--seed', required=True); s.add_argument('--max-bytes', type=int, default=0)
    s.add_argument('--allow-seen', action='store_true'); s.add_argument('--allow-same-task', action='store_true')
    s.add_argument('--input', type=Path)
    s = sub.add_parser('run')
    s.add_argument('--batch', required=True); s.add_argument('--run', action='store_true')
    s.add_argument('--limit', type=int); s.add_argument('--target-families', type=int)
    s.add_argument('--resume-errors', action='store_true')
    for name in ('export', 'verify'):
        s = sub.add_parser(name); s.add_argument('--batch', required=True)
    args = parser.parse_args()
    if args.command == 'run' and any(v is not None and v <= 0 for v in (args.limit, args.target_families)):
        parser.error('--limit and --target-families must be positive')
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == 'prepare':
            result = prepare(args.batch, args.count, args.seed, args.max_bytes,
                             not args.allow_same_task, not args.allow_seen, args.input)
        elif args.command in ('verify', 'export'):
            result = (verify if args.command == 'verify' else export)(batch_path(args.batch))
        else:
            batch = batch_path(args.batch)
            _, records = load_batch(batch)
            client = Client(ROOT)
            if not args.run:
                result = {'selected': len(records), 'paid_calls': False, 'accounting': client.accounting()}
            else:
                for record in records[:args.limit]:
                    if args.target_families and export(batch)['accepted_families'] >= args.target_families:
                        break
                    row = run_record(record, client, batch, args.resume_errors)
                    print(json.dumps({'case': record['case_id'], 'status': row['status'],
                        'reasons': row.get('decision', {}).get('reasons'), 'error': row.get('error'),
                        'session_spend': client.accounting()['session_actual_usd'],
                        'remaining': client.accounting()['remaining_usd']}), flush=True)
                    if row['status'] == 'budget_deferred':
                        break
                result = export(batch)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
