"""Request-wide inference references and observable multi-method explanations."""

from dataclasses import replace
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import inference as inf
import methods as engine
import stats as st


def leaf(mid, p, *, suffix=''):
    return {'id': mid + suffix, 'method_id': mid, 'feature': suffix.lstrip('.') or None,
            'n': 40, 'null_hypothesis': engine.METHODS[mid][2],
            'statistic_name': mid, 'statistic_value': .2, 'df': None,
            'p_value': p, 'p_method': 'reference', 'p_adjusted': None,
            'reject_adjusted': None, 'family_id': None,
            'status': 'ok' if p is not None else 'descriptive_only',
            'reason': None if p is not None else '置换已禁用'}


def method(mid, tests, *, status='ok', reason=None):
    return {'id': mid, 'label': engine.METHODS[mid][0], 'question': engine.METHODS[mid][1],
            'n': 40, 'status': status, 'reason': reason,
            'test_ids': [t['id'] for t in tests if t['method_id'] == mid], 'effect_ids': []}


def effect(mid, name, value):
    return {'id': f'{mid}.{name}', 'method_id': mid, 'name': name, 'value': value,
            'definition': name, 'direction': '按记录的编码方向', 'interval': None, 'reason': None}


def analyze(x, y, kinds=('numeric', 'numeric'), *, methods='auto', permutations=19):
    frame, _ = dr.normalize_frame(pd.DataFrame({'x': x, 'y': y}))
    cols = [dr.prepare_column(name, i, frame[name], kind=kind,
                             order=['低', '中', '高'] if kind == 'ordinal' else None)
            for i, (name, kind) in enumerate(zip(frame.columns, kinds))]
    dr.prepare_pair(frame, *cols)
    return engine.analyze_pair(*cols, methods=methods, permutations=permutations, seed=41)[0]


class HolmTests(unittest.TestCase):
    def test_fixed_reference_restores_original_order_and_keeps_raw(self):
        tests = [leaf('pearson', .01), leaf('spearman', .04), leaf('kendall_tau_b', .03)]
        original = [dict(t) for t in tests]
        family = inf.apply_holm(tests, .05)
        np.testing.assert_allclose([t['p_adjusted'] for t in tests], [.03, .06, .06], atol=1e-15)
        self.assertEqual([t['p_value'] for t in tests], [.01, .04, .03])
        self.assertEqual([t['id'] for t in tests], [t['id'] for t in original])
        self.assertEqual([t['reject_adjusted'] for t in tests], [True, False, False])
        self.assertEqual(family, {'family_id': 'request', 'test_ids': [t['id'] for t in tests],
                                 'm': 3, 'adjustment': 'holm', 'alpha': .05,
                                 'scope': 'request', 'excluded_test_ids': []})
        self.assertTrue(all(t['family_id'] == family['family_id'] for t in tests))

    def test_ties_zero_one_cumulative_max_and_cap(self):
        for raw, expected in [([.02, .2, .02], [.06, .2, .06]),
                              ([0, 1, .8], [0, 1, 1]),
                              ([.01, .04, .041, .9], [.04, .12, .12, .9])]:
            tests = [leaf('pearson', p, suffix=f'.{i}') for i, p in enumerate(raw)]
            inf.apply_holm(tests, .05)
            np.testing.assert_allclose([t['p_adjusted'] for t in tests], expected, atol=1e-15)

    def test_empty_singleton_null_and_alpha_equality(self):
        self.assertEqual(inf.apply_holm([], .05)['m'], 0)
        tests = [leaf('pearson', None), leaf('spearman', .05), leaf('kendall_tau_b', None)]
        family = inf.apply_holm(tests, .05)
        self.assertEqual(family['m'], 1)
        self.assertEqual(family['test_ids'], ['spearman'])
        self.assertEqual(family['excluded_test_ids'], ['pearson', 'kendall_tau_b'])
        self.assertEqual(tests[1]['p_adjusted'], .05)
        self.assertIs(tests[1]['reject_adjusted'], False)
        for t in (tests[0], tests[2]):
            self.assertIsNone(t['p_adjusted']); self.assertIsNone(t['reject_adjusted']); self.assertIsNone(t['family_id'])
        self.assertEqual(inf.apply_holm([leaf('pearson', None)], .05)['m'], 0)
        near = [leaf('pearson', .04999999)]
        inf.apply_holm(near, .05)
        conclusion = inf.summarize([method('pearson', near)], near, [], alpha=.05)[0][0]
        self.assertIn('0.04999999', conclusion['summary'])
        self.assertEqual(conclusion['status'], 'evidence')

    def test_all_calendar_leaves_share_family_without_container(self):
        tests = [leaf('mann_whitney', .01), leaf('datetime_features', .04, suffix='.weekday'),
                 leaf('datetime_features', .03, suffix='.hour'),
                 leaf('datetime_features', None, suffix='.day')]
        family = inf.apply_holm(tests, .05)
        self.assertEqual(family['m'], 3)
        np.testing.assert_allclose([t['p_adjusted'] for t in tests[:3]], [.03, .06, .06])
        self.assertNotIn('datetime_features', family['test_ids'])
        self.assertIn('datetime_features.hour', family['test_ids'])


