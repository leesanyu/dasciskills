"""Report structure retains one complete, immutable analysis without recomputation."""
from copy import deepcopy
import itertools
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import reporting as report
import plotting
from test_statistics_methods import make_pair, KINDS


def result_for(kind1='numeric', kind2='numeric', *, n=40, permutations=3):
    frame, columns = make_pair(kind1, kind2, n)
    analysis, chart, extra = dr.multi.analyze_pair(*columns, permutations=permutations)
    result = {'input_path': '/数据/销售.csv', 'sheet': None, 'sheet_index': None, 'format': 'csv',
              'col1': columns[0].profile(), 'col2': columns[1].profile(), 'n': n,
              'total_rows': n, 'missing_pairs': 0, 'alpha': .05,
              'cleaning': dr.prepare_pair(frame, *columns), 'assumptions': ['观测独立；不是因果'],
              'warnings': ['测试警告'], **analysis}
    result['plot'] = plotting.resolve_plan([result['col1'], result['col2']])
    return result, chart, extra


class ReportModelTests(unittest.TestCase):
    def test_all_15_pairs_preserve_complete_analysis_and_never_compute_statistics(self):
        for kinds in itertools.combinations_with_replacement(KINDS, 2):
            with self.subTest(kinds=kinds):
                result, chart, extra = result_for(*kinds)
                original = deepcopy(result)
                with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('report recomputed statistics')):
                    model = report.build_model(result, chart, extra, report_id='fixed', generated_at='2026-11-02T00:00:00Z')
                self.assertEqual(result, original)
                for key in ('method_plan', 'methods', 'tests', 'effects', 'multiplicity', 'conclusions', 'comparisons', 'assumptions', 'warnings'):
                    self.assertEqual(model[key], result[key])
                self.assertEqual(model['columns'], [result['col1'], result['col2']])
                self.assertEqual(model['source']['cleaning'], result['cleaning'])
                self.assertEqual([s['id'] for s in model['sections']], report.SECTION_IDS)
                self.assertEqual(model['html_template'], {'id': 'data-relationship-report', 'version': '1.4.1'})
                mapped = {mid for figure in model['figures'] for mid in figure['method_ids']}
                self.assertEqual(mapped, {m['id'] for m in result['methods']})
                model['methods'][0]['label'] = 'changed'
                self.assertEqual(result, original)

    def test_comparison_rows_reference_every_leaf_and_do_not_invent_container_p(self):
        result, chart, extra = result_for('boolean', 'datetime')
        model = report.build_model(result, chart, extra)
        overview = next(t for t in model['tables'] if t['id'] == 'method-overview')
        for test in result['tests']:
            row = next(row for row in overview['rows'] if row[1] == test['id'])
            self.assertIn(test['p_value'], row)
            self.assertIn(test['p_adjusted'], row)
        self.assertEqual(len(overview['rows']), sum(max(1, len(m['test_ids'])) for m in result['methods']))
        self.assertGreater(len(model['figures']), 1)
        self.assertIn('datetime_features.csv', [a['path'] for a in model['attachments']])

    def test_ordinal_order_is_preserved_without_equal_interval_axes(self):
        for kinds in [('ordinal','ordinal'), ('numeric','ordinal'), ('boolean','ordinal'), ('ordinal','datetime')]:
            with self.subTest(kinds=kinds):
                result, chart, extra = result_for(*kinds)
                model = report.build_model(result, chart, extra)
                self.assertNotEqual(model['figures'][0]['spec']['kind'], 'scatter')
                self.assertIn('顺序', model['figures'][0]['caption'])
                for c in model['columns']:
                    if c['effective_kind'] == 'ordinal':
                        self.assertEqual([v['value'] for v in c['levels']], ['低','中','高','未观察'])
                spec = model['figures'][0]['spec']
                labels = spec.get('labels', spec.get('row_labels', spec.get('category_order', [])))
                self.assertEqual(labels[:3], ['低','中','高'])

    def test_summary_and_unavailable_methods_use_actual_counts_and_nulls(self):
        result, chart, extra = result_for(n=2, permutations=0)
        model = report.build_model(result, chart, extra)
        self.assertEqual(model['summary']['m'], result['multiplicity']['m'])
        self.assertEqual(model['summary']['computed_methods'], sum(m['status'] != 'not_applicable' for m in result['methods']))
        self.assertEqual(model['summary']['inference_status'], 'descriptive_only')
        self.assertEqual(len(model['methods']), 3)
        self.assertTrue(all(t['p_adjusted'] is None for t in model['tests']))

    def test_shared_figure_and_caption_include_scope_and_original_column_mapping(self):
        result, chart, extra = result_for()
        model = report.build_model(result, chart, extra)
        self.assertEqual(len(model['figures']), 1)
        self.assertEqual(model['figures'][0]['method_ids'], ['pearson','spearman','kendall_tau_b'])
        self.assertIn('统计使用完整配对数据', model['figures'][0]['caption'])
        self.assertIn('x', model['figures'][0]['alt'])
        self.assertIsNone(model['figures'][0]['asset_path'])

    def test_tables_are_bounded_and_full_attachments_are_listed(self):
        result, chart, extra = result_for('categorical','categorical')
        import pandas as pd
        extra['table'] = pd.DataFrame([[1]*15]*16, index=[f'行{i}' for i in range(16)], columns=[f'列{i}' for i in range(15)])
        model = report.build_model(result, chart, extra)
        table = next(t for t in model['tables'] if t['id'] == 'contingency')
        self.assertEqual(len(table['rows']), 10)
        self.assertEqual(len(table['headers']), 11)
        self.assertIn('16 × 15', table['note'])
        self.assertIn('contingency.csv', [a['path'] for a in model['attachments']])

    def test_format_value_preserves_missing_direction_and_interval_values(self):
        self.assertEqual(report.format_value(None), '—')
        self.assertEqual(report.format_value(.0000123456789), '0.000012')
        self.assertEqual(report.format_value(False), '否')
        self.assertIn('0.9500', report.format_value({'level':.95,'low':-.2,'high':.3}))

    def test_display_precision_handles_small_values_without_rounding_nonzero_to_zero(self):
        for value,expected in [(1.23456789,'1.2346'),(-.12345678,'-0.1235'),
                               (.00001234,'0.000012'),(4.035388244e-67,'4.0354e-67'),
                               (-1e-9,'-1.0000e-09'),(-0.0,'0.0000'),(1000000000.123,'1.0000e+09')]:
            with self.subTest(value=value):self.assertEqual(report.format_value(value),expected)
        self.assertEqual(report.format_value(33746),'33746')
        self.assertEqual(report.format_value('列名 1.23456789'),'列名 1.23456789')
        value={'range':[-.123456789,.987654321],'p':4.035388244e-67,'ok':True,'missing':None}
        original=deepcopy(value)
        import json
        shown=json.loads(report.format_value(value))
        self.assertEqual(shown['range'],[-.1235,.9877])
        self.assertGreater(shown['p'],0)
        self.assertIs(shown['ok'],True)
        self.assertEqual(value,original)


if __name__ == '__main__':
    unittest.main()
