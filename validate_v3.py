"""Focused semantic boundary checks. Synthetic fixtures, not real-data yield."""
import argparse
import fcntl
import json
from pathlib import Path
from client import Client,BudgetError,save
from pipeline import VERSION,materialize,review_payload,decide,freeze

ROOT=Path(__file__).resolve().parent

def fixtures():
    system=('Tools: word_count(file) returns the file word count. '
            'write_text(file, content) writes exactly that content and returns written=true on success. '
            'The recorded tool outputs describe actual execution.')
    def record(name,rows,gold='success'):
        messages=[('system',system)]+rows
        return {'id':name,'source_gold':gold,'tools':[],
                'messages':[{'id':f'm{i:02d}','role':role,'content':text}
                            for i,(role,text) in enumerate(messages)]}
    positive=record('numeric_completion',[
        ('user','How many words are in memo.txt?'),
        ('assistant','word_count(file="memo.txt")'),('tool','{"word_count":7}'),
        ('assistant','memo.txt contains 7 words.'),
        ('user','Save that word count in count.txt.'),
        ('assistant','write_text(file="count.txt", content="7")'),('tool','{"written":true}'),
        ('assistant','The word count (7) has been saved in count.txt. Let me know if you need anything else.')])
    answer=record('numeric_answer',[
        ('user','How many words are in memo.txt?'),
        ('assistant','word_count(file="memo.txt")'),('tool','{"word_count":7}'),
        ('assistant','memo.txt contains 7 words.')])
    error=record('numeric_error',[
        ('user','Save exactly 70 in count.txt.'),
        ('assistant','write_text(file="count.txt", content="7")'),('tool','{"written":true}'),
        ('assistant','I saved 7 instead of the requested 70 in count.txt. Please check the file.')],gold='failure')
    return [
        {'name':'number_in_redundant_completion','record':positive,
         'delete':'The word count (7) has been saved in count.txt. ','expected_edit':'safe'},
        {'name':'number_is_requested_answer','record':answer,
         'delete':'memo.txt contains 7 words.','expected_edit':'unsafe'},
        {'name':'number_in_error_disclosure','record':error,
         'delete':'I saved 7 instead of the requested 70 in count.txt. ','expected_edit':'unsafe'}]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    cases=fixtures();dest=ROOT/'controls_v3';dest.mkdir(exist_ok=True)
    fixture_path=ROOT/'semantic_fixtures_v3.json'
    if fixture_path.exists():assert json.loads(fixture_path.read_text())==cases
    else:save(fixture_path,cases)
    client=Client()
    if not args.run:
        print(json.dumps({'controls':len(cases),'paid_calls':False,'accounting':client.accounting()}));return
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);freeze(ROOT)
        for case in cases:
            path=dest/(case['name']+'.json')
            if path.exists():continue
            family=materialize(case['record'],{'exact_text':case['delete'],'occurrence':0})
            try:
                review,h=client.request(review_payload(case['record'],family),
                                         {'stage':'semantic_control','protocol':VERSION,'name':case['name']})
            except BudgetError:
                print(json.dumps({'case':case['name'],'budget_deferred':True}),flush=True);break
            decision=decide(case['record'],family,review)
            result={'name':case['name'],'protocol':VERSION,'expected_edit':case['expected_edit'],
                    'actual_edit':review['edit_verdict'],'passed':review['edit_verdict']==case['expected_edit'],
                    'review':review,'decision':decision,'request_hash':h}
            save(path,result)
            print(json.dumps({'name':case['name'],'verdict':review['edit_verdict'],
                              'passed':result['passed'],'reason':review['edit_reason'],
                              'accounting':client.accounting()},ensure_ascii=False),flush=True)
    rows=[json.loads(p.read_text()) for p in dest.glob('*.json')]
    save(ROOT/'CONTROL_SUMMARY_V3.json',{'protocol':VERSION,'type':'synthetic boundary checks',
                                       'completed':len(rows),'passed':sum(r['passed'] for r in rows),
                                       'accounting':client.accounting()})

if __name__=='__main__':main()