class ExplanationTests(unittest.TestCase):
    def explain(self, tests, effects=(), unavailable=()):
        methods = [method(mid, tests) for mid in dict.fromkeys(t['method_id'] for t in tests)]
        methods += [method(mid, [], status='not_applicable', reason=reason) for mid, reason in unavailable]
        inf.apply_holm(tests, .05)
        return inf.summarize(methods, tests, list(effects), alpha=.05)

    def test_mixed_rank_evidence_retains_both_without_majority_decision(self):
        tests = [leaf('spearman', .001), leaf('kendall_tau_b', .4)]
        conclusions, comparisons = self.explain(tests)
        self.assertEqual(len(conclusions), 1)
        c = conclusions[0]
        self.assertEqual(c['status'], 'mixed_evidence')
        self.assertEqual(c['test_ids'], ['spearman', 'kendall_tau_b'])
        self.assertIn('spearman', c['summary']); self.assertIn('kendall_tau_b', c['summary'])
        self.assertIn('0.002', c['summary']); self.assertIn('0.4', c['summary'])
        self.assertIn('证据不足', c['summary'])
        self.assertEqual(comparisons[0]['evidence_relation'], 'different')
        self.assertIn('独立重复验证', comparisons[0]['explanation'])

    def test_raw_p_below_alpha_does_not_produce_adjusted_support(self):
        conclusions, _ = self.explain([leaf('pearson', .03), leaf('spearman', .04), leaf('kendall_tau_b', .045)])
        self.assertTrue(all(c['status'] == 'insufficient_evidence' for c in conclusions))
        self.assertTrue(all('证据不足' in c['summary'] for c in conclusions))
        self.assertTrue(all('0.09' in c['summary'] for c in conclusions))

    def test_linear_rank_disagreement_has_evidence_and_direction_references(self):
        tests = [leaf('pearson', .6), leaf('spearman', .001)]
        effects = [effect('pearson', 'pearson_r', -.2), effect('spearman', 'spearman_rho', .9)]
        conclusions, comparisons = self.explain(tests, effects)
        c = comparisons[0]
        self.assertEqual(c['method_ids'], ['pearson', 'spearman'])
        self.assertEqual(c['test_ids'], ['pearson', 'spearman'])
        self.assertEqual(c['direction_agreement'], 'opposite')
        self.assertEqual(c['evidence_relation'], 'different')
        self.assertEqual([d['effect_id'] for d in c['directions']], ['pearson.pearson_r', 'spearman.spearman_rho'])
        self.assertIn('线性', c['basis']); self.assertIn('单调', c['basis'])
        self.assertIn('可能', c['explanation']); self.assertIn('不能据此确定', c['explanation'])
        self.assertEqual({eid for c in conclusions for eid in c['effect_ids']}, {e['id'] for e in effects})

    def test_anova_welch_and_rank_are_grouped_by_question(self):
        tests = [leaf('anova', .001), leaf('welch_anova', .3), leaf('kruskal_wallis', .002)]
        conclusions, comparisons = self.explain(tests)
        self.assertEqual(len(conclusions), 2)
        mean = next(c for c in conclusions if c['question'] == '多组均值')
        self.assertEqual(mean['method_ids'], ['anova', 'welch_anova'])
        self.assertEqual(mean['status'], 'mixed_evidence')
        rank = next(c for c in conclusions if c['question'] == '多组秩分布')
        self.assertTrue(any('中位数' in s and '形状' in s for s in rank['limitations']))
        pairs = {tuple(c['method_ids']) for c in comparisons}
        self.assertEqual(pairs, {('anova','welch_anova'), ('anova','kruskal_wallis'), ('welch_anova','kruskal_wallis')})
        for c in comparisons:
            self.assertIn('假设', c['explanation'])

    def test_classification_methods_have_one_question_without_effect_tests(self):
        tests = [leaf('chi_square', .01), leaf('fisher_exact', .1), leaf('g_test', .02)]
        conclusions, comparisons = self.explain(tests, [effect('g_test','mutual_information', .3)])
        self.assertEqual(len(conclusions), 1)
        self.assertEqual(conclusions[0]['question'], '类别分布与独立性')
        self.assertEqual(len(conclusions[0]['test_ids']), 3)
        self.assertEqual(len(comparisons), 3)
        self.assertTrue(all('校准' in c['basis'] for c in comparisons))

    def test_calendar_does_not_become_overall_independence_p(self):
        tests = [leaf('mann_whitney', .01), leaf('datetime_features', .02, suffix='.weekday'),
                 leaf('datetime_features', .9, suffix='.month')]
        conclusions, comparisons = self.explain(tests)
        c = next(c for c in conclusions if c['question'] == '日历模式')
        self.assertEqual(c['test_ids'], ['datetime_features.weekday','datetime_features.month'])
        self.assertIn('weekday', c['summary']); self.assertIn('month', c['summary'])
        self.assertTrue(any('整体' in s for s in c['limitations']))
        self.assertEqual(comparisons[0]['evidence_relation'], 'not_comparable')

    def test_single_method_descriptive_and_unavailable_reasons(self):
        conclusions, comparisons = self.explain([leaf('spearman', None)], unavailable=[('pearson','N<3')])
        self.assertEqual([c['status'] for c in conclusions], ['descriptive_only','not_applicable'])
        self.assertIn('置换已禁用', conclusions[0]['summary'])
        self.assertIn('N<3', conclusions[1]['summary'])
        self.assertEqual(comparisons[0]['evidence_relation'], 'incomplete')
        conclusions, comparisons = self.explain([leaf('spearman', .01)])
        self.assertEqual(conclusions[0]['status'], 'evidence')
        self.assertFalse(comparisons)


