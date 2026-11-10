"""Two known semantic weaknesses: diagnostics only, never holdout estimates."""
import argparse
import fcntl
import json
from pathlib import Path
from client import Client,save
from build_dataset import read_jsonl
import pipeline_v4 as p

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'batches/v4_diagnostics_20261027'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true')
    args=parser.parse_args();OUT.mkdir(exist_ok=True)
    previous=ROOT/'batches/v3_new10_20261026'
    records={r['case_id']:r for r in read_jsonl(previous/'selected_records.jsonl')}
    expected={'v3_new10_07':{'request':'m0017','must_not_be':'success','reason':'35/35/32/32 psi contradicts above-40 claim; no directions.'},
              'v3_new10_03':{'request':'m0008','must_not_be':'success','reason':'Acquisition and post-execution notification are not established by Pending/Open.'}}
    plan={'protocol':p.protocol_state(),'expected':expected,'scope':'Known diagnostic cases, not independent quality measurement.'}
    path=OUT/'plan.json'
    if path.exists():assert json.loads(path.read_text())==plan
    else:save(path,plan)
    if not args.run:print(json.dumps(plan));return
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        client=Client(ROOT)
        for case in expected:
            target=OUT/(case+'.json')
            if target.exists():continue
            record=records[case]
            old=json.loads((previous/'results'/(case+'.json')).read_text())
            family=old['attempts'][-1]['family'] if old['attempts'] else None
            payload=p.review_payload(record,family)
            review,rh=client.request(payload,{'case':case,'stage':'v4_diagnostic_review','protocol':p.VERSION})
            result={'case_id':case,'review':review,'request':rh,'family':family}
            save(target,result)
            result['decision']=p.decide(record,family,review)
            row=next(r for r in review['requests'] if r['user_id']==expected[case]['request'])
            result['diagnostic_pass']=row['original']!=expected[case]['must_not_be']
            save(target,result)
            print(json.dumps({'case':case,'diagnostic_pass':result['diagnostic_pass'],
                              'decision':result['decision'],'accounting':client.accounting()}),flush=True)

if __name__=='__main__':main()
