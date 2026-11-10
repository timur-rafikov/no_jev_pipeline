"""Budget, replay and bounded-repair tests using fake transport only."""
import io
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import client
import runner
from pipeline import GENERATOR,REVIEWER,generation_payload
import test_pipeline

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root=Path(self.temp.name)
        models={'data':[{'id':m,'pricing':{'prompt':'0.00000075','completion':'0.0000045'}} for m in [GENERATOR,REVIEWER]]}
        (self.root/'models_snapshot.json').write_text(json.dumps(models))
        fixture=test_pipeline.ProtocolTests();fixture.setUp();self.record=fixture.r
        self.record.update({'case_id':'unit','id':'unit','cohort':'unit'})
        self.review=fixture.v
    def tearDown(self):self.temp.cleanup()
    def test_replay_does_not_double_bill(self):
        c=client.Client(self.root)
        body={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'cost':0.001}}
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-value'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(body).encode())) as network:
            a=c.request(generation_payload(self.record),{'stage':'test'})
            b=c.request(generation_payload(self.record),{'stage':'test'})
        self.assertEqual(a,b);self.assertEqual(network.call_count,1)
        self.assertEqual(c.accounting()['actual_usd'],0.001)
    def test_timeout_keeps_reserve_and_is_not_retried(self):
        c=client.Client(self.root)
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-value'}),patch('urllib.request.urlopen',side_effect=TimeoutError) as network:
            with self.assertRaises(TimeoutError):c.request(generation_payload(self.record),{})
            with self.assertRaises(client.UnresolvedRequest):c.request(generation_payload(self.record),{})
        self.assertEqual(network.call_count,1);self.assertGreater(c.accounting()['unresolved_reserved_usd'],0)
    def test_budget_block_happens_before_network(self):
        c=client.Client(self.root)
        with patch.object(client,'BUDGET',0),patch('urllib.request.urlopen') as network:
            with self.assertRaises(client.BudgetError):c.request(generation_payload(self.record),{})
        network.assert_not_called();self.assertEqual(c.accounting()['attempts'],0)
    def test_explicit_recovery_preserves_unknown_charge_and_is_cached(self):
        c=client.Client(self.root);p=generation_payload(self.record)
        body={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'cost':0.001}}
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-value'}),patch('urllib.request.urlopen',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):c.request(p,{})
        held=c.accounting()['unresolved_reserved_usd']
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'test-value'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(body).encode())) as net:
            result=c.request(p,{},recovery_reason='Explicit test recovery, retaining original reserve.')
            self.assertEqual(result,c.request(p,{}))
        self.assertEqual(net.call_count,1)
        self.assertEqual(c.accounting()['actual_usd'],0.001)
        self.assertEqual(c.accounting()['unresolved_reserved_usd'],held)
        self.assertEqual(c.accounting()['attempts'],2)
    def test_only_reviewer_rejects_numeric_edit_and_repair_is_reviewed(self):
        self.record['messages'][-1]['content']='Created the ticket. ID: 12'
        reviewer=self.review
        rejected=copy.deepcopy(reviewer)
        rejected.update(edit_verdict='unsafe',edit_reason='The requested ID was removed.',
                        suggested_deletion={'exact_text':'Created the ticket. ','occurrence':0})
        class FakeClient:
            models={REVIEWER:{'pricing':{'prompt':'0.00000075'}}}
            n=0
            stages=[]
            def accounting(self):return {'remaining_usd':1}
            def priced(self,p):return p,0.001
            def request(self,p,tag):
                self.n+=1
                self.stages.append(tag['stage'])
                replies=[{'deletion':{'exact_text':'Created the ticket. ID: 12','occurrence':0},'reason':'bad'},
                         rejected,
                         {'deletion':{'exact_text':'Created the ticket. ','occurrence':0},'reason':'fixed'},reviewer]
                return replies[self.n-1],str(self.n)
        fake=FakeClient()
        with patch.object(runner,'ROOT',self.root):row=runner.run_record(self.record,fake)
        self.assertEqual(fake.n,4);self.assertEqual(row['status'],'accepted')
        self.assertEqual(fake.stages,['generation','review','generation','review'])
        self.assertEqual(row['attempts'][0]['decision']['reasons'],['edit_unsafe'])
        self.assertIsNotNone(row['attempts'][1]['review'])
        self.assertEqual(row['attempts'][1]['family']['base']['messages'][-1]['content'],'ID: 12')

if __name__=='__main__':unittest.main()