class EngineInferenceTests(unittest.TestCase):
    def test_effects_and_calibration_do_not_add_family_members(self):
        result = analyze(['a']*4+['b']*4, ['a']*3+['b']+['a']+['b']*3, ('categorical','categorical'))
        self.assertEqual(result['multiplicity']['m'], 3)
        self.assertGreater(len(result['effects']), 3)
        self.assertEqual(result['multiplicity']['test_ids'], ['chi_square','fisher_exact','g_test'])
        self.assertEqual(result['inference_status'], 'adjusted')
        self.assertTrue(all(t['p_adjusted'] >= t['p_value'] for t in result['tests']))
        self.assertTrue(all(c['direction_agreement'] == 'same' for c in result['comparisons']))
        self.assertTrue(all(len(c['directions']) == 2 for c in result['comparisons']))

    def test_binary_ordinal_compares_u_with_both_related_rank_correlations(self):
        result = analyze(['a', 'b']*20, ['低','中','高','高']*10, ('categorical','ordinal'))
        pairs = {frozenset(c['method_ids']): c for c in result['comparisons']}
        self.assertEqual(len(pairs), 3)
        for rank in ('spearman', 'kendall_tau_b'):
            c = pairs[frozenset(('mann_whitney', rank))]
            self.assertIn('等价或高度相关', c['explanation'])
            self.assertEqual(len(c['directions']), 2)

    def test_nominal_ordinal_compares_order_using_kw_with_order_ignoring_chi(self):
        result = analyze(['a','b','c']*20, ['低','中','高','中','高','低']*10, ('categorical','ordinal'))
        self.assertEqual(len(result['comparisons']), 1)
        c = result['comparisons'][0]
        self.assertEqual(c['method_ids'], ['kruskal_wallis','chi_square'])
        self.assertIn('忽略顺序', c['basis'])
        self.assertEqual(c['direction_agreement'], 'not_comparable')
        self.assertEqual({c['question'] for c in result['conclusions']}, {'多组秩分布','类别分布与独立性'})

    def test_date_leaves_and_timestamp_rank_share_one_family(self):
        result = analyze(pd.date_range('2024-01-01', periods=24), ['a','b','c']*8, ('datetime','categorical'))
        tests = [t for t in result['tests'] if t['p_value'] is not None]
        self.assertGreater(len(tests), 1)
        self.assertEqual(result['multiplicity']['m'], len(tests))
        self.assertTrue(all(t['family_id'] == 'request' for t in tests))
        self.assertIn('kruskal_wallis', result['multiplicity']['test_ids'])
        self.assertTrue(any(tid.startswith('datetime_features.') for tid in result['multiplicity']['test_ids']))
        self.assertFalse(any('bonferroni' in key for t in result['tests'] for key in t))

    def test_plan_does_not_change_when_p_values_change(self):
        original = st.pearson
        first = analyze(np.arange(40), np.arange(40)**2)
        with patch.object(st, 'pearson', side_effect=lambda *a, **kw: replace(original(*a, **kw), p=.99)):
            second = analyze(np.arange(40), np.arange(40)**2)
        self.assertEqual(first['method_plan'], second['method_plan'])
        self.assertEqual([m['id'] for m in first['methods']], [m['id'] for m in second['methods']])
        self.assertEqual(len(second['tests']), 3)
        self.assertEqual(second['tests'][0]['p_value'], .99)
        self.assertFalse(second['tests'][0]['reject_adjusted'])
        self.assertEqual(second['tests'][0]['p_adjusted'], .99)

    def test_symmetric_u_shape_zero_correlations_do_not_prove_independence(self):
        x = np.arange(-20,21)
        result = analyze(x, x*x)
        self.assertTrue(all(abs(e['value']) < 1e-12 for e in result['effects']))
        self.assertTrue(all(c['status'] == 'insufficient_evidence' for c in result['conclusions']))
        self.assertTrue(all(any('非单调' in s and '不能排除' in s for s in c['limitations']) for c in result['conclusions']))
        self.assertTrue(all('证据不足' in c['summary'] for c in result['conclusions']))

    def test_all_descriptive_and_no_tests_have_empty_family(self):
        for result in [analyze([1,2,3],[3,1,2], methods='spearman,kendall_tau_b', permutations=0),
                       analyze([1,2],[2,1])]:
            self.assertEqual(result['multiplicity']['m'], 0)
            self.assertEqual(result['inference_status'], 'descriptive_only')
            self.assertTrue(result['conclusions'])
            self.assertTrue(all(t['reject_adjusted'] is None for t in result['tests']))
            json.dumps(result, allow_nan=False)

    def test_single_method_family_and_individual_interval_scope(self):
        result = analyze(np.arange(40), np.arange(40)**2, methods='pearson')
        self.assertEqual(result['multiplicity']['m'], 1)
        self.assertEqual(result['tests'][0]['p_value'], result['tests'][0]['p_adjusted'])
        self.assertEqual(result['effects'][0]['interval']['scope'], 'individual')
        self.assertTrue(any('单项' in s and '同时' in s for s in result['conclusions'][0]['limitations']))
        self.assertFalse(result['comparisons'])


