"""Frozen diagnostic controls, separate from production selection and exports."""
import argparse
import fcntl
import json
from pathlib import Path
import pipeline_v6 as p
import assemble_v6 as a
from budget_v6 import Client
from client import BudgetError, save

ROOT=Path(__file__).resolve().parent
FOLDER=ROOT/'diagnostics_v6'


def evaluate(case, review):
    reference=case['reference']; by_id={r['user_id']:r for r in review.get('requests',[]) if isinstance(r,dict)}
    errors=[]
    if review.get('edit_verdict') != reference['edit_verdict']:errors.append('edit_verdict')
    for constraint in reference['constraints']:
        for label in ('original','base'):
            if by_id.get(constraint['user_id'],{}).get(label) not in constraint[label]:
                errors.append(constraint['user_id']+':'+label)
    family=p.materialize(case['record'],case['deletion'])
    try:
        assessment=p.assess(case['record'],family,review,True)
        valid=True;error=None
    except (ValueError,KeyError,TypeError) as e:
        assessment=None;valid=False;error=str(e)
    return {'semantic_constraints_pass':not errors,'semantic_errors':errors,
        'contract_valid':valid,'contract_error':error,'assessment':assessment,
        'full_pass':not errors and valid}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true');parser.add_argument('--case',action='append')
    args=parser.parse_args()
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        cases=json.loads((FOLDER/'cases.json').read_text())
        manifest=json.loads((FOLDER/'manifest.json').read_text())
        if manifest['cases_hash']!=p.digest(cases) or manifest['protocol']!=p.protocol_state():
            raise ValueError('frozen_diagnostic_protocol_changed')
        c=Client(ROOT);rows=[]
        for case in cases:
            if args.case and case['case_id'] not in args.case:continue
            family=p.materialize(case['record'],case['deletion'])
            payload=p.review_payload(case['record'],family,True)
            if not args.run:
                print(json.dumps({'case':case['case_id'],'reserve_usd':c.priced(payload)[1],'paid_calls':0}));continue
            path=FOLDER/'results'/(case['case_id']+'.json');path.parent.mkdir(exist_ok=True)
            if path.exists():
                row=json.loads(path.read_text())
                receipt=json.loads((ROOT/'requests'/(row['request_id']+'.json')).read_text())
                if receipt['request']!=c.priced(payload)[0] or row['review']!=receipt['parsed']:
                    raise ValueError('diagnostic_receipt_mismatch')
                if row['evaluation']!=evaluate(case,row['review']):raise ValueError('diagnostic_replay_changed')
            else:
                try:review,rid=c.request(payload,{'stage':'diagnostic_v6','case':case['case_id'],'protocol':p.VERSION})
                except BudgetError:
                    print(json.dumps({'case':case['case_id'],'status':'budget_deferred'}));break
                row={'case_id':case['case_id'],'request_id':rid,'review':review,'evaluation':evaluate(case,review)}
                save(path,row)
            rows.append(row)
            print(json.dumps({'case':case['case_id'],**row['evaluation'],'session_spend':c.accounting()['session_actual_usd']}),flush=True)
        if args.run:
            save(FOLDER/'SUMMARY.json',{'completed':len(rows),'full_pass':sum(r['evaluation']['full_pass'] for r in rows),
                'semantic_pass':sum(r['evaluation']['semantic_constraints_pass'] for r in rows),
                'human_gold':False,'iid_holdout':False,'dataset_export':False,'accounting':c.accounting()})


if __name__=='__main__':main()
