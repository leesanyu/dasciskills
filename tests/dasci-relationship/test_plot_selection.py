"""Axis intent is independent of statistical field identity and confirmation."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import interaction as flow
import plotting


class PlotPlanTests(unittest.TestCase):
    def columns(self, a, b):
        return [{'effective_kind': kind, 'index': index, 'display_name': name}
                for kind, index, name in [(a, 7, '温度'), (b, 3, '观测值')]]

    def test_all_type_pairs_resolve_expected_layout_without_computation(self):
        discrete = {'boolean', 'categorical', 'ordinal'}
        kinds = ['numeric', 'datetime', *sorted(discrete)]
        for a in kinds:
            for b in kinds:
                with self.subTest(kinds=(a, b)):
                    cols = self.columns(a, b)
                    if a in discrete and b in discrete:
                        kind, x = 'heatmap', 0
                    elif a in discrete or b in discrete:
                        measure = 1 if a in discrete else 0
                        kind, x = ('timeline' if cols[measure]['effective_kind'] == 'datetime' else 'box'), measure
                    else:
                        kind = 'scatter'
                        x = (0 if a == 'datetime' else 1) if (a == 'datetime') != (b == 'datetime') else 0
                    p = plotting.resolve_plan(cols)
                    self.assertEqual(p['kind'], kind)
                    self.assertEqual(p['x']['slot'], f'col{x+1}')
                    self.assertEqual(p['y']['slot'], f'col{2-x}')
                    self.assertEqual(p['x']['column_index'], cols[x]['index'])
                    self.assertEqual(p['x']['label'], cols[x]['display_name'])
                    self.assertIsNone(p['x']['feature'])
                    self.assertEqual(p['requested_x'], 'auto')

    def test_explicit_axis_overrides_type_defaults_and_preserves_columns(self):
        cols = self.columns('categorical', 'datetime');before = deepcopy(cols)
        plan = plotting.resolve_plan(cols, 'col1')
        self.assertEqual(plan['x']['slot'], 'col1')
        self.assertEqual(plan['kind'], 'timeline')
        self.assertEqual(plan['source'], 'explicit')
        self.assertEqual(cols, before)
        self.assertEqual(plotting.resolve_plan(cols)['source'], 'type_default')
        self.assertEqual(plotting.resolve_plan(self.columns('numeric', 'numeric'))['source'], 'slot_default')


class PlotSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.path = self.root/'data.csv'
        self.frame = pd.DataFrame({'温度': range(12), '观测值': [v*v+1 for v in range(12)],
                                   '等级': ['低', '中', '高']*4})
        self.frame.to_csv(self.path, index=False)

    def advance(self, state=None, action=None, **extra):
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('selection ran statistics')):
            return flow.advance({'state': state or {}, 'action': action or {}, **extra})

    def selected(self, **extra):
        return self.advance(action={'input': str(self.path), 'columns': {'1': {'index': 1}, '2': {'index': 2}}, **extra})

    def test_complete_input_preserves_request_and_cli_plan(self):
        for x in ('auto', 'col1', 'col2'):
            with self.subTest(plot_x=x):
                r = self.selected(plot_x=x, explicit=True)
                self.assertEqual(r['step'], 'ready');self.assertIsNone(r['question'])
                argv = r['analysis_args']
                self.assertEqual(argv[argv.index('--plot-x')+1], x)
                result = dr.cmd_analyze(dr.build_parser().parse_args(argv+['--no-chart', '--out', str(self.root/'out')]))
                self.assertEqual(result['plot'], r['summary']['plot'])
                self.assertEqual(result['col1']['index'], 1)
                self.assertEqual(result['col2']['index'], 2)

    def test_swap_invalidates_old_confirmation_without_changing_fields(self):
        initial = self.selected();ready = self.advance(initial['state'], {'confirm': True})
        changed = self.advance(ready['state'], {'plot_x': 'col2', 'confirm': True})
        self.assertEqual(changed['step'], 'needs_confirmation');self.assertIsNone(changed['analysis_args'])
        self.assertEqual(changed['state']['columns'], ready['state']['columns'])
        self.assertEqual(changed['summary']['plot']['x']['label'], '观测值')
        self.assertNotIn('交换横纵轴', [o['label'] for o in changed['question']['options']])
        self.assertEqual(self.advance(changed['state'], {'confirm': True})['step'], 'ready')

    def test_default_highlight_does_not_override_or_confirm(self):
        pending = self.selected()
        r = self.advance(pending['state'], {'plot_x': 'col2', 'confirm': True, 'source': 'default'})
        self.assertEqual(r['step'], 'needs_confirmation')
        self.assertEqual(r['state']['plot_x'], 'auto')

    def test_replacing_field_or_file_resets_axis_but_same_action_can_assign(self):
        initial = self.selected(plot_x='col2')
        order = ['低', '中', '高']
        patch_columns = {'1': {'index': 3, 'type': 'ordinal', 'order': order}}
        changed = self.advance(initial['state'], {'columns': patch_columns})
        self.assertEqual(changed['state']['plot_x'], 'auto')
        self.assertEqual(changed['summary']['plot']['kind'], 'box')
        assigned = self.advance(initial['state'], {'columns': patch_columns, 'plot_x': 'col1'})
        self.assertEqual(assigned['summary']['plot']['x']['label'], '等级')
        other = self.root/'other.csv';self.frame.to_csv(other, index=False)
        self.assertEqual(self.advance(initial['state'], {'input': str(other)})['state']['plot_x'], 'auto')

    def test_type_only_edits_preserve_explicit_axis_and_refresh_layout(self):
        initial = self.selected(plot_x='col1')
        changed = self.advance(initial['state'], {'columns': {'1': {'type': 'categorical'}}})
        self.assertEqual(changed['state']['plot_x'], 'col1')
        self.assertEqual(changed['summary']['plot']['kind'], 'box')
        self.assertEqual(changed['summary']['plot']['x']['label'], '温度')

    def test_method_change_and_paging_keep_axis(self):
        initial = self.selected(plot_x='col2')
        r = self.advance(initial['state'], {'methods': 'spearman'}, view={'page': 1})
        self.assertEqual(r['state']['plot_x'], 'col2')
        self.assertEqual(r['summary']['plot'], initial['summary']['plot'])
        self.assertNotEqual(r['state']['confirmation_key'], initial['state']['confirmation_key'])

    def test_invalid_axis_keeps_fields_and_never_returns_ready_args(self):
        initial = self.selected(plot_x='col2')
        r = self.advance(initial['state'], {'plot_x': 'missing', 'confirm': True})
        self.assertFalse(r['ok']);self.assertIsNone(r['analysis_args'])
        self.assertEqual(r['state']['columns'], initial['state']['columns'])
        self.assertEqual(r['state']['plot_x'], 'col2')

    def test_axis_intent_survives_missing_file_until_first_binding(self):
        r = self.advance(action={'plot_x': 'col2', 'columns': {'1': {'index': 1}, '2': {'index': 2}}})
        self.assertEqual(r['step'], 'needs_file')
        r = self.advance(r['state'], {'input': str(self.path)})
        self.assertEqual(r['summary']['plot']['x']['slot'], 'col2')

    def test_sheet_change_resets_axis(self):
        path = self.root/'two.xlsx'
        with pd.ExcelWriter(path) as writer:
            self.frame.to_excel(writer, sheet_name='a', index=False)
            self.frame.to_excel(writer, sheet_name='b', index=False)
        initial = self.advance(action={'input': str(path), 'sheet': {'index': 1}, 'plot_x': 'col2',
                                      'columns': {'1': {'index': 1}, '2': {'index': 2}}, 'explicit': True})
        r = self.advance(initial['state'], {'sheet': {'index': 2}})
        self.assertEqual(r['state']['plot_x'], 'auto')
        self.assertEqual(r['step'], 'needs_columns')


if __name__ == '__main__':
    unittest.main()
