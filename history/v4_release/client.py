"""Sequential, resumable, budget-reserved OpenRouter client; no secret in receipts."""
import hashlib
import json
import math
import os
import time
import urllib.request
from pathlib import Path
from pipeline import canonical

ROOT=Path(__file__).resolve().parent
BUDGET=0.711952776  # Original remainder + explicit additional $0.50 for the new10 pilot.
ENDPOINT='https://openrouter.ai/api/v1/chat/completions'

def save(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(path)

class BudgetError(Exception):pass
class UnresolvedRequest(Exception):pass

class Client:
    def __init__(self,root=ROOT):
        self.root=Path(root);self.logs=self.root/'requests';self.logs.mkdir(exist_ok=True)
        self.models={x['id']:x for x in json.loads((self.root/'models_snapshot.json').read_text())['data']}

    def accounting(self):
        rows=[json.loads(p.read_text()) for p in self.logs.glob('*.json')]
        actual=sum(r.get('actual_usd') or 0 for r in rows)
        reserved=sum(r['reserve_usd'] for r in rows if r.get('actual_usd') is None)
        return {'budget_usd':BUDGET,'actual_usd':actual,'unresolved_reserved_usd':reserved,
                'remaining_usd':BUDGET-actual-reserved,'attempts':len(rows)}

    def priced(self,payload):
        p=json.loads(json.dumps(payload));model=self.models[p['model']]
        pin=float(model['pricing']['prompt']);pout=float(model['pricing']['completion'])
        p['provider']={'max_price':{'prompt':pin*1e6,'completion':pout*1e6},'require_parameters':True}
        # Conservative byte-based upper reserve (not a predicted average cost).
        input_bound=len(canonical(p).encode())+2048
        return p,(input_bound*pin+p['max_tokens']*pout)*1.05

    def request(self,payload,tag,recovery_reason=None):
        p,bound=self.priced(payload);h=hashlib.sha256(canonical(p).encode()).hexdigest();receipt_id=h;path=self.logs/(h+'.json')
        recovery_of=None
        if path.exists():
            row=json.loads(path.read_text())
            if row.get('parsed') is not None:return row['parsed'],h
            retry_id=h+'.recovery1';retry_path=self.logs/(retry_id+'.json')
            if retry_path.exists():
                recovered=json.loads(retry_path.read_text())
                if recovered.get('parsed') is not None:return recovered['parsed'],retry_id
                raise UnresolvedRequest('One explicit recovery was already attempted: '+h)
            if not recovery_reason:
                raise UnresolvedRequest('Previous attempt not retried: '+h)
            if row['status']!='operational_error' or 'response' in row or row.get('error_type') not in ('URLError','TimeoutError'):
                raise UnresolvedRequest('This failure is not eligible for explicit network recovery: '+h)
            # Deliberate recovery, not an automatic retry. Keep the entire old unknown
            # charge reserved and reserve a second full request before sending it.
            recovery_of=h;receipt_id=retry_id;path=retry_path
        if bound>self.accounting()['remaining_usd']:raise BudgetError('request_reserve_exceeds_remaining')
        key=os.environ.get('OPENROUTER_API_KEY')
        if not key:
            key=(self.root.parent/'.private/openrouter.key').read_text().strip()
        row={'tag':tag,'request_hash':h,'request':p,'reserve_usd':bound,'actual_usd':None,
             'status':'pending','created_at':time.time()}
        if recovery_of:row.update(receipt_id=receipt_id,recovery_of=recovery_of,recovery_reason=recovery_reason)
        save(path,row)
        req=urllib.request.Request(ENDPOINT,data=canonical(p).encode(),method='POST',
             headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        start=time.monotonic()
        try:
            with urllib.request.urlopen(req,timeout=150) as response:body=json.load(response)
            row['response']=body;cost=body.get('usage',{}).get('cost')
            if type(cost) in (int,float) and math.isfinite(cost) and cost>=0:
                row['actual_usd']=cost
            if cost is not None and cost>bound:raise ValueError('actual_exceeds_reservation')
            choice=body['choices'][0]
            if choice['finish_reason']!='stop':raise ValueError('incomplete_response_'+str(choice['finish_reason']))
            parsed=json.loads(choice['message']['content'])
            if not isinstance(parsed,dict):raise ValueError('not_json_object')
            row['parsed']=parsed;row['status']='completed'
        except Exception as e:
            row['status']='operational_error';row['error_type']=type(e).__name__
            # Keep unknown charge in reserve. Never blind retry an ambiguous timeout.
            row['elapsed_seconds']=time.monotonic()-start;save(path,row);save(self.root/'accounting.json',self.accounting())
            raise
        row['elapsed_seconds']=time.monotonic()-start;save(path,row);save(self.root/'accounting.json',self.accounting())
        return row['parsed'],receipt_id
