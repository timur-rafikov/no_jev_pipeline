"""Optional tokenizer-based reviewer reserve; shared ledger and unknown charges unchanged.

Not a provider-enforced credit cap: request token accounting includes generous overhead.
If tokenizer availability or observed accounting invalidates that estimate, fall back to
the original byte reserve before another request. No network calls on import.
"""
import json
import math
from client import Client as LegacyClient
from pipeline import canonical


class Client(LegacyClient):
    def __init__(self, root=None):
        if root is None:
            super().__init__()
        else:
            super().__init__(root)
        self.encoder = None
        self.token_bound_validated = False
        try:
            import tiktoken
            self.encoder = tiktoken.get_encoding('o200k_base')
            checked = 0
            for path in self.logs.glob('*.json'):
                row = json.loads(path.read_text())
                request = row.get('request', {})
                usage = row.get('response', {}).get('usage', {})
                if request.get('model') != 'openai/gpt-5.4-mini' or 'prompt_tokens' not in usage:
                    continue
                if usage['prompt_tokens'] > self.input_bound(request):
                    raise ValueError('token_bound_breached_in_observed_usage')
                checked += 1
            # Calibrate against real responses, not an assumed universal tokenizer rule.
            self.token_bound_validated = checked >= 5
        except Exception:
            self.encoder = None
            self.token_bound_validated = False

    def input_bound(self, request):
        measured = len(self.encoder.encode(canonical(request), disallowed_special=()))
        return math.ceil(measured * 1.25) + 2048

    def priced(self, payload):
        request, legacy_bound = super().priced(payload)
        if payload['model'] != 'openai/gpt-5.4-mini' or not self.token_bound_validated:
            return request, legacy_bound
        model = self.models[payload['model']]
        bound = (self.input_bound(request) * float(model['pricing']['prompt'])
                 + request['max_tokens'] * float(model['pricing']['completion'])) * 1.05
        return request, min(legacy_bound, bound)
