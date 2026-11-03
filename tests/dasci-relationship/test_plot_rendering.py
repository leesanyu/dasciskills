"""Rendered axes refer to actual data; changing them preserves statistics."""
from copy import deepcopy
from pathlib import Path
import itertools
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import plotting
import plots
import reporting as report
from test_report_model import result_for
from test_statistics_methods import KINDS


class AxisRenderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def model(self, kinds, requested='auto'):
        result, chart, extra = result_for(*kinds)
        result['plot'] = plotting.resolve_plan([result['col1'], result['col2']], requested)
        return report.build_model(result, chart, extra), result, chart

    def test_all_ordered_pairs_and_both_axes_preserve_analysis_and_match_plan(self):
        for kinds in itertools.product(KINDS, repeat=2):
            for x in ('col1', 'col2'):
                with self.subTest(kinds=kinds, x=x):
                    result, chart, extra = result_for(*kinds)
                    result['plot'] = plotting.resolve_plan([result['col1'], result['col2']], x)
                    before, before_chart = deepcopy(result), deepcopy(chart)
                    with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('recomputed statistics')):
                        model = report.build_model(result, chart, extra)
                    self.assertEqual(result, before);self.assertEqual(chart, before_chart)
                    figure = model['figures'][0];plan = result['plot']
                    self.assertEqual(figure['axes'], {'x': plan['x'], 'y': plan['y']})
                    self.assertEqual(figure['spec']['kind'], plan['kind'])
                    for axis in ('x', 'y'):
                        self.assertEqual(figure['spec'][axis+'_label'], plan[axis]['label'])
                    for key in ('methods', 'tests', 'effects', 'conclusions', 'comparisons', 'multiplicity'):
                        self.assertEqual(model[key], result[key])

    def test_scatter_swaps_values_and_date_format_together(self):
        model, result, original = self.model(('numeric', 'datetime'), 'col2')
        spec = model['figures'][0]['spec']
        self.assertEqual(spec['x'], original['y']);self.assertEqual(spec['y'], original['x'])
        self.assertTrue(spec['x_date']);self.assertFalse(spec['y_date'])
        with patch.object(plots, 'scatter', wraps=plots.scatter) as draw:
            report.render_figures(model, self.root)
        np.testing.assert_array_equal(draw.call_args.args[0], original['y'])
        self.assertEqual(draw.call_args.kwargs['x_date'], True)

    def test_asymmetric_heatmap_transposes_display_only(self):
        result, chart, extra = result_for('categorical', 'ordinal')
        chart.update(table=[[1, 2, 3], [4, 5, 6]], row_labels=['a', 'b'], col_labels=['低', '中', '高'])
        result['plot'] = plotting.resolve_plan([result['col1'], result['col2']], 'col1')
        before = deepcopy(extra['table'])
        spec = report.build_model(result, chart, extra)['figures'][0]['spec']
        self.assertEqual(spec['table'], [[1, 4], [2, 5], [3, 6]])
        self.assertEqual(spec['row_labels'], ['低', '中', '高'])
        self.assertEqual(spec['col_labels'], ['a', 'b'])
        self.assertTrue(extra['table'].equals(before))

    def test_ordinal_group_order_is_preserved_in_both_box_orientations(self):
        for requested, orientation in [('col1', 'vertical'), ('col2', 'horizontal')]:
            model, _, _ = self.model(('ordinal', 'numeric'), requested)
            spec = model['figures'][0]['spec']
            self.assertEqual(spec['orientation'], orientation)
            self.assertEqual(spec['labels'], ['低', '中', '高', '未观察'])
            with patch.object(plots, 'boxplot', wraps=plots.boxplot) as draw:
                report.render_figures(model, self.root)
            self.assertEqual(draw.call_args.kwargs['orientation'], orientation)
            self.assertEqual(model['figures'][0]['status'], 'available')

    def test_time_in_y_uses_y_date_ticks_and_keeps_categories(self):
        model, _, _ = self.model(('datetime', 'categorical'), 'col2')
        spec = model['figures'][0]['spec']
        self.assertEqual(spec['time_axis'], 'y')
        with patch.object(plots, '_axes', wraps=plots._axes) as axes:
            report.render_figures(model, self.root)
        self.assertIs(axes.call_args_list[0].kwargs['y_formatter'], plots._date_label)
        self.assertFalse(axes.call_args_list[0].kwargs['show_x_ticks'])

    def test_calendar_figures_keep_their_own_feature_axes_after_primary_swap(self):
        normal, _, _ = self.model(('datetime', 'categorical'), 'col1')
        swapped, _, _ = self.model(('datetime', 'categorical'), 'col2')
        self.assertGreater(len(normal['figures']), 1)
        for a, b in zip(normal['figures'][1:], swapped['figures'][1:]):
            self.assertEqual(a['axes'], b['axes'])
            self.assertEqual(a['spec'], b['spec'])
            self.assertEqual(a['axes']['x']['slot'], 'col2')
            self.assertIsNotNone(a['axes']['y']['feature'])
            self.assertIn(a['axes']['y']['label'], a['caption'])

    def test_scatter_trend_line_is_fitted_in_display_coordinates(self):
        model, _, original = self.model(('numeric', 'numeric'), 'col2')
        with patch.object(np, 'polyfit', wraps=np.polyfit) as fit:
            report.render_figures(model, self.root)
        self.assertEqual(fit.call_count, 1)
        np.testing.assert_array_equal(fit.call_args.args[0], original['y'])
        np.testing.assert_array_equal(fit.call_args.args[1], original['x'])

    def test_real_pngs_differ_by_orientation_and_contain_untruncated_axis_footer(self):
        for kinds in [('numeric', 'numeric'), ('ordinal', 'numeric'), ('datetime', 'categorical'), ('categorical', 'ordinal')]:
            images = []
            for x in ('col1', 'col2'):
                model, _, _ = self.model(kinds, x)
                full = '很长的完整字段名称_'*12
                figure = model['figures'][0];figure['spec']['x_label'] = full
                with patch.object(plots, '_text', wraps=plots._text) as text:
                    report.render_figures(model, self.root)
                chunks = [str(call.args[2]) for call in text.call_args_list]
                self.assertIn(full, ''.join(chunks))
                self.assertEqual(figure['status'], 'available')
                path = self.root/figure['asset_path'];images.append(path.read_bytes())
                with Image.open(path) as image:
                    self.assertGreater(image.height, plots.HEIGHT)
                    image.verify()
            self.assertNotEqual(images[0], images[1])


if __name__ == '__main__':
    unittest.main()
