"""Set an explicitly authorized NEW spending allowance. Dry run unless --apply.

Never deletes receipts or releases unknown charges. This command does not call an API.
Run it yourself only after deciding how much additional spending you authorize.
"""
import argparse
import fcntl
import json
import math
from pathlib import Path
import time
from budget_v6 import Client
from client import save

ROOT=Path(__file__).resolve().parent


def propose(root,amount,purpose):
    if not math.isfinite(amount) or amount<=0 or not purpose.strip():
        raise ValueError('positive_finite_amount_and_purpose_required')
    root=Path(root);account=Client(root).accounting()
    return {'authorization':'Explicit local configure_budget_v6.py --apply command',
        'purpose':purpose,'created_at':time.time(),'additional_limit_usd':amount,
        'baseline_actual_usd':account['actual_usd'],
        'baseline_reserved_usd':account['unresolved_reserved_usd'],
        'baseline_attempts':account['attempts'],
        'effective_ledger_cap_usd':account['actual_usd']+account['unresolved_reserved_usd']+amount,
        'previous_remainder_not_spent':account['remaining_usd']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--additional-usd',type=float,required=True)
    parser.add_argument('--purpose',required=True);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    with (ROOT/'.run.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        proposal=propose(ROOT,args.additional_usd,args.purpose)
        if args.apply:
            history=ROOT/'budget_history';history.mkdir(exist_ok=True)
            save(history/(str(time.time_ns())+'.json'),json.loads((ROOT/'budget_session_v6.json').read_text()))
            save(ROOT/'budget_session_v6.json',proposal)
        print(json.dumps({'applied':args.apply,'paid_calls':0,'proposal':proposal},indent=2))


if __name__=='__main__':main()
