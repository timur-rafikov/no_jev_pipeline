"""Run the frozen new10 batch using the unchanged v3 pipeline and shared budget.

Dry-run by default. --run does not increase the existing spending authorization.
"""
import argparse
import fcntl
import json
import shutil
from pathlib import Path
import runner
from client import Client,save
from pipeline import freeze,digest

ROOT=Path(__file__).resolve().parent
BATCH=ROOT/'batches/v3_new10_20261026'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',action='store_true')
    parser.add_argument('--recover-interrupted',action='store_true',help='One explicit retry of the recorded interrupted first review, retaining its unknown charge.')
    args=parser.parse_args()
    manifest=json.loads((BATCH/'selection_manifest.json').read_text())
    assert freeze(ROOT)==manifest['protocol'],'Pipeline changed after sample selection.'
    records=[json.loads(l) for l in (BATCH/'selected_records.jsonl').read_text().splitlines()]
    assert len(records)==10
    assert [digest(r) for r in records]==[r['source_hash'] for r in manifest['selected']]
    class RecoveryClient(Client):
        def request(self,payload,tag):
            reason=None
            if args.recover_interrupted and tag.get('case')=='v3_new10_01' and tag.get('stage')=='review' and tag.get('attempt')==0:
                reason=('Explicit recovery after interrupted transport. Public simulator provenance verified in '
                        'batches/v3_new10_20261026/provenance/PUBLIC_SIMULATOR_PROVENANCE.json. '
                        'Original unknown charge remains fully reserved; one new review only, identical prompt.')
            return super().request(payload,tag,recovery_reason=reason)
    client=RecoveryClient(ROOT)
    if not args.run:
        print(json.dumps({'selected':len(records),'protocol':manifest['protocol']['protocol'],
                          'paid_calls':False,'accounting':client.accounting()}));return
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.recover_interrupted:
            proof=json.loads((BATCH/'provenance/PUBLIC_SIMULATOR_PROVENANCE.json').read_text())
            assert len(proof['all_card_like_values_checked'])==2
            assert all(r['all_16_digit_values_match_public_fixture'] for r in proof['all_card_like_values_checked'])
            path=BATCH/'results/v3_new10_01.json'
            old=json.loads(path.read_text())
            if old['status']=='operational_error':
                archive=BATCH/'operational_history';archive.mkdir(exist_ok=True)
                saved=archive/'first_interrupted_record.json'
                if not saved.exists():shutil.copy2(path,saved)
                old['status']='pending';save(path,old)
        runner.ROOT=BATCH
        for record in records:
            result=runner.run_record(record,client)
            summary=runner.summarize(client)
            save(BATCH/'RUN_STATE.json',{'last_case':record['case_id'],'accounting':client.accounting(),
                                       'source_selection_sha256':digest(manifest)})
            print(json.dumps({'case':record['case_id'],'status':result['status'],
                              'reasons':result.get('reasons'),'accounting':client.accounting()}),flush=True)
            # A malformed response is recorded for that task; it must not prevent
            # the remaining frozen tasks from being attempted or silently replace it.
            if result['status']=='budget_deferred':break

if __name__=='__main__':main()
