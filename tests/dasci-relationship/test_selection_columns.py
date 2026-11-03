"""Field catalog, physical headers and exact two-column selection."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr


class ColumnSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def inspect(self, path, *extra):
        return dr.cmd_inspect(dr.build_parser().parse_args(['inspect', '--input', str(path), *extra]))

    def analyze(self, path, *extra):
        return dr.cmd_analyze(dr.build_parser().parse_args(['analyze', '--input', str(path), '--no-chart',
                              '--out', str(self.root / 'out'), *extra]))

    def test_65_column_pages_search_and_preview_preserve_physical_position(self):
        path = self.root / 'wide.csv'
        pd.DataFrame({f'字段 {i}': range(i, i + 8) for i in range(1, 66)}).to_csv(path, index=False)
        first = self.inspect(path)
        self.assertEqual(len(first['columns']), 20)
        self.assertEqual(first['column_catalog']['total'], 65)
        self.assertEqual(len(first['preview']['rows']), 5)
        self.assertEqual(len(first['preview']['rows'][0]), 20)
        last = self.inspect(path, '--page', '4')
        self.assertEqual([c['index'] for c in last['columns']], [61, 62, 63, 64, 65])
        self.assertEqual(last['preview']['rows'][0][-1], '65')
        found = self.inspect(path, '--search', '字段 65')
        self.assertEqual(found['columns'][0]['index'], 65)
        self.assertEqual(found['preview']['columns'][0]['index'], 65)
        all_columns = self.inspect(path, '--all-columns')
        self.assertEqual(len(all_columns['columns']), 65)
        excluded = self.inspect(path, '--exclude-index', '65', '--all-columns')
        self.assertNotIn(65, [c['index'] for c in excluded['columns']])
        result = self.analyze(path, '--col1-index', '1', '--col2-index', '65')
        self.assertEqual(result['col2']['original_name'], '字段 65')
        self.assertEqual(result['col2']['index'], 65)

    def test_csv_excel_headers_retain_duplicates_blank_and_literal_pandas_suffix(self):
        headers = [' 名称 ', '重复', '重复', '', '重复.1', '含,逗号', 'Unnamed: real']
        frame = pd.DataFrame([[i+j for j in range(7)] for i in range(1, 9)], columns=headers)
        for suffix in ('.csv', '.xlsx'):
            with self.subTest(suffix=suffix):
                path = self.root / f'headers{suffix}'
                sheet = []
                if suffix == '.xlsx':
                    frame.to_excel(path, index=False, sheet_name='表 1'); sheet = ['--sheet', '表 1']
                else:
                    frame.to_csv(path, index=False)
                result = self.inspect(path, *sheet)
                cols = result['columns']
                self.assertEqual([c['original_name'] for c in cols], [*headers[:3], None if suffix == '.xlsx' else '', *headers[4:]])
                self.assertEqual([c['index'] for c in cols], list(range(1, 8)))
                self.assertEqual(len(set(c['display_name'] for c in cols)), 7)
                self.assertEqual(cols[-1]['display_name'], 'Unnamed: real')
                with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('statistics ran')):
                    with self.assertRaises(dr.UserError) as cm:
                        self.analyze(path, *sheet, '--col1', '重复', '--col2-index', '7')
                    self.assertEqual(cm.exception.payload['step'], 'needs_columns')
                selected = self.analyze(path, *sheet, '--col1-index', '3', '--col2', '含,逗号')
                self.assertEqual(selected['col1']['original_name'], '重复')
                self.assertEqual(selected['col1']['index'], 3)
                self.assertEqual(selected['col2']['index'], 6)

    def test_name_index_conflicts_same_column_ambiguity_and_missing_name_stop_before_statistics(self):
        path = self.root / 'data.csv'
        pd.DataFrame({'Name': range(8), 'NAME': range(8, 16), 'with space': range(16, 24)}).to_csv(path, index=False)
        failures = [('--col1', 'Name', '--col1-index', '2', '--col2-index', '3'),
                    ('--col1', 'missing', '--col1-index', '1', '--col2-index', '3'),
                    ('--col1', 'name', '--col2-index', '3'),
                    ('--col1-index', '1', '--col2', 'Name'),
                    ('--col1-index', '0', '--col2-index', '3')]
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('statistics ran')):
            for extra in failures:
                with self.subTest(extra=extra), self.assertRaises(dr.UserError) as cm:
                    self.analyze(path, *extra)
                self.assertEqual(cm.exception.payload['step'], 'needs_columns')
        valid = self.analyze(path, '--col1', 'Name', '--col1-index', '1', '--col2', 'with space')
        self.assertEqual(valid['col1']['index'], 1)
        self.assertEqual(valid['col2']['index'], 3)

    def test_samples_status_suggestions_and_source_values_are_visible(self):
        path = self.root / 'status.csv'
        pd.DataFrame({'customer_id': range(100, 160), 'empty': [None]*60, 'constant': ['same']*60,
                      'free': [f'long free text {i} '+ '字'*100 for i in range(60)],
                      '部门': [10, 20, 30]*20, '等级': ['低', '中', '高']*20,
                      'amount': range(60)}).to_csv(path, index=False)
        result = self.inspect(path)
        cols = result['columns']
        for c in cols[:4]:
            self.assertFalse(c['selectable'])
            self.assertTrue(c['reason'])
        self.assertEqual(cols[4]['suggested_kind'], 'categorical')
        self.assertEqual(cols[5]['suggested_kind'], 'ordinal')
        self.assertTrue(all(len(c['sample']) <= 3 and all(len(v) <= 60 for v in c['sample']) for c in cols))
        self.assertIn('…', cols[3]['sample'][0])
        for index in (1, 2, 3, 4):
            with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('statistics ran')):
                with self.assertRaises(dr.UserError):
                    self.analyze(path, '--col1-index', str(index), '--col2-index', '7')
        overridden = self.analyze(path, '--col1-index', '1', '--col1-type', 'numeric', '--col2-index', '7')
        self.assertEqual(overridden['col1']['inferred_kind'], 'id')
        self.assertEqual(overridden['col1']['type_source'], 'user')

    def test_type_overrides_and_ordinal_order_keep_header_mapping(self):
        path = self.root / 'types.csv'
        pd.DataFrame({'部门': [10, 20, 30]*4, '等级': ['低', '中', '高']*4}).to_csv(path, index=False)
        result = self.analyze(path, '--col1', '部门', '--col1-type', 'categorical',
                              '--col2-index', '2', '--col2-type', 'ordinal', '--col2-order', '["低","中","高"]',
                              '--permutations', '3')
        self.assertEqual(result['col1']['original_name'], '部门')
        self.assertEqual(result['col2']['original_name'], '等级')
        self.assertEqual(result['col2']['display_name'], '等级')
        self.assertEqual(result['col2']['effective_kind'], 'ordinal')
        self.assertEqual([v['value'] for v in result['col2']['levels']], ['低', '中', '高'])
        self.assertEqual(result['method_plan']['candidate_ids'], ['kruskal_wallis', 'chi_square'])
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('statistics ran')):
            with self.assertRaises(dr.UserError):
                self.analyze(path, '--col1-index', '1', '--col2-index', '2', '--col2-type', 'ordinal')


if __name__ == '__main__':
    unittest.main()
