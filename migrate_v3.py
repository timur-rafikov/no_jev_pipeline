"""Re-evaluate recorded reviews without new model calls; preserve v2 history."""
import json
from pathlib import Path
from client import save
from pipeline import VERSION,decide,freeze

ROOT=Path(__file__).resolve().parent

def main():
    records={r['case_id']:r for r in map(json.loads,(ROOT/'selected_records.jsonl').read_text().splitlines())}
    previous=ROOT/'history/v2'
    assert (previous/'protocol_lock.json').exists(), 'Archive v2 before migrating.'
    lock=ROOT/'protocol_lock.json'
    if lock.exists() and json.loads(lock.read_text())['protocol']!=VERSION:
        assert lock.read_bytes()==(previous/'protocol_lock.json').read_bytes()
        lock.unlink()
    freeze(ROOT)
    changes=[]
    for path in sorted((previous/'results').glob('*.json')):
        row=json.loads(path.read_text());before={'status':row['status'],'reasons':row.get('reasons',[])}
        for attempt in row['attempts']:
            assert attempt['review'] is not None
            attempt['generation_protocol']='no-jev-edit-review-v2'
            attempt['review_protocol']='no-jev-edit-review-v2'
            attempt['decision']=decide(records[row['case_id']],attempt['family'],attempt['review'])
        if row['attempts']:row.update(row['attempts'][-1]['decision'])
        row['protocol']=VERSION
        row['validation_mode']='historical_review_replay' if row['attempts'] else 'not_processed'
        row.pop('review_reused_identical_prompts',None)
        save(ROOT/'results'/path.name,row)
        changes.append({'case':row['case_id'],'before':before,
                        'after':{'status':row['status'],'reasons':row.get('reasons',[])}})
    save(ROOT/'migration_v3.json',{
        'from':'no-jev-edit-review-v2','to':VERSION,'paid_calls':0,
        'prompt_changes':True,'historical_reviews_rerun_with_new_prompt':False,
        'changes':changes,
        'reason':'User requested semantic review instead of numeric/punctuation vetoes. '
                 'Original model verdicts and edits were preserved; only decision logic was replayed. '
                 'This replay is not a live validation of the new prompts.'})
    print(json.dumps(changes,ensure_ascii=False))

if __name__=='__main__':main()
