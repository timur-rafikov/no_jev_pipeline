"""Meaningful admission, evidence, pairing, budget and interrupted-run regressions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pipeline_v5 as p
import assemble as b
import test_v4
from client import BudgetError


class V5Tests(unittest.TestCase):
    def setUp(self):
        f = test_v4.V4Tests(); f.setUp()
        self.r, self.f, self.v = f.r, f.f, f.v
        for row in self.v['requests']:
            row.update(state_check='Correct ticket created.', delivery_check='Creation only requested.', unsupported_material_claims=[])

    def audit(self, review):
        a=copy.deepcopy(review)
        a["requests"]=[{**r,"delivery_requirement":"not_requested","answer_evidence":[]} for r in review["requests"]]
        return a

    def fake(self, replies):
        class Client:
            n = 0
            def request(self, payload, tag):
                value = replies[self.n]; self.n += 1
                if isinstance(value, BaseException): raise value
                return value, str(self.n)
        return Client()

    def test_single_review_cannot_admit(self):
        self.assertEqual(p.decide(self.r, self.f, self.v)['status'], 'awaiting_audit')

    def test_two_independent_agreeing_reviews_admit(self):
        self.assertEqual(p.decide(self.r, self.f, self.v, self.audit(self.v))['status'], 'accepted')

    def test_same_overall_label_but_per_turn_disagreement_quarantines(self):
        self.r['source_gold'] = 'failure'
        self.r['messages'].insert(-1, {'id':'u2','role':'user','content':'Also send it.'})
        self.f = p.materialize(self.r, self.f['deletion'])
        self.v['requests'][0].update(original='failure', base='failure')
        self.v['requests'].append({**self.v['requests'][0], 'user_id':'u2'})
        other = copy.deepcopy(self.v)
        other['requests'][1].update(original='success',base='success')
        self.assertEqual(p.decide(self.r,self.f,self.v,self.audit(other))['status'],'quarantined')

    def test_unsafe_audit_cannot_admit(self):
        other = copy.deepcopy(self.v); other['edit_verdict'] = 'unsafe'
        self.assertEqual(p.decide(self.r,self.f,self.v,self.audit(other))['status'],'quarantined')

    def test_material_unverified_fact_holds_even_with_success_labels(self):
        self.v['requests'][0]['unsupported_material_claims'] = ['Airport-name expansion lacks supporting evidence.']
        self.assertEqual(p.decide(self.r,self.f,self.v,self.audit(self.v))['status'],'quarantined')

    def test_source_grade_preserved_separately_from_consensus_label(self):
        self.r['source_gold'] = 'failure'
        decision=p.decide(self.r,self.f,self.v,self.audit(self.v))
        self.assertEqual(decision['status'],'accepted')
        self.assertEqual(decision['benchmark_relation'],'disagrees')
        self.assertEqual(self.r['source_gold'],'failure')

    def test_blind_audit_has_no_primary_review_or_gold(self):
        data = json.loads(p.review_payload(self.r,self.f,True)['messages'][1]['content'])
        self.assertEqual(set(data), {'original','candidate','base_rule','execution_index','index_note','required_user_ids'})
        self.assertEqual(set(data['original']), {'messages','tools'})
        self.assertNotIn('reason',data['candidate'])
        self.assertNotEqual(p.review_payload(self.r,self.f)['model'],p.review_payload(self.r,self.f,True)['model'])

    def test_index_pairs_multiple_ordered_calls_and_marks_missing(self):
        ms=[{'id':'u','role':'user','content':'Run'},
            {'id':'a','role':'assistant','content':'[cd(folder="x"), ls()]'},
            {'id':'t1','role':'tool','content':'None'}, {'id':'t2','role':'tool','content':'[]'},
            {'id':'a2','role':'assistant','content':'[cat(file_name="x")]'}]
        index=p.execution_index(ms)
        self.assertEqual(index[0]['links'][1],{'call_index':1,'tool_message_id':'t2'})
        self.assertEqual(index[1]['mapping'],'no_observation')

    def test_index_never_guesses_one_to_one_with_count_mismatch(self):
        ms=[{'id':'a','role':'assistant','content':'[foo(), bar()]'},
            {'id':'t','role':'tool','content':'[]'}]
        self.assertEqual(p.execution_index(ms)[0]['mapping'],'group_only_ambiguous')
        self.assertEqual(p.execution_index(ms)[0]['links'],[])

    def test_index_prefers_explicit_ids_over_order(self):
        ms=[{'id':'a','role':'assistant','tool_calls':[{'id':'x','function':{'name':'x'}},{'id':'y','function':{'name':'y'}}]},
            {'id':'t1','role':'tool','tool_call_id':'y','content':'ok'},
            {'id':'t2','role':'tool','tool_call_id':'x','content':'ok'}]
        self.assertEqual(p.execution_index(ms)[0]['links'][0]['call_index'],1)

    def test_parser_does_not_execute_recorded_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'never'
            p.parsed_calls({'content':f'__import__("pathlib").Path({str(path)!r}).touch()'})
            self.assertFalse(path.exists())

    def test_null_costs_only_generator_and_resumes_without_calls(self):
        c=self.fake([{'deletion':None,'reason':'No completion claim.'}])
        with tempfile.TemporaryDirectory() as tmp:
            batch=Path(tmp);r=b.run_record(self.r,c,batch)
            self.assertEqual(r['status'],'rejected'); self.assertEqual(c.n,1)
            b.run_record(self.r,self.fake([]),batch)

    def test_interrupt_after_primary_resumes_only_audit(self):
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},self.v,KeyboardInterrupt()])
        with tempfile.TemporaryDirectory() as tmp:
            batch=Path(tmp)
            with self.assertRaises(KeyboardInterrupt): b.run_record(self.r,c,batch)
            resumed=self.fake([self.audit(self.v)]);row=b.run_record(self.r,resumed,batch)
            self.assertEqual(resumed.n,1);self.assertEqual(row['status'],'accepted')
            b.run_record(self.r,self.fake([]),batch)

    def test_budget_deferral_after_primary_cannot_export_accepted(self):
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},self.v,BudgetError('cap')])
        with tempfile.TemporaryDirectory() as tmp:
            row=b.run_record(self.r,c,Path(tmp))
            self.assertEqual(row['status'],'budget_deferred')
            self.assertNotIn('audit',row)

    def test_invalid_paid_review_persists_without_auto_retry(self):
        bad=copy.deepcopy(self.v);bad['requests'][0]['tool_evidence'][0]['quote']='fabricated evidence'
        c=self.fake([{'deletion':self.f['deletion'],'reason':'claim'},bad])
        with tempfile.TemporaryDirectory() as tmp:
            row=b.run_record(self.r,c,Path(tmp))
            self.assertEqual(row['status'],'quarantined')
            self.assertIn('invalid_primary_review',row['decision']['reasons'])
            self.assertEqual(row['review'],bad)
            b.run_record(self.r,self.fake([]),Path(tmp))

    def test_five_variants_still_share_base_and_keep_numbers(self):
        self.r['messages'][-1]['content']='Created ticket 12. ID: 12'
        family=p.materialize(self.r,{'exact_text':'Created ticket 12. ','occurrence':0})
        p.mechanical_check(self.r,family)
        self.assertEqual({v['judge_payload']['trace']['messages'][-1]['content'] for v in family['variants']},{'ID: 12'})
        self.assertEqual(len(family['variants']),5)

    def test_planned_pool_is_not_marked_as_already_executed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b,'ROOT',Path(tmp)):
            folder=Path(tmp)/'batches/full_plan';folder.mkdir(parents=True)
            (folder/'selected_records.jsonl').write_text(json.dumps({'task_id':'never_run','case_id':'case'})+'\n')
            self.assertNotIn('never_run',b.executed_tasks())

    def test_session_budget_preserves_old_unknown_charge(self):
        from budget_v5 import Client
        from client import Client as Base
        root=Path(__file__).resolve().parent
        current,old=Client(root).accounting(),Base(root).accounting()
        self.assertEqual(current['unresolved_reserved_usd'],old['unresolved_reserved_usd'])
        self.assertLessEqual(current['remaining_usd'],old['remaining_usd'])
        self.assertEqual(current['session_limit_usd'],1)


class ContractTests(unittest.TestCase):
    def setUp(self):
        f=V5Tests();f.setUp();self.f=f

    def test_external_quote_marks_are_only_typography(self):
        self.assertEqual(p.normalized_quote('Send the invoice.', '\"Send the invoice.\"'),'Send the invoice.')
        with self.assertRaises(ValueError):p.normalized_quote('Send the invoice.', '\"Send the refund.\"')

    def test_auditor_schema_requires_every_user_id(self):
        f=self.f;a=f.audit(f.v);a['requests']={}
        result=p.decide(f.r,f.f,f.v,a)
        self.assertEqual(result['reasons'],['invalid_independent_audit'])

    def test_internal_tool_result_is_not_delivered_answer(self):
        f=self.f;a=f.audit(f.v);row=a['requests'][0]
        row['delivery_requirement']='required'
        row['answer_evidence']=[{'message_id':'m2','quote':'"status":"created"'}]
        result=p.decide(f.r,f.f,f.v,a)
        self.assertEqual(result['reasons'],['invalid_independent_audit'])

    def test_required_success_needs_actual_answer_evidence(self):
        f=self.f;a=f.audit(f.v);a['requests'][0]['delivery_requirement']='required'
        result=p.decide(f.r,f.f,f.v,a)
        self.assertEqual(result['validation_error'],'success_requires_delivered_answer_evidence')

if __name__=='__main__':unittest.main()
