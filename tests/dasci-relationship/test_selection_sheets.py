"""Stable workbook navigation and input-boundary behavior."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import selection as nav


class SheetSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / '中文 数据.xlsx'
        book = Workbook()
        book.active.title = '客户 数据'
        book.active.append(['x', 'y'])
        book.active.append([1, 2])
        book.active.append([2, 4])
        hidden = book.create_sheet('隐藏表')
        hidden.append(['x', 'y']); hidden.append([1, 2]); hidden.append([2, 3])
        hidden.sheet_state = 'hidden'
        book.create_sheet('空表')
        formatted = book.create_sheet('格式空表')
        formatted['G10'].number_format = '0.00'
        book.create_sheet('仅表头').append(['x', 'y'])
        for i in range(6, 26):
            ws = book.create_sheet(str(i))
            ws.append(['x', 'y']); ws.append([1, 2]); ws.append([2, 3])
        book.save(self.path); book.close()

    def inspect(self, *extra):
        return dr.cmd_inspect(dr.build_parser().parse_args(['inspect', '--input', str(self.path), *extra]))

    def test_catalog_paginates_25_sheets_and_keeps_source_indices(self):
        first = self.inspect()
        self.assertTrue(first['needs_sheet'])
        self.assertEqual(first['step'], 'needs_sheet')
        self.assertEqual(len(first['sheets']), 20)
        self.assertEqual(first['sheet_catalog']['total'], 25)
        self.assertTrue(first['sheet_catalog']['has_next'])
        last = self.inspect('--page', '2')
        self.assertEqual([s['index'] for s in last['sheets']], list(range(21, 26)))
        self.assertEqual(last['sheet_catalog']['start'], 21)
        found = self.inspect('--search', '25')
        self.assertEqual([s['index'] for s in found['sheets']], [25])
        self.assertEqual(found['sheet_catalog']['matched'], 1)

    def test_hidden_empty_and_formatted_empty_have_observed_states(self):
        sheets = dr.list_sheets(self.path)
        self.assertEqual(sheets[0]['rows'], 3)
        self.assertIn('估计', sheets[0]['dimension_note'])
        self.assertEqual(sheets[1]['state'], 'hidden')
        self.assertTrue(sheets[1]['selectable'])
        for option in sheets[2:5]:
            self.assertFalse(option['selectable'])
            self.assertEqual(option['content_status'], 'empty')
            self.assertTrue(option['reason'])
        result = self.inspect('--sheet-index', '2')
        self.assertFalse(result['needs_sheet'])
        self.assertEqual(result['sheet'], '隐藏表')
        self.assertTrue(any('隐藏' in warning for warning in result['warnings']))

    def test_name_number_and_hash_are_explicit_and_conflicts_fail(self):
        self.assertEqual(self.inspect('--sheet', '25')['sheet'], '25')
        self.assertEqual(self.inspect('--sheet', '#1')['sheet'], '客户 数据')
        self.assertEqual(self.inspect('--sheet', '客户 数据', '--sheet-index', '1')['sheet'], '客户 数据')
        for extra in [('--sheet', '25', '--sheet-index', '1'), ('--sheet-index', '26'),
                      ('--sheet', 'missing'), ('--sheet', '空表')]:
            with self.subTest(extra=extra), self.assertRaises(dr.UserError) as cm:
                self.inspect(*extra)
            self.assertEqual(cm.exception.payload['step'], 'needs_sheet')

    def test_casefold_ambiguity_is_never_silently_chosen(self):
        options = [{'index': 1, 'name': 'Data', 'selectable': True},
                   {'index': 2, 'name': 'DATA', 'selectable': True}]
        self.assertEqual(nav.resolve_option(options, name='Data', label='工作表', step='needs_sheet')['index'], 1)
        with self.assertRaises(dr.UserError):
            nav.resolve_option(options, name='data', label='工作表', step='needs_sheet')

    def test_paging_invalid_or_empty_search_and_unknown_dimensions(self):
        options = [{'index': 25, 'name': '未知', 'rows': None, 'columns': None, 'selectable': True}]
        page = nav.page_options(options)
        self.assertIsNone(page['items'][0]['rows'])
        self.assertEqual(nav.page_options(options, search='不存在')['items'], [])
        for n in (0, 2):
            with self.assertRaises(dr.UserError):
                nav.page_options(options, page=n)

    def test_analyze_uses_sheet_index_and_csv_skips_sheet_step(self):
        args = dr.build_parser().parse_args(['analyze', '--input', str(self.path), '--sheet-index', '1',
                                             '--col1-index', '1', '--col2-index', '2', '--no-chart',
                                             '--out', str(self.root / 'out')])
        result = dr.cmd_analyze(args)
        self.assertEqual(result['sheet'], '客户 数据')
        self.assertTrue(Path(result['result_path']).exists())
        path = self.root / 'data.csv'
        pd.DataFrame({'x': [1, 2], 'y': [2, 3]}).to_csv(path, index=False)
        inspected = dr.cmd_inspect(dr.build_parser().parse_args(['inspect', '--input', str(path)]))
        self.assertFalse(inspected['needs_sheet'])
        with self.assertRaises(dr.UserError):
            dr.cmd_inspect(dr.build_parser().parse_args(['inspect', '--input', str(path), '--sheet-index', '1']))

    def test_single_sheet_requires_explicit_choice_and_no_implicit_analysis(self):
        path = self.root / 'single.xlsx'
        pd.DataFrame({'x': [1, 2], 'y': [2, 3]}).to_excel(path, index=False)
        inspected = dr.cmd_inspect(dr.build_parser().parse_args(['inspect', '--input', str(path)]))
        self.assertTrue(inspected['needs_sheet'])
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('statistics ran')):
            with self.assertRaises(dr.NeedsSheet):
                dr.cmd_analyze(dr.build_parser().parse_args(['analyze', '--input', str(path), '--col1', 'x', '--col2', 'y']))


if __name__ == '__main__':
    unittest.main()
