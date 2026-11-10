"""Known regressions, explicitly separate from the frozen new-source pilot."""
import argparse
import fcntl
import json
from pathlib import Path
from client import save
from budget_v5 import Client
from build_dataset import read_jsonl
import pipeline_v5 as p

ROOT=Path(__file__).resolve().parent
CASES=[
    ('pressure', 'v3_new10_20261026','v3_new10_07',False),
    ('purchase','v3_new10_20261026','v3_new10_03',False),
    ('directory','v4_holdout8_20261027','v4_holdout8_20261027_0005',False),
    ('airport','v4_holdout8_20261027','v4_holdout8_20261027_0007',False),
    ('airport_audit','v4_holdout8_20261027','v4_holdout8_20261027_0007',True)]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--case');args=parser.parse_args()
    folder=ROOT/'diagnostics_v5';folder.mkdir(exist_ok=True)
    plan={'protocol':p.protocol_state(),'cases':[list(c) for c in CASES],
          'scope':'Known weaknesses, not independent holdout accuracy.',
          'expected':{'pressure':'second request failure; threshold contradicts final prose',
              'purchase':'acquisition/postexecution request must not be success',
              'directory':'move request failure from wrong relative directory',
              'airport':'not accepted due to unsupported airport-name expansion',
              'airport_audit':'same as airport, independent model'}}
    if (folder/'plan.json').exists():
        assert json.loads((folder/'plan.json').read_text())==plan,'diagnostic_plan_changed'
    else:save(folder/'plan.json',plan)
    if not args.run:print(json.dumps(plan));return
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        client=Client(ROOT)
        for name,batch,case,auditor in CASES:
            if args.case and name!=args.case:continue
            out=folder/(name+'.json')
            if out.exists():continue
            source=ROOT/'batches'/batch
            record=next(r for r in read_jsonl(source/'selected_records.jsonl') if r['case_id']==case)
            previous=json.loads((source/'results'/(case+'.json')).read_text())
            family=previous['attempts'][-1].get('family') if previous['attempts'] else None
            review,rid=client.request(p.review_payload(record,family,auditor),
                {'case':case,'stage':'v5_diagnostic_'+name,'protocol':p.VERSION})
            result={'name':name,'case_id':case,'source_id':record['id'],'auditor':auditor,
                    'review':review,'request':rid,'family':family}
            save(out,result)
            result['assessment']=p.assess(record,family,review)
            save(out,result)
            print(json.dumps({'case':name,'outcomes':[r['original'] for r in review['requests']],
                'status':result['assessment']['status'],'reasons':result['assessment']['reasons'],
                'accounting':client.accounting()}),flush=True)


if __name__=='__main__':main()
