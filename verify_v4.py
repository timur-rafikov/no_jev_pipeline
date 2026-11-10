"""Offline receipt/source/decision verification. Makes no paid API calls."""
import json
from pathlib import Path
from client import Client,save
import build_dataset as b
import pipeline_v4 as p

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v4_holdout8_20261027'


def main():
    manifest,records=b.load_batch(BATCH)
    raw_pool={r['id']:r for r in b.source_pool()}
    c=Client(ROOT);receipts=[];candidate_count=0
    for record in records:
        expected={**raw_pool[record['id']],'case_id':record['case_id'],'cohort':record['cohort']}
        assert record==expected,'raw normalization mismatch'
        row=json.loads((BATCH/'results'/(record['case_id']+'.json')).read_text())
        feedback=None
        for entry in row['attempts']:
            for kind,body in [('generation',p.generation_payload(record,feedback)),
                              ('review',p.review_payload(record,entry['family']))]:
                rid=entry[kind+'_request'];receipt=json.loads((ROOT/'requests'/(rid+'.json')).read_text())
                assert p.digest(receipt['request'])==receipt['request_hash']
                assert receipt['request']==c.priced(body)[0],kind+' payload differs'
                assert receipt['parsed']==entry[kind],kind+' output differs'
                receipts.append(rid)
            assert p.decide(record,entry['family'],entry['review'])==entry['decision']
            if entry['family'] is not None:p.mechanical_check(record,entry['family'])
            feedback={'problem':entry['review']['edit_reason'],'previous_deletion':entry['generation']['deletion'],
                      'suggested_deletion':entry['review']['suggested_deletion'],
                      'instruction':'Propose one corrected edit; all original constraints still apply.'}
        if row['attempts'][-1]['family'] is not None:candidate_count+=1
        assert row['status']==row['attempts'][-1]['decision']['status']
    before=c.accounting()
    # Exercise real CLI runner logic: every completed result must resume without transport.
    class NoTransport(Client):
        def request(self,*args,**kwargs):raise AssertionError('completed replay tried to call API')
    replay=NoTransport(ROOT)
    for record in records:b.run_record(record,replay,BATCH)
    assert c.accounting()==before
    summary=b.export(BATCH)
    assert len(set(receipts))==16
    assert summary['candidate_families']==candidate_count==4
    assert summary['accepted_variants']==5
    assert not any(s in summary['statuses'] for s in ('operational_error','budget_deferred','pending'))
    report={'passed':True,'sources_checked':len(records),'request_response_pairs_checked':len(receipts),
            'families_checked':candidate_count,'paid_calls_during_verification':0,
            'resume_calls_api_zero':True,'source_hashes_and_raw_normalization':True,
            'frozen_protocol_and_selection':True,'five_shared_bases_and_exact_patches':True,
            'exact_or_ordered_elided_citations':True,'benchmark_grade_agreement_not_overridden':True,
            'accounting':c.accounting()}
    save(BATCH/'OFFLINE_VERIFICATION.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
