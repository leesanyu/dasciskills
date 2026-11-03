"""T3 inference checks using independent enumeration/formulas, without SciPy."""

import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import methods as engine
import stats as st


def pair(x, y, kinds=('numeric', 'numeric')):
    frame, _ = dr.normalize_frame(pd.DataFrame({'x': x, 'y': y}))
    cols = [dr.prepare_column(name, i, frame[name], kind=kind) for i, (name, kind) in enumerate(zip(frame.columns, kinds))]
    dr.prepare_pair(frame, *cols)
    return cols


def reference_ranks(x):
    # Definition by pairwise counts, independently of the production sorter.
    return np.array([1 + sum(v < a for v in x) + .5 * (sum(v == a for v in x) - 1) for a in x])


def reference_stat(mid, x, y):
    if mid == 'spearman':
        return abs(float(np.corrcoef(reference_ranks(x), reference_ranks(y))[0, 1]))
    if mid == 'kendall_tau_b':
        return abs(sum(np.sign(x[j] - x[i]) * np.sign(y[j] - y[i]) for i, j in itertools.combinations(range(len(x)), 2)))
    ranks = reference_ranks(x)
    levels = sorted(set(y))
    sums = [sum(ranks[np.array(y) == level]) for level in levels]
    sizes = [sum(v == level for v in y) for level in levels]
    if mid == 'mann_whitney':
        return abs(sums[0] - sizes[0] * (sizes[0] + 1) / 2 - sizes[0] * sizes[1] / 2)
    n = len(x)
    ties = [sum(v == level for v in x) for level in sorted(set(x))]
    correction = 1 - sum(t**3 - t for t in ties) / (n**3 - n)
    return max(0, (12 / (n * (n + 1)) * sum(s*s / k for s, k in zip(sums, sizes)) - 3 * (n + 1)) / correction)


class RankPermutationTests(unittest.TestCase):
    cases = [
        ('spearman', [1, 1, 2, 3, 4], [3, 2, 2, 4, 5]),
        ('kendall_tau_b', [1, 1, 2, 3, 4], [3, 2, 2, 4, 5]),
        ('mann_whitney', [1, 1, 2, 4, 5], [0, 0, 1, 1, 1]),
        ('kruskal_wallis', [1, 1, 2, 3, 4, 4], [0, 0, 1, 1, 2, 2]),
    ]

    def test_fixed_seed_matches_independent_tied_permutation_reference(self):
        for mid, x, y in self.cases:
            with self.subTest(method=mid):
                x, y = np.array(x), np.array(y)
                observed = reference_stat(mid, x, y)
                rng = np.random.default_rng(701)
                extreme = sum(reference_stat(mid, x, rng.permutation(y)) >= observed - 1e-12 for _ in range(137))
                result = st.permutation_rank_test(mid, x, y, n_permutations=137, seed=701)
                self.assertEqual(result.extreme, extreme)
                self.assertEqual(result.p, (extreme + 1) / 138)
                self.assertEqual((result.requested, result.used, result.seed), (137, 137, 701))
                self.assertEqual(result.alternative, 'greater' if mid == 'kruskal_wallis' else 'two_sided')
                self.assertAlmostEqual(result.resolution, 1 / 138)
                self.assertAlmostEqual(result.mc_standard_error, np.sqrt(result.p * (1 - result.p) / 137))
                self.assertEqual(result, st.permutation_rank_test(mid, x, y, n_permutations=137, seed=701))

    def test_enumerated_tiny_null_including_all_ties(self):
        for mid, x, y in self.cases:
            with self.subTest(method=mid):
                x, y = np.array(x), np.array(y)
                permutations = [np.array(p) for p in itertools.permutations(range(len(y)))]
                observed = reference_stat(mid, x, y)
                extreme = sum(reference_stat(mid, x, y[p]) >= observed - 1e-12 for p in permutations)
                # Each index permutation is included, including duplicated value
                # assignments when tied. The +1 correction remains explicit.
                with patch.object(np.random, 'default_rng') as rng:
                    rng.return_value.permutation.side_effect = permutations
                    result = st.permutation_rank_test(mid, x, y, n_permutations=len(permutations), seed=9)
                self.assertEqual(result.p, (extreme + 1) / (len(permutations) + 1))
                self.assertEqual(rng.return_value.permutation.call_count, len(permutations))

    def test_two_sided_rank_direction_and_nonzero_p_at_one_draw(self):
        for mid in ('spearman', 'kendall_tau_b'):
            a = st.permutation_rank_test(mid, np.arange(9), np.arange(9), n_permutations=1, seed=21)
            b = st.permutation_rank_test(mid, np.arange(9), -np.arange(9), n_permutations=1, seed=21)
            self.assertEqual(a.p, b.p)
            self.assertGreaterEqual(a.p, .5)
            self.assertEqual(a.used, 1)

    def test_no_silent_budget_floor_or_cap(self):
        for budget in (1, 7, 2003):
            result = st.permutation_rank_test('spearman', [1, 2, 3], [1, 3, 2], n_permutations=budget, seed=7)
            self.assertEqual(result.used, budget)
            self.assertGreaterEqual(result.p, 1 / (budget + 1))

    def test_primitives_reject_degenerate_inputs(self):
        calls = [lambda: st.kendall_tau_b([1, 1, 1], [1, 2, 3]),
                 lambda: st.kruskal_wallis([[1, 1], [1, 1]]),
                 lambda: st.welch_t_test([1, 1], [2, 2]),
                 lambda: st.permutation_rank_test('spearman', [1, 1, 1], [1, 2, 3], n_permutations=9, seed=7),
                 lambda: st.permutation_rank_test('mann_whitney', [1, 2, 3], [0, 0, 0], n_permutations=9, seed=7),
                 lambda: st.permutation_rank_test('spearman', [1, 2, 3], [1, 3, 2], n_permutations=0, seed=7)]
        for call in calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()


