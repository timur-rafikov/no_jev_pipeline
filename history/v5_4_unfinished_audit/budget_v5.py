"""Shared ledger plus a separate $1 session cap, preserving every unknown charge."""
import json
import math
from pathlib import Path
from budget_v4 import Client as PriorClient


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

    def accounting(self):
        row = super().accounting()
        a = self.authorization
        cap = a['effective_ledger_cap_usd']
        row.update(budget_usd=cap, remaining_usd=cap-row['actual_usd']-row['unresolved_reserved_usd'],
                   session_limit_usd=a['additional_limit_usd'],
                   session_actual_usd=row['actual_usd']-a['baseline_actual_usd'],
                   session_reserved_delta_usd=row['unresolved_reserved_usd']-a['baseline_reserved_usd'])
        return row
