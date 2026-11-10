import copy
import unittest
from audit_source_alignment import compare


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.raw={'result':[['get_watchlist()']], 'inference_log':[{'begin_of_turn_query':[],
            'step_0':[{'role':'tool','content':'{"watchlist": ["TSLA", "GOOG"]}'}]}]}
        self.score={'model_result_raw':[['get_watchlist()']],
            'error':{'execution_result':[{'model':[['{"watchlist":["TSLA","GOOG"]}']]}]}}
    def test_json_whitespace_is_not_an_observation_difference(self):
        self.assertEqual(compare(self.raw,self.score)['status'],'observed_prefix_matches')
    def test_different_watchlist_is_reported_without_relabeling(self):
        self.score['error']['execution_result'][0]['model']=[['{"watchlist":["NVDA","TSLA","GOOG"]}']]
        report=compare(self.raw,self.score)
        self.assertEqual(report['status'],'different_observations');self.assertEqual(len(report['mismatches']),1)
    def test_different_action_sequence_is_not_compared(self):
        self.score['model_result_raw']=[['other_action()']]
        self.assertEqual(compare(self.raw,self.score)['status'],'model_result_sequence_not_identical')
    def test_absent_success_replay_is_not_declared_verified(self):
        self.assertEqual(compare(self.raw,None)['status'],'no_replay_record_for_benchmark_success')

if __name__=='__main__':unittest.main()
