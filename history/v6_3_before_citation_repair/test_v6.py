"""Admission and cost regressions. These tests do not estimate LLM accuracy."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pipeline_v6 as p
import assemble_v6 as runner
from client import BudgetError
from budget_v6 import Client
import test_v5


class V6Tests(unittest.TestCase):
    def setUp(self):
        old = test_v5.V5Tests(); old.setUp()
        self.r, self.f = old.r, old.f
        self.v = old.audit(old.v)
        row = self.v['requests'][0]
        row.update(request_kind='action_or_state', execution_checks=[{
            'requirement_quote': 'Create ticket.', 'required_result': 'completed_effect',
            'observed_result': 'completed_effect',
            'evidence': [{'message_id':'m2','quote':'"status":"created"'}],
            'reason':'The created object is the requested ticket.'}])

    def decision(self, other=None):
        return p.decide(self.r, self.f, self.v, copy.deepcopy(self.v) if other is None else other)

    def test_only_two_independent_reviews_can_admit(self):
        self.assertEqual(p.decide(self.r,self.f,self.v)['status'],'awaiting_audit')
        self.assertEqual(self.decision()['status'],'accepted')

    def test_pending_purchase_cannot_be_success(self):
        self.v['requests'][0]['execution_checks'][0]['observed_result']='in_progress'
        d=self.decision()
        self.assertEqual(d['status'],'quarantined')
        self.assertIn('success_conflicts_with_required_completion:m1',d['reasons'])

    def test_submission_can_succeed_while_pending(self):
        check=self.v['requests'][0]['execution_checks'][0]
        check.update(required_result='submission',observed_result='in_progress')
        self.assertEqual(self.decision()['status'],'accepted')

    def test_open_created_ticket_is_not_globally_banned(self):
        self.r['messages'][2]['content']='{"id":12,"status":"Open"}'
        self.f=p.materialize(self.r,self.f['deletion'])
        row=self.v['requests'][0]
        for evidence in [row['evidence'],row['execution_checks'][0]['evidence']]:
            evidence[0]['quote']='"status":"Open"'
        self.assertEqual(self.decision()['status'],'accepted')

    def test_no_observation_must_not_support_success(self):
        check=self.v['requests'][0]['execution_checks'][0]
        check.update(observed_result='not_observed',evidence=[])
        self.assertEqual(self.decision()['status'],'quarantined')
        self.v['requests'][0].update(original='failure',base='failure')
        self.assertEqual(self.decision()['status'],'accepted')

    def test_action_must_have_completion_check(self):
        self.v['requests'][0]['execution_checks']=[]
        self.assertEqual(self.decision()['validation_error'],'action_goal_coverage_missing_or_inconsistent')

    def test_requirement_must_be_grounded_in_actual_user_turn(self):
        self.v['requests'][0]['execution_checks'][0]['requirement_quote']='Send email.'
        self.assertEqual(self.decision()['status'],'quarantined')

    def test_boundary_omissions_preserve_exact_grounding(self):
        self.assertEqual(p.normalized_quote('Could you find the price and fill it with content now?',
            'Could you find the price and fill it with content ...'),'Could you find the price and fill it with content')
        self.assertEqual(p.normalized_quote('Before. Create ticket. After.', '… Create ticket. ...'),'Create ticket.')
        for quote in ['...','... fabricated ...','provide an analysis ...']:
            with self.assertRaises(ValueError):p.normalized_quote('providing an analysis',quote)

    def test_grounded_failure_claim_does_not_automatically_veto_failure(self):
        row=self.v['requests'][0]
        row.update(original='failure',base='failure',unsupported_material_claims=['Contradicted answer.'])
        self.assertEqual(self.decision()['status'],'accepted')
        row.update(original='success',base='success')
        self.assertEqual(self.decision()['status'],'quarantined')

    def test_failure_claim_without_grounded_tool_evidence_is_held(self):
        row=self.v['requests'][0]
        row.update(original='failure',base='failure',unsupported_material_claims=['Unverifiable assertion.'],
            evidence=[{'message_id':'m1','quote':'Create ticket.'}])
        self.assertEqual(self.decision()['status'],'quarantined')

    def test_observation_evidence_must_be_actual_tool_result(self):
        check=self.v['requests'][0]['execution_checks'][0]
        check['evidence']=[]
        self.assertEqual(self.decision()['validation_error'],'claimed_observation_without_tool_evidence')
        check['evidence']=[{'message_id':'m3','quote':'Created the ticket.'}]
        self.assertEqual(self.decision()['status'],'quarantined')

    def test_success_answer_must_survive_deletion(self):
        row=self.v['requests'][0]
        row.update(delivery_requirement='required',answer_evidence=[{'message_id':'m3','quote':'Created the ticket.'}])
        self.assertEqual(self.decision()['validation_error'],'base_success_requires_retained_answer_evidence')
        row['answer_evidence']=[{'message_id':'m3','quote':'ID: 12'}]
        self.assertEqual(self.decision()['status'],'accepted')

    def test_original_answer_removed_is_assessable_but_not_admissible(self):
        row=self.v['requests'][0]
        row.update(original='success',base='failure',delivery_requirement='required',
            answer_evidence=[{'message_id':'m3','quote':'Created the ticket.'}])
        self.assertIn('outcome_changed',self.decision()['reasons'])
        row['answer_evidence']=[]
        self.assertEqual(self.decision()['validation_error'],'success_requires_delivered_answer_evidence')

    def test_information_only_requires_delivery(self):
        row=self.v['requests'][0]
        row.update(request_kind='information_only',execution_checks=[])
        self.assertEqual(self.decision()['validation_error'],'information_request_requires_delivery')

    def test_schema_roles_do_not_share_mutable_quote_objects(self):
        row=p.review_schema(self.r)['properties']['requests']['items']['properties']
        general=row['evidence']['items']['properties']['message_id']['enum']
        answer=row['answer_evidence']['items']['properties']['message_id']['enum']
        tools=row['execution_checks']['items']['properties']['evidence']['items']['properties']['message_id']['enum']
        self.assertEqual(general,['m0','m1','m2','m3'])
        self.assertEqual(answer,['m3']);self.assertEqual(tools,['m2'])
        answer.append('bad')
        self.assertNotIn('bad',general);self.assertNotIn('bad',tools)

    def test_schema_fixes_user_count_and_validator_checks_exact_coverage(self):
        array=p.review_schema(self.r)['properties']['requests']
        self.assertEqual(array['minItems'],1);self.assertEqual(array['maxItems'],1)
        self.v['requests']=[]
        self.assertEqual(self.decision()['validation_error'],'request_coverage')

    def test_reviews_are_blind_and_use_different_models(self):
        for audit in [False,True]:
            data=json.loads(p.review_payload(self.r,self.f,audit)['messages'][1]['content'])
            self.assertEqual(set(data['original']),{'messages','tools'})
            self.assertNotIn('reason',data['candidate']);self.assertNotIn('review',data)
        self.assertNotEqual(p.review_payload(self.r,self.f)['model'],p.review_payload(self.r,self.f,True)['model'])

    def test_disagreement_is_held_without_tiebreaker(self):
        other=copy.deepcopy(self.v);other['requests'][0].update(original='failure',base='failure')
        self.assertIn('independent_audit_disagreement',self.decision(other)['reasons'])

    def test_numeric_claim_and_five_conditions_are_preserved(self):
        self.r['messages'][-1]['content']='Created ticket 12. ID: 12'
        self.f=p.materialize(self.r,{'exact_text':'Created ticket 12. ','occurrence':0})
        self.assertEqual(self.decision()['status'],'accepted')
        self.assertEqual(len(self.f['variants']),5)
        self.assertEqual(len({p.digest(v['judge_payload']['trace']) for v in self.f['variants']}),1)

    def fake(self,replies):
        class Fake:
            n=0
            def request(self,*args):
                value=replies[self.n];self.n+=1
                if isinstance(value,BaseException):raise value
                return value,str(self.n)
        return Fake()

    def test_interrupted_audit_resumes_without_repeating_paid_stages(self):
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},self.v,KeyboardInterrupt()])
        with tempfile.TemporaryDirectory() as tmp:
            batch=Path(tmp)
            with self.assertRaises(KeyboardInterrupt):runner.run_record(self.r,c,batch)
            resumed=self.fake([self.v]);row=runner.run_record(self.r,resumed,batch)
            self.assertEqual(row['status'],'accepted');self.assertEqual(resumed.n,1)
            replay=self.fake([]);runner.run_record(self.r,replay,batch)
            self.assertEqual(replay.n,0)

    def test_budget_stop_saves_primary_and_never_admits_partial_family(self):
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},self.v,BudgetError('cap')])
        with tempfile.TemporaryDirectory() as tmp:
            row=runner.run_record(self.r,c,Path(tmp))
            self.assertEqual(row['status'],'budget_deferred')
            self.assertIn('review',row);self.assertNotIn('audit',row)

    def test_length_retry_requires_known_cost_and_actual_length_finish(self):
        payload=p.review_payload(self.r,self.f,True)
        with tempfile.TemporaryDirectory() as tmp:
            logs=Path(tmp)
            class Fake:
                def priced(self,payload):return payload,.01
            client=Fake();client.logs=logs;rid=p.digest(payload);path=logs/(rid+'.json')
            receipt={'request':payload,'status':'operational_error','actual_usd':None,
                'response':{'choices':[{'finish_reason':'length'}]}}
            path.write_text(json.dumps(receipt))
            self.assertIsNone(runner.known_length_receipt(client,payload))
            receipt['actual_usd']=.003;path.write_text(json.dumps(receipt))
            self.assertEqual(runner.known_length_receipt(client,payload),rid)
            receipt['response']['choices'][0]['finish_reason']='stop';path.write_text(json.dumps(receipt))
            self.assertIsNone(runner.known_length_receipt(client,payload))

    def test_length_retry_uses_saved_stages_and_preserves_old_charge(self):
        payload=p.review_payload(self.r,self.f,True)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);logs=root/'requests';logs.mkdir();rid=p.digest(payload)
            (logs/(rid+'.json')).write_text(json.dumps({'request':payload,'status':'operational_error',
                'actual_usd':.003,'response':{'choices':[{'finish_reason':'length'}]}}))
            client=self.fake([self.v]);client.logs=logs;client.priced=lambda payload:(payload,.01)
            row={'case_id':self.r['case_id'],'family':self.f}
            review,_=runner.request_audit(self.r,row,client,root/'result.json')
            self.assertEqual(client.n,1);self.assertEqual(review,self.v)
            self.assertIn(rid,row['superseded_request_ids'])
            self.assertEqual(runner.audit_payload(self.r,self.f,row)['max_tokens'],24576)
            self.assertTrue((logs/(rid+'.json')).exists())

    def test_second_length_failure_never_causes_third_attempt(self):
        client=self.fake([ValueError('incomplete_response_length')])
        row={'family':self.f,'audit_length_retry':{'original_request_id':'old'}}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):runner.request_audit(self.r,row,client,Path(tmp)/'result.json')
            self.assertEqual(client.n,1)

    def test_null_candidate_stops_after_one_call(self):
        c=self.fake([{'deletion':None,'reason':'No safe edit.'}])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(runner.run_record(self.r,c,Path(tmp))['status'],'rejected')
            self.assertEqual(c.n,1)

    def test_malformed_paid_review_is_retained_and_not_retried(self):
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},{}])
        with tempfile.TemporaryDirectory() as tmp:
            row=runner.run_record(self.r,c,Path(tmp))
            self.assertEqual(row['status'],'quarantined');self.assertEqual(row['review'],{})
            runner.run_record(self.r,self.fake([]),Path(tmp))

    def test_external_seen_tasks_are_excluded_but_unrun_plans_are_not(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(runner,'ROOT',Path(tmp)):
            (Path(tmp)/'external_seen_tasks_v6.json').write_text('["multi_turn_base_117"]')
            self.assertIn('multi_turn_base_117',runner.executed_tasks())
            self.assertNotIn('never_run',runner.executed_tasks())

    def test_session_cap_retains_all_old_unknown_reserves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'requests').mkdir()
            source=Path(__file__).resolve().parent
            for name in ['models_snapshot.json','models_snapshot_v6.json']:
                (root/name).write_bytes((source/name).read_bytes())
            (root/'requests/old_unknown.json').write_text('{"actual_usd":null,"reserve_usd":0.05}')
            (root/'requests/old_paid.json').write_text('{"actual_usd":0.07,"reserve_usd":0.08}')
            (root/'budget_session_v6.json').write_text(json.dumps({
                'additional_limit_usd':.2,'baseline_actual_usd':.07,'baseline_reserved_usd':.05,
                'effective_ledger_cap_usd':.32}))
            c=Client(root);a=c.accounting()
            self.assertAlmostEqual(a['unresolved_reserved_usd'],.05)
            self.assertAlmostEqual(a['remaining_usd'],.2)
            (root/'requests/new_unknown.json').write_text('{"actual_usd":null,"reserve_usd":0.01}')
            self.assertAlmostEqual(c.accounting()['remaining_usd'],.19)

    def test_budget_stops_before_opening_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'requests').mkdir()
            source=Path(__file__).resolve().parent
            for name in ['models_snapshot.json','models_snapshot_v6.json']:
                (root/name).write_bytes((source/name).read_bytes())
            (root/'budget_session_v6.json').write_text(json.dumps({
                'additional_limit_usd':.000001,'baseline_actual_usd':0,'baseline_reserved_usd':0,
                'effective_ledger_cap_usd':.000001}))
            c=Client(root)
            with patch('urllib.request.urlopen',side_effect=AssertionError('network_called')):
                with self.assertRaises(BudgetError):c.request(p.review_payload(self.r,self.f),{})
            self.assertEqual(list((root/'requests').glob('*.json')),[])


if __name__=='__main__':unittest.main()