class CliInferenceTests(unittest.TestCase):
    def test_representative_scenarios_save_all_evidence_and_explanations(self):
        rng = np.random.default_rng(91)
        scenarios = [
            ({'x':np.linspace(0,3,60), 'y':np.exp(np.linspace(0,3,60))}, ['numeric','numeric']),
            ({'x':['低','中','高']*20, 'y':np.tile([1,2,3],20)+rng.normal(0,.2,60)}, ['ordinal','numeric']),
            ({'x':np.r_[rng.normal(0,1,20),rng.normal(1,4,20),rng.normal(4,8,20)], 'y':['a']*20+['b']*20+['c']*20}, ['numeric','categorical']),
            ({'x':['a']*5+['b']*4+['c']*3, 'y':['u','v','w']*4}, ['categorical','categorical']),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i,(data,kinds) in enumerate(scenarios):
                with self.subTest(scenario=i):
                    path=root/f'data{i}.csv'; pd.DataFrame(data).to_csv(path,index=False)
                    argv=['analyze','--input',str(path),'--col1','x','--col2','y','--col1-type',kinds[0],
                          '--col2-type',kinds[1],'--permutations','29','--seed','91','--no-chart','--out',str(root/f'out{i}')]
                    if kinds[0]=='ordinal': argv+=['--col1-order','["低","中","高"]']
                    result=dr.cmd_analyze(dr.build_parser().parse_args(argv))
                    saved=json.loads(Path(result['result_path']).read_text(),parse_constant=lambda x:self.fail(x))
                    self.assertEqual(saved,result)
                    report=Path(result['report_md_path']).read_text()
                    self.assertIn('Holm',report)
                    self.assertNotIn('尚未作请求级校正',report)
                    for t in result['tests']:
                        self.assertIn(t['id'],report)
                        if t['p_value'] is not None:
                            self.assertEqual(t['family_id'],'request')
                            self.assertIsNotNone(t['p_adjusted'])
                    for c in result['conclusions']:
                        self.assertIn(dr.reports.FINDING_STATUS[c['status']],report)
                        for reference in c['test_ids'] + c['effect_ids']:
                            self.assertIn(reference,report)
                    report_json = [json.loads(block) for block in re.findall(
                        r'^```json\n(.*?)\n```$', report, re.MULTILINE | re.DOTALL)]
                    for c in result['comparisons']:
                        self.assertIn(json.loads(dr.reports.json_text(c)),report_json)
                    self.assertTrue({'method','method_label','reason','metrics','interpretation'}.isdisjoint(result))
                    for t in result['tests']:
                        line=next(line for line in report.splitlines() if line.startswith(f"| {t['id']} |") and line.count("|") >= 11)
                        cells=[cell.strip() for cell in line.strip('|').split('|')]
                        for field,index in [('p_value',5),('p_adjusted',6)]:
                            if t[field] is None:
                                self.assertEqual(cells[index],'—')
                            else:
                                self.assertEqual(cells[index],dr.reports.format_value(t[field]))

    def test_calendar_csv_uses_request_holm_values_directly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/'dates.csv'
            pd.DataFrame({'time':pd.date_range('2024-01-01',periods=30), 'g':['a','b','c']*10}).to_csv(path,index=False)
            argv=['analyze','--input',str(path),'--col1','time','--col2','g','--col1-type','datetime',
                  '--col2-type','categorical','--permutations','17','--seed','8','--no-chart','--out',str(root/'out')]
            result=dr.cmd_analyze(dr.build_parser().parse_args(argv))
            csv=pd.read_csv(Path(result['out_dir'])/'datetime_features.csv')
            leaves={t['feature']:t for t in result['tests'] if t['method_id']=='datetime_features'}
            for row in csv.to_dict('records'):
                t=leaves[row['feature']]
                self.assertAlmostEqual(row['p_adjusted'],t['p_adjusted'])
                self.assertEqual(row['reject_adjusted'],t['reject_adjusted'])
                self.assertEqual(row['family_id'],'request')
            self.assertNotIn('p_bonferroni',csv.columns)


if __name__ == '__main__':
    unittest.main()
