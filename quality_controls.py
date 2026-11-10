"""Small controlled fixtures, reported separately from real BFCL yield."""
import argparse
import json
import fcntl
from pathlib import Path
from client import Client,BudgetError,save
from pipeline import materialize,review_payload,decide,freeze,VERSION
ROOT=Path(__file__).resolve().parent

def fixtures():
    system='Tools: create_ticket(title) creates a ticket and returns id/status. delete_message(id) returns deleted=true only after deletion. Tool results are authoritative execution evidence.'
    def source(name,user,call,result,final,gold='success'):
        return {'id':name,'source_gold':gold,'tools':[],'messages':[
            {'id':'m0','role':'system','content':system},{'id':'m1','role':'user','content':user},
            {'id':'m2','role':'assistant','content':call},{'id':'m3','role':'tool','content':result},
            {'id':'m4','role':'assistant','content':final}]}
    ticket=source('control_ticket','Create a ticket called Help and tell me its ID.',
                  'create_ticket(title="Help")','{"id":"T42","status":"created"}',
                  'The ticket was successfully created. Ticket ID: T42. I will check its progress tomorrow.')
    message=source('control_message','Delete my message to Bob with id M7.',
                  'delete_message(id="M7")','{"id":"M7","deleted":true}',
                  'The message to Bob has been successfully deleted.')
    failure=source('control_failure','Delete message M7.',
                  'delete_message(id="M7")','{"error":"permission_denied"}',
                  'I could not delete message M7 because permission was denied.','failure')
    return [
        {'name':'safe_specific_action','record':message,'delete':message['messages'][-1]['content'],'expected_edit':'safe'},
        {'name':'safe_header_preserves_answer','record':ticket,'delete':'The ticket was successfully created. ','expected_edit':'safe'},
        {'name':'unsafe_requested_id_removed','record':ticket,'delete':'The ticket was successfully created. Ticket ID: T42. ','expected_edit':'unsafe'},
        {'name':'unsafe_adverb_only','record':ticket,'delete':'successfully ','expected_edit':'unsafe'},
        {'name':'unsafe_future_promise','record':ticket,'delete':'I will check its progress tomorrow.','expected_edit':'unsafe'},
        {'name':'unsafe_error_disclosure','record':failure,'delete':failure['messages'][-1]['content'],'expected_edit':'unsafe'}]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    cases=fixtures();dest=ROOT/'controls'/VERSION;dest.mkdir(parents=True,exist_ok=True)
    fixture_path=ROOT/'quality_control_fixtures.json'
    if not fixture_path.exists():save(fixture_path,cases)
    else:assert json.loads(fixture_path.read_text())==cases
    if not args.run:print(json.dumps({'controls':len(cases),'paid_calls':False}));return
    client=Client();freeze(ROOT)
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for case in cases:
            path=dest/(case['name']+'.json')
            if path.exists():continue
            family=materialize(case['record'],{'exact_text':case['delete'],'occurrence':0})
            try:
                review,h=client.request(review_payload(case['record'],family),{'stage':'semantic_control','name':case['name'],'protocol':VERSION})
                decision=decide(case['record'],family,review)
                result={'name':case['name'],'protocol':VERSION,'expected_edit':case['expected_edit'],'actual_edit':review['edit_verdict'],
                        'passed':review['edit_verdict']==case['expected_edit'],'review':review,'decision':decision,'request_hash':h}
            except BudgetError:
                print(json.dumps({'name':case['name'],'budget_deferred':True}));break
            except Exception as e:
                result={'name':case['name'],'operational_error':type(e).__name__,'passed':False}
            save(path,result)
            print(json.dumps({k:v for k,v in result.items() if k not in ('review','decision')},ensure_ascii=False),flush=True)
    rows=[json.loads(p.read_text()) for p in dest.glob('*.json')]
    save(ROOT/('CONTROL_SUMMARY_'+VERSION+'.json'),{'type':'synthetic controlled fixtures, not real-data yield or human-gold accuracy',
                                    'completed':len(rows),'passed':sum(r['passed'] for r in rows),'accounting':client.accounting()})

if __name__=='__main__':main()
