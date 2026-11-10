"""Offline corruption and decision-consistency tests; not LLM accuracy estimates."""
import copy
import unittest
from pipeline import *

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.r={'messages':[{'id':'m0','role':'system','content':'tool definition'},
               {'id':'m1','role':'user','content':'Create ticket.'},
               {'id':'m2','role':'tool','content':'{"id":12,"status":"created"}'},
               {'id':'m3','role':'assistant','content':'Created the ticket. ID: 12'}],
               'tools':[],'source_gold':'success'}
        self.f=materialize(self.r,{'exact_text':'Created the ticket. ','occurrence':0})
        self.v={'edit_verdict':'safe','edit_reason':'only completion header removed',
                'edit_evidence_ids':['m3'],'requests':[{'user_id':'m1','original':'success','base':'success',
                'evidence_ids':['m2'],'reason':'creation evidenced'}],'suggested_deletion':None}
    def test_exact_deletion_and_five_shared_bases(self):
        self.assertTrue(mechanical_check(self.r,self.f));self.assertEqual(len(self.f['variants']),5)
        self.assertEqual(self.f['base']['messages'][-1]['content'],'ID: 12')
        self.assertEqual(len({digest(v['judge_payload']['trace']) for v in self.f['variants']}),1)
    def test_tool_result_tamper(self):
        f=copy.deepcopy(self.f);f['base']['messages'][2]['content']='invented success'
        with self.assertRaises(ValueError):mechanical_check(self.r,f)
    def test_one_variant_drift(self):
        f=copy.deepcopy(self.f);f['variants'][2]['judge_payload']['trace']['messages'][1]['content']='different task'
        with self.assertRaises(ValueError):mechanical_check(self.r,f)
    def test_annotation_role_or_wording_drift(self):
        for key,value in [('speaker','system'),('quoted_statement','Definitely succeeded!')]:
            f=copy.deepcopy(self.f);f['variants'][1]['judge_payload']['status_annotation'][key]=value
            with self.assertRaises(ValueError):mechanical_check(self.r,f)
    def test_only_actual_patch_allowed(self):
        with self.assertRaises(ValueError):materialize(self.r,{'exact_text':'invented sentence','occurrence':0})
    def test_missing_request_or_fabricated_evidence(self):
        for change in ('coverage','evidence'):
            v=copy.deepcopy(self.v)
            if change=='coverage':v['requests']=[]
            else:v['requests'][0]['evidence_ids']=['not_in_source']
            with self.assertRaises(ValueError):decide(self.r,self.f,v)
    def test_accept_and_gold_mismatch_quarantine(self):
        self.assertEqual(decide(self.r,self.f,self.v)['status'],'accepted')
        self.r['source_gold']='failure'
        self.assertEqual(decide(self.r,self.f,self.v)['status'],'quarantined')
    def test_unknown_and_outcome_change_not_accepted(self):
        for result in ('unknown','failure'):
            v=copy.deepcopy(self.v);v['requests'][0]['base']=result
            self.assertNotEqual(decide(self.r,self.f,v)['status'],'accepted')
    def test_no_redundant_existence_flag(self):
        v=copy.deepcopy(self.v);v['source_has_safe_deletion']=False
        with self.assertRaises(ValueError):decide(self.r,self.f,v)
    def test_gold_and_reason_blind_review(self):
        prompt=canonical(review_payload(self.r,self.f))
        self.assertNotIn('source_gold',prompt);self.assertNotIn('generation_reason',prompt)
    def test_null_candidate_never_accepted(self):
        self.assertNotEqual(decide(self.r,None,self.v)['status'],'accepted')
    def test_aggregate_failure_survives_later_success(self):
        self.assertEqual(aggregate(['failure','success']),'failure')
        self.assertEqual(aggregate(['unknown','success']),'unknown')
    def test_numeric_payload_guard_overrides_optimistic_review(self):
        self.r['messages'][-1]['content']='The word count (9) was saved. Anything else?'
        f=materialize(self.r,{'exact_text':'The word count (9) was saved. ','occurrence':0})
        self.assertIn('protected_numeric_literal_removed',decide(self.r,f,self.v)['reasons'])
        self.assertNotEqual(decide(self.r,f,self.v)['status'],'accepted')
    def test_broken_splice_guard(self):
        self.r['messages'][-1]['content']='The engine is running, and all preparations are complete. No more calls.'
        f=materialize(self.r,{'exact_text':'and all preparations are complete. ','occurrence':0})
        self.assertIn('dangling_punctuation_after_deletion',local_edit_errors(self.r,f))
    def test_object_name_with_digits_not_a_standalone_value(self):
        self.r['messages'][-1]['content']='Message M7 was deleted.'
        f=materialize(self.r,{'exact_text':self.r['messages'][-1]['content'],'occurrence':0})
        self.assertEqual(local_edit_errors(self.r,f),[])

if __name__=='__main__':unittest.main()
