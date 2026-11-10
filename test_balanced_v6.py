import unittest
from collections import Counter
import prepare_balanced_v6 as b


def rec(i, task, gold):
    return {'id': f'm{i}', 'task_id': task, 'source_gold': gold}


class BalancedSelectTest(unittest.TestCase):
    def pool(self):
        # 3:1 failure-heavy pool, one task shared across classes.
        rows = [rec(i, f't{i}', 'failure') for i in range(30)]
        rows += [rec(100 + i, f's{i}', 'success') for i in range(10)]
        rows.append(rec(200, 't0', 'success'))
        return rows

    def test_equal_classes_and_balanced_prefixes(self):
        chosen = b.balanced_select(self.pool(), 10, 'seed')
        self.assertEqual(Counter(r['source_gold'] for r in chosen), {'success': 5, 'failure': 5})
        for k in range(2, 11, 2):
            self.assertEqual(Counter(r['source_gold'] for r in chosen[:k]), {'success': k // 2, 'failure': k // 2})

    def test_unique_tasks_across_classes(self):
        chosen = b.balanced_select(self.pool(), 20, 'seed')
        tasks = [r['task_id'] for r in chosen]
        self.assertEqual(len(tasks), len(set(tasks)))

    def test_deterministic_and_seed_dependent(self):
        ids = lambda seed: [r['id'] for r in b.balanced_select(self.pool(), 10, seed)]
        self.assertEqual(ids('x'), ids('x'))
        self.assertNotEqual(ids('x'), ids('y'))

    def test_shortage_is_an_error_not_silent_imbalance(self):
        with self.assertRaisesRegex(ValueError, 'insufficient_class_records'):
            b.balanced_select(self.pool(), 24, 'seed')

    def test_count_must_be_even(self):
        with self.assertRaises(ValueError):
            b.balanced_select(self.pool(), 7, 'seed')

    def test_availability_counts_tasks(self):
        info = b.availability(self.pool())
        self.assertEqual(info['executions'], {'success': 11, 'failure': 30})
        self.assertEqual(info['max_balanced_count'], 22)


if __name__ == '__main__':
    unittest.main()
