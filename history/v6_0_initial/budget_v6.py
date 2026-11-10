"""New explicit session allowance; all historical receipts/reserves remain intact."""
import json
import math
from budget_v4 import Client as PriorClient


class Client(PriorClient):
    def __init__(self, root=None):
        super().__init__(root)
        self.authorization = json.loads((self.root/'budget_session_v6.json').read_text())
        a = self.authorization
        if (not math.isfinite(a['additional_limit_usd']) or a['additional_limit_usd'] <= 0 or
            not math.isclose(a['effective_ledger_cap_usd'], a['baseline_actual_usd'] +
                a['baseline_reserved_usd'] + a['additional_limit_usd'], abs_tol=1e-9)):
            raise ValueError('invalid_budget_authorization')
        self.models = {m['id']: m for m in json.loads((self.root/'models_snapshot_v6.json').read_text())['data']}

    def accounting(self):
        row = super().accounting()
        a = self.authorization
        cap = a['effective_ledger_cap_usd']
        row.update(budget_usd=cap, remaining_usd=cap-row['actual_usd']-row['unresolved_reserved_usd'],
            session_limit_usd=a['additional_limit_usd'],
            session_actual_usd=row['actual_usd']-a['baseline_actual_usd'],
            session_reserved_delta_usd=row['unresolved_reserved_usd']-a['baseline_reserved_usd'])
        return row
