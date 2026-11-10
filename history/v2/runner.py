"""CLI: python runner.py --run [--limit N]. Defaults to no paid requests."""
import argparse
import fcntl
import json
from pathlib import Path
from client import Client,BudgetError,save
from pipeline import (freeze,source_check,generation_payload,review_payload,
                      validate_schema,GEN_SCHEMA,materialize,decide,mechanical_check,local_edit_errors)
ROOT=Path(__file__).resolve().parent

def read_records():
    return [json.loads(l) for l in (ROOT/'selected_records.jsonl').read_text().splitlines()]

def run_record(record,client):
    outdir=ROOT/'results';outdir.mkdir(exist_ok=True)
    path=outdir/(record['case_id']+'.json')
    if path.exists():
        old=json.loads(path.read_text())
        if old['status'] not in ('pending','budget_deferred'):return old
    row={'case_id':record['case_id'],'source_id':record['id'],'cohort':record['cohort'],
         'status':'pending','attempts':[],'ready_for_judge_run':False}
    save(path,row)
    try:
        source_check(record)
        feedback=None
        for attempt in range(2):
            # Reserve capacity for generation + review before starting a family/repair.
            gen_payload=generation_payload(record,feedback)
            gen_bound=client.priced(gen_payload)[1]
            # Even the largest possible candidate representation can be bounded by source bytes.
            review_stub=review_payload(record,None)
            review_bound=client.priced(review_stub)[1]+(2*len(record['messages'][-1]['content'].encode())+4096)*float(client.models[review_stub['model']]['pricing']['prompt'])*1.05
            if gen_bound+review_bound>client.accounting()['remaining_usd']:
                if row['attempts']:row['repair_deferred_for_budget']=True;break
                raise BudgetError('generation_review_pair_does_not_fit')
            generated,gh=client.request(gen_payload,{'case':record['case_id'],'stage':'generation','attempt':attempt})
            validate_schema(generated,GEN_SCHEMA)
            family=None if generated['deletion'] is None else materialize(record,generated['deletion'])
            guard_errors=local_edit_errors(record,family)
            if guard_errors:
                decision={'status':'rejected','reasons':guard_errors,'original_outcome':None,'base_outcome':None}
                row['attempts'].append({'generation_request':gh,'review_request':None,'generation':generated,
                                        'family':family,'review':None,'decision':decision})
                row.update(decision);save(path,row)
                feedback={'problem':'; '.join(guard_errors),'previous_deletion':generated['deletion'],
                          'instruction':'Keep all standalone numeric values and coherent punctuation. Choose a different legal span or null.'}
                continue
            review,rh=client.request(review_payload(record,family),{'case':record['case_id'],'stage':'review','attempt':attempt})
            decision=decide(record,family,review)
            row['attempts'].append({'generation_request':gh,'review_request':rh,'generation':generated,
                                    'family':family,'review':review,'decision':decision})
            row.update(decision);save(path,row)
            # Repair only a concrete edit problem. No retry until an answer becomes positive.
            if attempt==1 or decision['status'] in ('accepted','quarantined'):break
            if not review['suggested_deletion']:break
            feedback={'problem':review['edit_reason'],'previous_deletion':generated['deletion'],
                      'suggested_deletion':review['suggested_deletion'],'instruction':'Propose one corrected edit; all original constraints still apply.'}
    except BudgetError as e:
        row['status']='budget_deferred';row['error']=str(e)
    except Exception as e:
        row['status']='operational_error';row['error_type']=type(e).__name__
    save(path,row)
    return row

def summarize(client):
    from collections import Counter
    rows=[json.loads(p.read_text()) for p in sorted((ROOT/'results').glob('*.json'))]
    s={'processed':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
       'accepted_families':sum(r['status']=='accepted' for r in rows),
       'accounting':client.accounting(),'Jev_calls':0,'judge_experiment_run':False}
    s['accepted_variants']=s['accepted_families']*5
    save(ROOT/'SUMMARY.json',s);return s

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--limit',type=int)
    a=p.parse_args();client=Client();records=read_records()
    if not a.run:
        print(json.dumps({'selected':len(records),'accounting':client.accounting(),'paid_calls':False}));return
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);freeze(ROOT)
        for record in records[:a.limit]:
            row=run_record(record,client)
            print(json.dumps({'case':record['case_id'],'status':row['status'],'reasons':row.get('reasons'),'accounting':client.accounting()}),flush=True)
            summarize(client)
            if row['status'] in ('budget_deferred','operational_error'):break

if __name__=='__main__':main()
