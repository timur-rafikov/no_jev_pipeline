"""Shared ledger plus a separate $1 session cap, preserving every unknown charge."""
import json
import math
from pathlib import Path
from budget_v4 import Client as PriorClient
from pipeline import canonical


class Client(PriorClient):
    def __init__(self, root=None):
        super().__init__(root)
        self.authorization = json.loads((self.root/'budget_session_v5.json').read_text())
        if (not math.isfinite(self.authorization['additional_limit_usd'])
            or self.authorization['additional_limit_usd']<=0
            or not math.isclose(self.authorization['effective_ledger_cap_usd'],
                self.authorization['baseline_actual_usd']+self.authorization['baseline_reserved_usd']+
                self.authorization['additional_limit_usd'],abs_tol=1e-9)):
            raise ValueError('invalid_budget_authorization')
        # Use the price catalogue fetched for this version; require_parameters/max_price
        # remain part of each cached, receipted request.
        self.models = {m['id']: m for m in json.loads((self.root/'models_snapshot_v5.json').read_text())['data']}
        self.claude_bound_validated=False
        if self.encoder is not None:
            observed=[json.loads(path.read_text()) for path in self.logs.glob('*.json')]
            observed=[r for r in observed if r.get('request',{}).get('model')=='anthropic/claude-sonnet-4.6'
                      and 'prompt_tokens' in r.get('response',{}).get('usage',{})]
            self.claude_bound_validated=(len(observed)>=3 and all(
                r['response']['usage']['prompt_tokens']<=self.claude_input_bound(r['request']) for r in observed))

    def claude_input_bound(self,request):
        # This is NOT Claude's tokenizer. Use twice the measured token count plus
        #4096 overhead, calibrated against actual Claude receipts; otherwise byte fallback.
        return 2*len(self.encoder.encode(canonical(request),disallowed_special=()))+4096

    def priced(self,payload):
        request,bound=super().priced(payload)
        if payload['model']=='anthropic/claude-sonnet-4.6' and self.claude_bound_validated:
            price=self.models[payload['model']]['pricing']
            estimate=(self.claude_input_bound(request)*float(price['prompt'])+
                      request['max_tokens']*float(price['completion']))*1.05
            bound=min(bound,estimate)
        return request,bound

    def accounting(self):
        row = super().accounting()
        a = self.authorization
        cap = a['effective_ledger_cap_usd']
        row.update(budget_usd=cap, remaining_usd=cap-row['actual_usd']-row['unresolved_reserved_usd'],
                   session_limit_usd=a['additional_limit_usd'],
                   session_actual_usd=row['actual_usd']-a['baseline_actual_usd'],
                   session_reserved_delta_usd=row['unresolved_reserved_usd']-a['baseline_reserved_usd'])
        return row
