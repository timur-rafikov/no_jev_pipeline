import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import budget_v4
import client
from pipeline_v4 import REVIEWER,generation_payload,review_payload
import test_v4


class BudgetV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'requests').mkdir()
        (self.root/'models_snapshot.json').write_text(json.dumps({'data':[{'id':REVIEWER,'pricing':{'prompt':'0.00000075','completion':'0.0000045'}}]}))
        fixture=test_v4.V4Tests();fixture.setUp();self.payload=review_payload(fixture.r,fixture.f)
        for i in range(5):
            (self.root/'requests'/f'{i}.json').write_text(json.dumps({'request':self.payload,'actual_usd':.001,'reserve_usd':.08,'response':{'usage':{'prompt_tokens':100}}}))
        (self.root/'requests'/'unknown.json').write_text(json.dumps({'request':self.payload,'actual_usd':None,'reserve_usd':.0495684}))
        self.fake=types.SimpleNamespace(get_encoding=lambda name:types.SimpleNamespace(encode=lambda text,**kw:list(range(120))))
    def tearDown(self):self.temp.cleanup()

    def test_accounting_preserves_unknown_reservation(self):
        with patch.dict('sys.modules',{'tiktoken':self.fake}):c=budget_v4.Client(self.root)
        self.assertEqual(c.accounting(),client.Client(self.root).accounting())
        self.assertEqual(c.accounting()['unresolved_reserved_usd'],.0495684)

    def test_pricing_improvement_does_not_change_request_or_cache_key(self):
        with patch.dict('sys.modules',{'tiktoken':self.fake}):c=budget_v4.Client(self.root)
        new=c.priced(self.payload);old=client.Client(self.root).priced(self.payload)
        self.assertEqual(new[0],old[0]);self.assertLess(new[1],old[1])

    def test_observed_token_bound_breach_restores_byte_reserve(self):
        path=self.root/'requests/0.json';r=json.loads(path.read_text());r['response']['usage']['prompt_tokens']=99999;path.write_text(json.dumps(r))
        with patch.dict('sys.modules',{'tiktoken':self.fake}):c=budget_v4.Client(self.root)
        self.assertFalse(c.token_bound_validated)
        self.assertEqual(c.priced(self.payload),client.Client(self.root).priced(self.payload))

    def test_missing_tokenizer_falls_back_without_network(self):
        with patch.dict('sys.modules',{'tiktoken':None}):c=budget_v4.Client(self.root)
        self.assertEqual(c.priced(self.payload),client.Client(self.root).priced(self.payload))

if __name__=='__main__':unittest.main()