class InferenceBoundaryTests(unittest.TestCase):
    def test_small_rank_methods_switch_to_permutation_or_disabled(self):
        samples = [
            (pair([1, 1, 2, 3, 4], [3, 2, 2, 4, 5]), ['spearman', 'kendall_tau_b']),
            (pair([1, 1, 2, 4, 5], ['a', 'a', 'b', 'b', 'b'], ('numeric', 'categorical')), ['mann_whitney']),
            (pair([1, 1, 2, 3, 4, 4], ['a', 'a', 'b', 'b', 'c', 'c'], ('numeric', 'categorical')), ['kruskal_wallis']),
        ]
        for cols, mids in samples:
            for budget in (0, 17):
                with self.subTest(methods=mids, budget=budget):
                    result = engine.analyze_pair(*cols, methods=','.join(mids), permutations=budget, seed=701)[0]
                    for test in result['tests']:
                        self.assertEqual(test['n'], len(cols[0].analysis_series))
                        self.assertEqual(test['permutations_requested'], budget)
                        self.assertEqual(test['permutations_used'], budget)
                        self.assertEqual(test['p_adjusted'] is None, budget == 0)
                        if budget:
                            self.assertEqual(test['p_method'], 'permutation')
                            self.assertIn('可交换', test['null_hypothesis'])
                            self.assertEqual(test['seed'], 701)
                            self.assertEqual(test['p_resolution'], 1 / 18)
                            self.assertGreater(test['p_value'], 0)
                        else:
                            self.assertIsNone(test['p_value'])
                            self.assertEqual(test['status'], 'descriptive_only')
                            self.assertIn('禁用', test['reason'])
                            self.assertIsNone(test['p_resolution'])
                    json.dumps(result, allow_nan=False)

    def test_exact_thresholds_keep_asymptotic_p_with_zero_budget(self):
        samples = [
            (pair(np.arange(30), np.arange(30)**2), 'spearman,kendall_tau_b'),
            (pair(np.arange(20), ['a']*10 + ['b']*10, ('numeric', 'categorical')), 'mann_whitney'),
            (pair(np.arange(15), ['a']*5 + ['b']*5 + ['c']*5, ('numeric', 'categorical')), 'kruskal_wallis'),
        ]
        for cols, mids in samples:
            with self.subTest(methods=mids):
                result = engine.analyze_pair(*cols, methods=mids, permutations=0)[0]
                self.assertTrue(all(t['p_value'] is not None and t['p_method'] != 'permutation' for t in result['tests']))
                self.assertTrue(all(t['permutations_used'] == 0 for t in result['tests']))

    def test_below_each_threshold_uses_permutation(self):
        samples = [
            (pair(np.arange(29), np.arange(29)**2), 'spearman,kendall_tau_b'),
            (pair(np.arange(19), ['a']*9 + ['b']*10, ('numeric', 'categorical')), 'mann_whitney'),
            (pair(np.arange(14), ['a']*4 + ['b']*5 + ['c']*5, ('numeric', 'categorical')), 'kruskal_wallis'),
        ]
        for cols, mids in samples:
            with self.subTest(methods=mids):
                result = engine.analyze_pair(*cols, methods=mids, permutations=7)[0]
                self.assertTrue(all(t['p_method'] == 'permutation' and t['permutations_used'] == 7 for t in result['tests']))

    def test_undefined_cohen_d_retained_as_null_with_reason(self):
        cols = pair([1, 1, 2, 2], ['a', 'a', 'b', 'b'], ('numeric', 'categorical'))
        result = engine.analyze_pair(*cols, permutations=13)[0]
        welch = next(m for m in result['methods'] if m['id'] == 'welch_t')
        self.assertEqual(welch['status'], 'not_applicable')
        effect = next(e for e in result['effects'] if e['name'] == 'cohen_d')
        self.assertIsNone(effect['value'])
        self.assertTrue(effect['reason'])
        self.assertTrue(all(t['method_id'] != 'welch_t' or t['p_value'] is None for t in result['tests']))
        json.dumps(result, allow_nan=False)

    def test_mean_methods_keep_all_groups_and_variance_requirements(self):
        # One group is constant; the rank method still has a valid null.
        cols = pair([1, 1, 1, 2, 3, 4, 5, 6, 8], ['a']*3+['b']*3+['c']*3, ('numeric', 'categorical'))
        result = engine.analyze_pair(*cols, permutations=23)[0]
        states = {m['id']: m['status'] for m in result['methods']}
        self.assertEqual(states, {'anova':'not_applicable', 'welch_anova':'not_applicable', 'kruskal_wallis':'ok'})
        self.assertTrue(all(m['details']['group_sizes'] == [3,3,3] for m in result['methods']))
        self.assertEqual(result['tests'][0]['n'], 9)

    def test_anova_sd_ratio_and_group_count_rules(self):
        for x, g in [([0, 1, 2, 0, 4, 8, 1, 2, 3], ['a']*3+['b']*3+['c']*3),
                     (list(range(63)), [str(i//3) for i in range(63)])]:
            result = engine.analyze_pair(*pair(x, g, ('numeric', 'categorical')), methods='anova', permutations=0)[0]
            self.assertEqual(result['methods'][0]['status'], 'not_applicable')
            self.assertTrue(result['methods'][0]['reason'])

    def test_fisher_infinite_odds_is_null_but_exact_p_is_retained(self):
        result = engine.analyze_pair(*pair(['a']*3+['b']*3, ['a']*3+['b']*3, ('categorical','categorical')), permutations=11)[0]
        fisher = next(t for t in result['tests'] if t['method_id'] == 'fisher_exact')
        self.assertAlmostEqual(fisher['p_value'], .1)
        self.assertIsNone(fisher['statistic_value'])
        self.assertTrue(fisher['reason'])
        odds = next(e for e in result['effects'] if e['name'] == 'odds_ratio')
        self.assertIsNone(odds['value'])
        self.assertTrue(odds['reason'])
        json.dumps(result, allow_nan=False)

    def test_pearson_unavailable_intervals_at_n3_and_perfect_correlation(self):
        for x, y in [([1,2,3], [3,1,2]), (list(range(6)), list(range(6))), (list(range(6)), list(range(6))[::-1])]:
            primitive = st.pearson(x,y)
            self.assertIsNone(primitive.ci_low)
            self.assertIsNone(primitive.ci_high)
            self.assertTrue(primitive.ci_note)
            result = engine.analyze_pair(*pair(x,y), permutations=13)[0]
            self.assertTrue(all(e['interval'] is None and e['reason'] for e in result['effects']))
            json.dumps(result, allow_nan=False)

    def test_rank_primitive_does_not_borrow_fisher_interval(self):
        result = st.spearman(np.arange(40), np.arange(40)**2 + np.tile([0,10],20))
        self.assertIsNone(result.ci_low)
        self.assertIsNone(result.ci_high)
        self.assertTrue(result.ci_note)

    def test_single_group_or_constant_after_pairing_is_rejected(self):
        for x,y,kinds in [([1,1,2],[1,2,None],('numeric','numeric')),
                          ([1,2,None],['a','a','b'],('numeric','categorical'))]:
            with self.subTest(kinds=kinds), self.assertRaises(dr.UserError):
                pair(x,y,kinds)

    def test_one_constant_welch_group_is_allowed_when_standard_error_positive(self):
        cols = pair([1,1,2,3], ['a','a','b','b'], ('numeric','categorical'))
        result = engine.analyze_pair(*cols, methods='welch_t', permutations=0)[0]
        self.assertEqual(result['methods'][0]['status'], 'ok')
        self.assertAlmostEqual(result['effects'][0]['value'], 3)


class ContingencyInferenceTests(unittest.TestCase):
    def table_pair(self, table):
        x,y=[],[]
        for i,j in np.ndindex(np.array(table).shape):
            x.extend([f'a{i}']*table[i][j]); y.extend([f'b{j}']*table[i][j])
        return pair(x,y,('categorical','categorical'))

    def test_sparse_chi_and_g_match_their_own_independent_null(self):
        table=np.array([[3,1,0],[1,0,2],[0,2,1]])
        cols=self.table_pair(table.tolist())
        expected=np.outer(table.sum(axis=1),table.sum(axis=0))/table.sum()
        def statistic(t,mid):
            if mid=='chi_square': return np.sum((t-expected)**2/expected)
            return 2*sum(v*np.log(v/expected[i,j]) for (i,j),v in np.ndenumerate(t) if v)
        for mid in ('chi_square','g_test'):
            observed=statistic(table,mid)
            codes=[np.array([int(v[1:]) for v in c.analysis_series]) for c in cols]
            rng=np.random.default_rng(37)
            extreme=0
            for _ in range(131):
                perm=np.zeros((3,3),dtype=int)
                for a,b in zip(codes[0],rng.permutation(codes[1])): perm[a,b]+=1
                extreme+=statistic(perm,mid)>=observed-1e-12
            result=engine.analyze_pair(*cols,methods=mid,permutations=131,seed=37)[0]
            test=result['tests'][0]
            self.assertEqual(test['p_value'],(extreme+1)/132)
            self.assertEqual(test['alternative'],'greater')
            self.assertEqual(test['permutation_extreme'],extreme)
            self.assertEqual(test['p_resolution'],1/132)
            self.assertAlmostEqual(test['mc_standard_error'],np.sqrt(test['p_value']*(1-test['p_value'])/131))

    def test_nonsparse_2x2_yates_does_not_change_cramers_v(self):
        table=np.array([[20,10],[10,20]])
        result=engine.analyze_pair(*self.table_pair(table.tolist()),permutations=0)[0]
        chi=next(t for t in result['tests'] if t['method_id']=='chi_square')
        self.assertEqual(chi['p_method'],'chi_square_yates')
        self.assertAlmostEqual(chi['statistic_value'],5.4)
        vs=[e['value'] for e in result['effects'] if e['name']=='cramers_v']
        self.assertTrue(all(abs(v-1/3)<1e-12 for v in vs))

    def test_sparse_date_leaves_follow_same_budget_and_common_sample(self):
        cols=pair(pd.date_range('2024-01-01',periods=9,tz='Asia/Shanghai'), ['a','b','c']*3, ('datetime','categorical'))
        for budget in (0,17):
            result=engine.analyze_pair(*cols,permutations=budget,seed=55)[0]
            leaves=[t for t in result['tests'] if t['method_id']=='datetime_features']
            self.assertTrue(leaves)
            self.assertTrue(all(t['n']==9 for t in result['tests']))
            self.assertTrue(all(t['permutations_used']==budget for t in leaves))
            self.assertTrue(all((t['p_value'] is None)==(budget==0) for t in leaves))
            self.assertEqual(result['transformations'][0]['timezone_handling'],'converted_to_UTC')
            self.assertTrue(result['methods'][1]['details']['excluded_features'])

    def test_cli_saves_calibration_precision_and_strict_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'data.csv'
            pd.DataFrame({'x':[1,1,2,3,4], 'y':[3,2,2,4,5]}).to_csv(path,index=False)
            args=dr.build_parser().parse_args(['analyze','--input',str(path),'--col1','x','--col2','y',
                '--col1-type','numeric','--col2-type','numeric','--methods','spearman,kendall_tau_b',
                '--permutations','37','--seed','701','--no-chart','--out',str(root/'out')])
            result=dr.cmd_analyze(args)
            saved=json.loads(Path(result['result_path']).read_text(),parse_constant=lambda x:self.fail(x))
            self.assertEqual(saved,result)
            text=Path(result['report_md_path']).read_text()
            for test in result['tests']:
                self.assertIn(test['id'],text)
                self.assertEqual(test['permutations_used'],37)
                self.assertEqual(test['seed'],701)
            for label in ('请求 B','实际 B','分辨率','MC 标准误','701','37'):
                self.assertIn(label,text)


if __name__=='__main__':
    unittest.main()
