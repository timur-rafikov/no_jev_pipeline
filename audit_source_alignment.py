"""Offline observation alignment audit, not a semantic filter or automatic relabeler.

Compare original tool observations with scorer replay observations only when the recorded
model-result sequence is identical. Different JSON formatting does not count as a difference.
The scorer often stops early: matching a prefix does NOT validate the complete gold label.
"""
from collections import Counter
import json
from pathlib import Path
from client import save
from prepare_data import MODELS
from build_dataset import read_jsonl

ROOT=Path(__file__).resolve().parent


def normalized_observation(value):
    if not isinstance(value,str):return value
    try:return json.loads(value)
    except (ValueError,TypeError):return value


def flatten(value):
    if isinstance(value,list):
        return [item for child in value for item in flatten(child)]
    return [value]


def compare(raw,score):
    if score is None:return {'status':'no_replay_record_for_benchmark_success','compared_observations':0}
    if raw['result']!=score.get('model_result_raw'):
        return {'status':'model_result_sequence_not_identical','compared_observations':0}
    replay=score.get('error',{}).get('execution_result')
    if not isinstance(replay,list):return {'status':'no_scorer_observations','compared_observations':0}
    turns=[]
    for turn in raw['inference_log']:
        if not isinstance(turn,dict) or 'begin_of_turn_query' not in turn:continue
        observations=[]
        for key,entries in turn.items():
            if not key.startswith('step_'):continue
            observations.extend(m.get('content') for m in entries if m.get('role')=='tool')
        turns.append(observations)
    mismatches=[];compared=0;length_differences=[]
    for turn_index,(original,graded) in enumerate(zip(turns,replay)):
        if not isinstance(graded,dict) or 'model' not in graded:continue
        rerun=flatten(graded['model'])
        if len(original)!=len(rerun):length_differences.append({'turn_index':turn_index,'original':len(original),'replay':len(rerun)})
        for observation_index,(a,b) in enumerate(zip(original,rerun)):
            compared+=1
            if normalized_observation(a)!=normalized_observation(b):
                mismatches.append({'turn_index':turn_index,'observation_index':observation_index,
                                   'original':a,'scorer_replay':b})
    return {'status':'different_observations' if mismatches else 'observed_prefix_matches' if compared else 'no_comparable_observations',
            'compared_observations':compared,'length_differences':length_differences,'mismatches':mismatches}


def main():
    rows=[]
    for model in MODELS:
        scores={r['id']:r for r in read_jsonl(ROOT/'raw'/(model+'_score.jsonl'))[1:]}
        for raw in read_jsonl(ROOT/'raw'/(model+'_result.jsonl')):
            rows.append({'source_id':model+'::'+raw['id'],'task_id':raw['id'],**compare(raw,scores.get(raw['id']))})
    summary={'executions':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
             'semantic_preselection':False,'paid_calls':0,'automatic_relabels':0,
             'interpretation':'An observed mismatch means the displayed trace and scorer replay differ, not proof that their binary outcomes differ. A matching prefix is not full label verification. Do not count absent success replay as verified alignment.',
             'rows':rows}
    save(ROOT/'SOURCE_ALIGNMENT_AUDIT.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},indent=2))


if __name__=='__main__':main()
