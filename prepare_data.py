"""Normalize pinned public BFCL executions and freeze selection before paid calls."""
import hashlib
import json
from pathlib import Path
from pipeline import canonical,digest,source_check
ROOT=Path(__file__).resolve().parent
MODELS=['Qwen_Qwen3-235B-A22B-Instruct-2507','DeepSeek-V3.2-Exp','gpt-4.1-2025-04-14']

def normalize(row,model,gold):
    messages=[]
    for turn in row['inference_log']:
        if not isinstance(turn,dict):continue # simulator state, not model-visible content
        for key,entries in turn.items():
            if key!='begin_of_turn_query' and not key.startswith('step_'):continue
            for item in entries:
                if item.get('role') not in ('system','developer','user','assistant','tool'):continue
                # Canonical message IDs; preserve all model-visible fields verbatim.
                messages.append({'id':f'm{len(messages):04d}',**item})
    return {'id':model+'::'+row['id'],'task_id':row['id'],'model':model,
            'messages':messages,'tools':[],'source_gold':gold,
            'raw_result_sha256':digest(row),'normalization':'all model-visible roles in log order; no simulator state/handler diagnostics'}

def main():
    records=[];issues=[];raw_rows={};summaries=[]
    for model in MODELS:
        data=[json.loads(l) for l in (ROOT/'raw'/(model+'_result.jsonl')).read_text().splitlines()]
        scores=[json.loads(l) for l in (ROOT/'raw'/(model+'_score.jsonl')).read_text().splitlines()]
        failed={s['id']:s for s in scores[1:]}
        assert len(data)==scores[0]['total_count']==200
        assert all(s.get('valid') is False for s in failed.values())
        assert len(data)-len(failed)==scores[0]['correct_count']
        assert set(failed)<={r['id'] for r in data}
        summaries.append({'model':model,**scores[0],'failed_records':len(failed)})
        for row in data:
            r=normalize(row,model,'failure' if row['id'] in failed else 'success')
            raw_rows[r['id']]={'result':row,'score':failed.get(row['id']),'score_header':scores[0]}
            try:source_check(r)
            except ValueError as e:issues.append({'id':r['id'],'reason':str(e)});continue
            records.append(r)
    regression_ids=[MODELS[0]+'::multi_turn_base_27',MODELS[1]+'::multi_turn_base_41',
                    MODELS[0]+'::multi_turn_base_46',MODELS[2]+'::multi_turn_base_82']
    selected=[]
    for i,rid in enumerate(regression_ids):
        r=next(r for r in records if r['id']==rid)
        selected.append({**r,'case_id':f'regression_{i+1}','cohort':'task_regression_different_snapshot'})
    excluded={'multi_turn_base_'+str(n) for n in [27,41,46,82,122,163,158,194,179,197,99,15]}
    # No semantic/claim wording filter, no gold-based sampling. Size is a cost/context restriction.
    pool=[r for r in records if r['task_id'] not in excluded and len(canonical(r['messages']).encode())<=36000]
    pool.sort(key=lambda r:hashlib.sha256(('no-jev-20261026-v1|'+r['id']).encode()).hexdigest())
    seen=set(excluded)
    for r in pool:
        if r['task_id'] in seen:continue
        selected.append({**r,'case_id':f'fresh_{len(selected)-3}','cohort':'hash_sample_new_to_current_pilot'})
        seen.add(r['task_id'])
        if len(selected)==8:break
    assert len(selected)==8
    (ROOT/'selected_records.jsonl').write_text(''.join(canonical(r)+'\n' for r in selected))
    (ROOT/'selected_raw.jsonl').write_text(''.join(canonical({'id':r['id'],**raw_rows[r['id']]})+'\n' for r in selected))
    manifest={'source_repository':'HuanzhiMao/BFCL-Result','commit':json.loads((ROOT/'source_commit.json').read_text())['sha'],
              'release':'2025-11-03','pool_executions':600,'structural_eligible':len(records),'size_eligible_after_task_exclusions':len(pool),
              'selection':'4 prior task IDs (different public executions) + first 4 distinct tasks ordered by sha256(seed|id), <=36000 message bytes',
              'seed':'no-jev-20261026-v1','no_lexical_or_semantic_screen':True,'gold_used_for_selection':False,
              'prior_archives_missing':True,'exact_old_execution_equivalence':False,
              'score_headers':summaries,'local_ineligible':issues,
              'selected':[{'id':r['id'],'case_id':r['case_id'],'cohort':r['cohort'],'source_hash':digest(r),
                           'bytes':len(canonical(r['messages']).encode())} for r in selected]}
    (ROOT/'selection_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('local_ineligible','score_headers')},indent=2))

if __name__=='__main__':main()
