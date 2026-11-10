"""Real prior null regressions + corruption, interruption and split-leakage checks."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pipeline_v4 as p
import build_dataset as b
import test_pipeline


class V4Tests(unittest.TestCase):
    def setUp(self):
        f=test_pipeline.ProtocolTests();f.setUp()
        self.r=f.r;self.r.update(id='model::task',task_id='task',case_id='case',cohort='test')
        self.f=f.f
        self.v={'edit_verdict':'safe','edit_reason':'Only completion claim removed.',
            'edit_evidence_ids':['m3'],'requests':[{'user_id':'m1','criterion':'Create the ticket.',
            'original':'success','base':'success','reason':'Tool confirms created ID.',
            'evidence':[{'message_id':'m2','quote':'"status":"created"'}]}], 'suggested_deletion':None}

    def test_null_and_empty_edit_ids_are_a_normal_rejection(self):
        self.v.update(edit_verdict='unsafe',edit_reason='no candidate',edit_evidence_ids=[])
        result=p.decide(self.r,None,self.v)
        self.assertEqual(result['status'],'rejected')
        self.assertIn('no_candidate',result['reasons'])

    def test_actual_candidate_still_needs_edit_evidence(self):
        self.v['edit_evidence_ids']=[]
        with self.assertRaisesRegex(ValueError,'missing_edit_evidence'):
            p.decide(self.r,self.f,self.v)

    def test_fabricated_quote_cannot_be_accepted(self):
        self.v['requests'][0]['evidence'][0]['quote']='"status":"filled"'
        with self.assertRaisesRegex(ValueError,'evidence_quote_not_in_source'):
            p.decide(self.r,self.f,self.v)

    def test_numeric_claim_has_no_code_veto(self):
        self.r['messages'][-1]['content']='Ticket 12 was created.'
        family=p.materialize(self.r,{'exact_text':self.r['messages'][-1]['content'],'occurrence':0})
        self.assertEqual(p.decide(self.r,family,self.v)['status'],'accepted')

    def test_failure_does_not_hide_an_unknown_separate_request(self):
        self.r['source_gold']='failure'
        self.r['messages'].insert(3,{'id':'u2','role':'user','content':'Also email it.'})
        family=p.materialize(self.r,self.f['deletion'])
        self.v['requests'][0].update(original='failure',base='failure')
        self.v['requests'].append({**self.v['requests'][0],'user_id':'u2','original':'unknown','base':'unknown'})
        result=p.decide(self.r,family,self.v)
        self.assertEqual(result['status'],'quarantined')
        self.assertIn('outcome_unknown',result['reasons'])

    def test_known_gold_conflict_remains_quarantined(self):
        self.r['source_gold']='failure'
        self.assertIn('source_gold_disagreement',p.decide(self.r,self.f,self.v)['reasons'])

    def test_reviewer_cannot_see_gold_or_editor_rationale(self):
        payload=p.review_payload(self.r,self.f)
        data=json.loads(payload['messages'][1]['content'])
        self.assertNotIn('source_gold',data['original'])
        self.assertNotIn('reason',data['candidate'])

    def test_real_prior_null_reviews_no_longer_fail_on_empty_edit_evidence(self):
        root=Path(__file__).resolve().parent
        records={r['case_id']:r for r in b.read_jsonl(root/'batches/v3_new10_20261026/selected_records.jsonl')}
        tested=0
        for receipt in (root/'requests').glob('*.json'):
            item=json.loads(receipt.read_text());tag=item['tag']
            if tag.get('case') not in {'v3_new10_07','v3_new10_08','v3_new10_09'} or tag.get('stage')!='review' or item.get('parsed') is None:
                continue
            # This migration tests ONLY null structural handling, not a new semantic review.
            old=copy.deepcopy(item['parsed']);r=records[tag['case']]
            messages={m['id']:m for m in r['messages']}
            for request in old['requests']:
                request['criterion']='Legacy outcome retained for structural regression only.'
                ids=request.pop('evidence_ids')
                request['evidence']=[{'message_id':i,'quote':messages[i]['content'][:50]} for i in ids]
            self.assertEqual(p.decide(r,None,old)['status'],'rejected');tested+=1
        self.assertEqual(tested,3)

    def test_task_split_is_shared_across_models_and_conditions(self):
        groups={}
        for task in range(200):
            key=f'multi_turn_base_{task}'
            splits={b.task_split(key) for _model in range(3) for _condition in range(5)}
            self.assertEqual(len(splits),1);groups[key]=splits.pop()
        self.assertEqual(set(groups.values()),{'train','validation','test'})

    def fake_client(self,replies):
        class Fake:
            models={p.REVIEWER:{'pricing':{'prompt':'0.00000075'}}}
            n=0
            def accounting(self):return {'remaining_usd':1}
            def priced(self,payload):return payload,0.001
            def request(self,payload,tag):
                value=replies[self.n];self.n+=1
                if isinstance(value,BaseException):raise value
                return value,str(self.n)
        return Fake()

    def test_paid_outputs_survive_review_validation_error(self):
        bad=copy.deepcopy(self.v);bad['requests'][0]['evidence'][0]['quote']='not present'
        client=self.fake_client([{'deletion':self.f['deletion'],'reason':'claim'},bad])
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'pair_reserve',return_value=.01):
            result=b.run_record(self.r,client,Path(folder))
        self.assertEqual(result['status'],'operational_error')
        self.assertIn('review',result['attempts'][0]);self.assertIn('generation',result['attempts'][0])

    def test_interrupt_after_generation_resumes_only_review(self):
        client=self.fake_client([{'deletion':self.f['deletion'],'reason':'claim'},KeyboardInterrupt()])
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'pair_reserve',return_value=.01):
            batch=Path(folder)
            with self.assertRaises(KeyboardInterrupt):b.run_record(self.r,client,batch)
            second=self.fake_client([self.v])
            result=b.run_record(self.r,second,batch)
            self.assertEqual(second.n,1);self.assertEqual(result['status'],'accepted')
            third=self.fake_client([])
            b.run_record(self.r,third,batch);self.assertEqual(third.n,0)

    def test_repair_is_bounded_and_gets_a_fresh_review(self):
        bad=copy.deepcopy(self.v)
        bad.update(edit_verdict='unsafe',edit_reason='Requested ID removed.',suggested_deletion=self.f['deletion'])
        client=self.fake_client([
            {'deletion':{'exact_text':self.r['messages'][-1]['content'],'occurrence':0},'reason':'bad'},bad,
            {'deletion':self.f['deletion'],'reason':'fixed'},self.v])
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'pair_reserve',return_value=.01):
            result=b.run_record(self.r,client,Path(folder))
        self.assertEqual(client.n,4);self.assertEqual(result['status'],'accepted')

    def test_budget_deferral_never_calls_transport(self):
        client=self.fake_client([])
        with tempfile.TemporaryDirectory() as folder,patch.object(b,'pair_reserve',return_value=2):
            result=b.run_record(self.r,client,Path(folder))
        self.assertEqual(client.n,0);self.assertEqual(result['status'],'budget_deferred')


if __name__=='__main__':unittest.main()
