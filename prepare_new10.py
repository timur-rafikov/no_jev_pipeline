"""Freeze ten unseen task IDs for a v3 pilot. Offline, no semantic screening."""
import hashlib
import json
from pathlib import Path
from client import Client,save
from pipeline import canonical,digest,freeze,source_check,generation_payload,review_payload,VERSION
from prepare_data import MODELS,normalize

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v3_new10_20261026'
SEED='no-jev-v3-new10-20261026'

def main():
    protocol=freeze(ROOT)
    previous=[json.loads(l) for l in (ROOT/'selected_records.jsonl').read_text().splitlines()]
    known_old={'multi_turn_base_'+str(n) for n in [27,41,46,82,122,163,158,194,179,197,99,15]}
    excluded=known_old|{r['task_id'] for r in previous}
    eligible=[];raw_by_id={};structural=0
    for model in MODELS:
        data=[json.loads(l) for l in (ROOT/'raw'/(model+'_result.jsonl')).read_text().splitlines()]
        scores=[json.loads(l) for l in (ROOT/'raw'/(model+'_score.jsonl')).read_text().splitlines()]
        failed={s['id']:s for s in scores[1:]}
        assert len(failed)==len(scores)-1
        assert len(data)==scores[0]['total_count']==200
        assert len(data)-len(failed)==scores[0]['correct_count']
        assert all(x.get('valid') is False for x in failed.values())
        for raw in data:
            r=normalize(raw,model,'failure' if raw['id'] in failed else 'success')
            try:source_check(r)
            except ValueError:continue
            structural+=1
            if r['task_id'] in excluded or len(canonical(r['messages']).encode())>36000:continue
            eligible.append(r)
            raw_by_id[r['id']]={'id':r['id'],'result':raw,'score':failed.get(raw['id']),'score_header':scores[0]}
    eligible.sort(key=lambda r:hashlib.sha256((SEED+'|'+r['id']).encode()).hexdigest())
    selected=[];seen=set(excluded)
    for record in eligible:
        if record['task_id'] in seen:continue
        selected.append({**record,'case_id':f'v3_new10_{len(selected)+1:02d}','cohort':'v3_unseen_task_hash_sample'})
        seen.add(record['task_id'])
        if len(selected)==10:break
    assert len(selected)==10 and len({r['task_id'] for r in selected})==10
    assert not {r['task_id'] for r in selected}&excluded
    BATCH.mkdir(parents=True,exist_ok=True)
    records_text=''.join(canonical(r)+'\n' for r in selected)
    target=BATCH/'selected_records.jsonl'
    if target.exists():assert target.read_text()==records_text,'Selection is already frozen.'
    else:target.write_text(records_text)
    raw_text=''.join(canonical(raw_by_id[r['id']])+'\n' for r in selected)
    raw_path=BATCH/'selected_raw.jsonl'
    if raw_path.exists():assert raw_path.read_text()==raw_text
    else:raw_path.write_text(raw_text)
    client=Client();costs=[]
    for record in selected:
        gen=client.priced(generation_payload(record))[1]
        review=review_payload(record,None)
        bound=client.priced(review)[1]+(2*len(record['messages'][-1]['content'].encode())+4096)*float(client.models[review['model']]['pricing']['prompt'])*1.05
        costs.append({'case_id':record['case_id'],'generation_reserve_usd':gen,
                      'review_reserve_usd':bound,'initial_pair_reserve_usd':gen+bound})
    historical=[]
    for path in (ROOT/'requests').glob('*.json'):
        r=json.loads(path.read_text())
        if r.get('actual_usd') is not None and r['tag']['stage'] in ('generation','review'):
            historical.append(r['actual_usd'])
    historical_completed=sum(bool(json.loads(p.read_text())['attempts']) for p in (ROOT/'history/v2/results').glob('*.json'))
    expected=sum(historical)/historical_completed*10
    manifest={'protocol':protocol,'seed':SEED,'source_commit':json.loads((ROOT/'source_commit.json').read_text())['sha'],
              'selection':'First 10 distinct task IDs in sha256(seed|execution_id) order; same <=36000-byte context scope as previous pilot.',
              'excluded_task_ids':sorted(excluded),'excluded_previously_selected_even_if_unprocessed':True,
              'gold_used_for_selection':False,'semantic_screening':False,'lexical_screening':False,
              'structurally_eligible_executions':structural,'size_eligible_unseen_executions':len(eligible),
              'novelty_scope':'No task overlap with currently available selection and documented historical task exclusions; unavailable earlier archives cannot be checked.',
              'selected':[{'case_id':r['case_id'],'source_id':r['id'],'task_id':r['task_id'],
                           'source_hash':digest(r),'message_bytes':len(canonical(r['messages']).encode())} for r in selected]}
    save(BATCH/'selection_manifest.json',manifest)
    preflight={'status':'awaiting_budget_extension','selected':10,'paid_calls':0,
               'current_accounting':client.accounting(),'expected_initial_run_usd_from_six_prior_records':expected,
               'estimate_is_not_a_quote':True,'cost_reserves':costs,
               'sum_initial_pair_upper_reserves_usd':sum(x['initial_pair_reserve_usd'] for x in costs),
               'cheapest_pair_fits_current_budget':min(x['initial_pair_reserve_usd'] for x in costs)<=client.accounting()['remaining_usd'],
               'quality_audit':'Assistant reads all ten original traces and actual edits without model verdicts first; then compares against accepted/rejected/quarantined decisions. No extra paid LLM calls planned for this audit.',
               'pipeline_fixed_during_pilot':True,'existing_budget_unchanged':True}
    save(BATCH/'PREFLIGHT.json',preflight)
    save(BATCH/'AUDIT_PLAN.json',{
        'scope':'Every one of the ten tasks, including rejected and quarantined cases.',
        'blinding':'Inspect originals and actual candidate edits before reading generator rationale, reviewer verdicts, or source benchmark labels.',
        'checks':['Target is a completion claim rather than the requested answer.',
                  'Actual edits preserve requested deliverables, caveats, error disclosures, and execution evidence.',
                  'The remaining message is interpretable without an unintended change of meaning.',
                  'Execution outcome is supported for each request; source-label disagreement is recorded separately.',
                  'All five payloads are mechanically identical except the planned attributed annotation.',
                  'For no candidate, inspect whether a valid deletion was overlooked.'],
        'outputs':['Raw accepted family count and variant count.',
                   'Case-level audit with evidence IDs, possible false accepts, possible false rejects, and uncertain cases.',
                   'Any disagreements kept separate from raw pipeline results; no tuning on the same ten before reporting.'],
        'limitations':'Assistant audit is not independent human gold; ten cases cannot establish general precision or recall.'})
    print(json.dumps({'selected':manifest['selected'],'cost_estimate_usd':expected,
                      'remaining_usd':client.accounting()['remaining_usd'],
                      'minimum_pair_reserve_usd':min(x['initial_pair_reserve_usd'] for x in costs),
                      'maximum_pair_reserve_usd':max(x['initial_pair_reserve_usd'] for x in costs),
                      'sum_initial_pair_reserves_usd':preflight['sum_initial_pair_upper_reserves_usd'],
                      'paid_calls':0},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
