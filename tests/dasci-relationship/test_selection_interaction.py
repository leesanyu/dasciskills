"""Executable conversations, local corrections and host-independent readiness."""
from copy import deepcopy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import data_relationship as dr
import interaction as flow


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.csv = self.root / '原始 数据.csv'
        self.excel = self.root / '多表.xlsx'
        self.frame = pd.DataFrame({'金额': list(range(12)), '含,逗号': [2*i+3 for i in range(12)],
                                   '等级': ['低', '中', '高']*4, 'constant': ['x']*12})
        self.frame.to_csv(self.csv, index=False)
        with pd.ExcelWriter(self.excel) as writer:
            self.frame.to_excel(writer, sheet_name='第一表', index=False)
            self.frame.to_excel(writer, sheet_name='第二表', index=False)

    def advance(self, state=None, action=None, **extra):
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('selection computed statistics')):
            return flow.advance({'state': state or {}, 'action': action or {}, **extra})

    def selected(self):
        return self.advance(action={'input': str(self.csv), 'columns': {'1': {'index': 1}, '2': {'index': 2}}})

    def test_frozen_dialogues_reach_only_confirmed_ready_and_execute_exact_argv(self):
        scripts = json.loads((Path(__file__).parent / 'fixtures/selection_dialogues.json').read_text())
        transcripts = []
        evidence = os.environ.get('SELECTION_DIALOGUE_EVIDENCE')
        artifact_root = Path(evidence).parent / 'dialogues' if evidence else self.root
        artifact_root.mkdir(parents=True, exist_ok=True)
        for script in scripts:
            with self.subTest(dialogue=script['id']):
                state, questions, turns = {}, 0, []
                for turn in script['turns']:
                    action = deepcopy(turn['action'])
                    if action.get('input') == '$file':
                        source = self.csv if script['file'] == 'csv' else self.excel
                        if evidence:
                            target = artifact_root / source.name
                            shutil.copyfile(source, target)
                            source = target
                        action['input'] = str(source)
                    result = self.advance(state, action, host=script.get('host', {'questions': True, 'multi_select': True, 'max_options': 20}))
                    self.assertEqual(result['step'], turn['step'])
                    self.assertTrue(result['ok'], result)
                    if result['question']:
                        questions += 1
                        self.assertEqual(result['question']['mode'], turn.get('mode', 'tool'))
                        self.assertIsNone(result['analysis_args'])
                    else:
                        self.assertEqual(result['step'], 'ready')
                    state = result['state']; turns.append({'request': action, 'response': result})
                self.assertEqual(questions, script['questions'])
                self.assertTrue(state['confirmed'])
                self.assertEqual(result['summary']['method_plan']['candidate_ids'], script['methods'])
                argv = result['analysis_args'] + ['--out', str(artifact_root / script['id']), '--no-chart', '--permutations', '3']
                analyzed = dr.cmd_analyze(dr.build_parser().parse_args(argv))
                self.assertEqual(analyzed['method_plan']['candidate_ids'], script['methods'])
                self.assertEqual(analyzed['plot'], result['summary']['plot'])
                self.assertEqual(argv[argv.index('--plot-x')+1], state['plot_x'])
                for number in (1, 2):
                    self.assertEqual(analyzed[f'col{number}']['index'], state['columns'][number-1]['index'])
                    self.assertEqual(analyzed[f'col{number}']['original_name'], state['columns'][number-1]['original_name'])
                transcripts.append({'id': script['id'], 'questions': questions, 'turns': turns, 'executed_argv': argv, 'result_path': analyzed['result_path']})
        # Optional evidence location is set by the Feature acceptance runner.
        if os.environ.get('SELECTION_DIALOGUE_EVIDENCE'):
            Path(os.environ['SELECTION_DIALOGUE_EVIDENCE']).write_text(json.dumps(transcripts, ensure_ascii=False, indent=2))

    def test_no_input_requests_only_file_and_no_default_submission(self):
        result = self.advance()
        self.assertEqual(result['step'], 'needs_file')
        self.assertIsNone(result['analysis_args'])
        default = self.advance(result['state'], {'input': str(self.csv), 'source': 'default', 'confirm': True})
        self.assertEqual(default['step'], 'needs_file')
        selected = self.selected()
        default = self.advance(selected['state'], {'confirm': True, 'source': 'default'})
        self.assertEqual(default['step'], 'needs_confirmation')
        self.assertFalse(default['state']['confirmed'])

    def test_local_column_error_keeps_other_slot_and_excludes_it(self):
        result = self.selected()
        first = deepcopy(result['state']['columns'][0])
        bad = self.advance(result['state'], {'columns': {'2': {'index': 1}}})
        self.assertEqual(bad['step'], 'needs_columns')
        self.assertFalse(bad['ok'])
        self.assertEqual(bad['state']['columns'][0], first)
        self.assertIsNone(bad['state']['columns'][1])
        self.assertNotIn(1, [c['index'] for c in bad['catalog']['items']])
        self.assertNotIn(1, [c['index'] for c in bad['preview']['columns']])
        repaired = self.advance(bad['state'], {'columns': {'2': {'name': '含,逗号'}}})
        self.assertEqual(repaired['step'], 'needs_confirmation')
        self.assertEqual(repaired['state']['columns'][0], first)

    def test_changing_sheet_or_file_clears_bound_columns(self):
        result = self.advance(action={'input': str(self.excel), 'sheet': {'name': '第一表'},
                                      'columns': {'1': {'index': 1}, '2': {'index': 2}}, 'explicit': True})
        self.assertEqual(result['step'], 'ready')
        changed = self.advance(result['state'], {'sheet': {'index': 2}})
        self.assertEqual(changed['step'], 'needs_columns')
        self.assertEqual(changed['state']['columns'], [None, None])
        changed = self.advance(result['state'], {'input': str(self.csv)})
        self.assertIsNone(changed['state']['sheet'])
        self.assertEqual(changed['state']['columns'], [None, None])

    def test_supplied_column_names_survive_until_missing_sheet_is_chosen(self):
        initial = self.advance(action={'input': str(self.excel), 'columns': {'1': {'name': '金额'}, '2': {'name': '含,逗号'}}})
        self.assertEqual(initial['step'], 'needs_sheet')
        chosen = self.advance(initial['state'], {'sheet': {'index': 2}})
        self.assertEqual(chosen['step'], 'needs_confirmation')
        self.assertEqual([col['index'] for col in chosen['state']['columns']], [1, 2])

    def test_new_identity_drops_previous_ordinal_semantics_and_confirmation(self):
        pending = self.advance(action={'input': str(self.csv), 'columns': {'1': {'index': 3, 'type': 'ordinal', 'order': ['低', '中', '高']},
                                                                         '2': {'index': 2}}})
        ready = self.advance(pending['state'], {'confirm': True})
        self.assertEqual(ready['step'], 'ready')
        changed = self.advance(ready['state'], {'columns': {'1': {'index': 1}}, 'confirm': True})
        self.assertEqual(changed['step'], 'needs_confirmation')
        self.assertFalse(changed['state']['confirmed'])
        self.assertEqual(changed['state']['columns'][0]['type'], 'auto')
        self.assertIsNone(changed['state']['columns'][0]['order'])

    def test_semantics_and_method_errors_preserve_valid_columns_and_can_be_corrected(self):
        pending = self.advance(action={'input': str(self.csv), 'columns': {'1': {'index': 3}, '2': {'index': 1}}})
        self.assertEqual(pending['step'], 'needs_semantics')
        pending = self.advance(pending['state'], {'columns': {'1': {'type': 'ordinal', 'order': ['低']}}})
        self.assertEqual(pending['step'], 'needs_semantics')
        repaired = self.advance(pending['state'], {'columns': {'1': {'order': ['低', '中', '高']}}})
        self.assertEqual(repaired['step'], 'needs_confirmation')
        bad = self.advance(repaired['state'], {'methods': 'chi_square'})
        self.assertEqual(bad['step'], 'needs_semantics')
        self.assertEqual([c['index'] for c in bad['state']['columns']], [3, 1])
        fixed = self.advance(bad['state'], {'methods': 'spearman'})
        self.assertEqual(fixed['summary']['method_plan']['candidate_ids'], ['spearman'])
        self.assertEqual(fixed['step'], 'needs_confirmation')

    def test_constant_requires_reselection_and_invalid_request_does_not_run_statistics(self):
        result = self.advance(action={'input': str(self.csv), 'columns': {'1': {'index': 1}, '2': {'index': 4}}})
        self.assertEqual(result['step'], 'needs_columns')
        self.assertEqual(result['state']['columns'][0]['index'], 1)
        self.assertIsNone(result['state']['columns'][1])
        self.assertIsNone(result['analysis_args'])
        for request in [{'action': {'surprise': 1}}, {'action': {'columns': [1, 2]}},
                        {'action': {'confirm': 'yes'}}, {'state': {'columns': []}},
                        {'host': {'max_options': 0}}, {'action': {'columns': {'1': {'index': True}}}}]:
            with self.subTest(request=request), self.assertRaises(dr.UserError):
                flow.advance(request)

    def test_field_form_uses_native_questions_independently_of_multiselect(self):
        for host in ({'questions': False}, {'questions': True, 'multi_select': False},
                     {'questions': True, 'multi_select': True, 'max_options': 2}):
            with self.subTest(host=host):
                result = self.advance(action={'input': str(self.csv)}, host=host)
                self.assertEqual(result['question']['mode'], 'tool' if host['questions'] else 'text')
                self.assertEqual(result['question']['options'], [])
                self.assertEqual(result['question']['submit_as'], 'pair')
        result = self.advance(action={'input': str(self.csv)}, host={'questions': True, 'multi_select': True, 'max_options': 20})
        self.assertEqual([q['id'] for q in result['question']['questions']], ['x','y'])

    def test_semantics_prompt_contains_actual_levels_even_outside_current_page(self):
        pending = self.advance(action={'input': str(self.csv), 'columns': {'1': {'index': 3}, '2': {'index': 1}}})
        self.assertEqual(pending['semantic_context']['slot'], 1)
        self.assertEqual(pending['semantic_context']['observed_levels'], ['低', '中', '高'])
        self.assertEqual(pending['question']['mode'], 'text')
        self.assertEqual(pending['question']['options'], [])

    def test_select_excel_field_paging_does_not_page_sheet_catalog(self):
        path = self.root / 'wide.xlsx'
        pd.DataFrame({f'v{i}': range(12) for i in range(65)}).to_excel(path, index=False)
        response = self.advance(action={'input': str(path), 'sheet': {'index': 1}}, view={'page': 4})
        self.assertEqual([c['index'] for c in response['catalog']['items']], [61, 62, 63, 64, 65])
        self.assertEqual(response['step'], 'needs_columns')

    def test_missing_file_preserves_supplied_sheet_columns_and_methods(self):
        pending = self.advance(action={'sheet': {'name': '第二表'}, 'columns': {'1': {'index': 1}, '2': {'index': 2}}, 'methods': 'spearman'})
        self.assertEqual(pending['step'], 'needs_file')
        chosen = self.advance(pending['state'], {'input': str(self.excel)})
        self.assertEqual(chosen['step'], 'needs_confirmation')
        self.assertEqual(chosen['summary']['sheet']['name'], '第二表')
        self.assertEqual(chosen['summary']['method_plan']['candidate_ids'], ['spearman'])

    def test_id_override_is_local_and_does_not_repeat_type_confirmation(self):
        path = self.root / 'id.csv'
        pd.DataFrame({'customer_id': range(100, 125), 'amount': range(25)}).to_csv(path, index=False)
        pending = self.advance(action={'input': str(path), 'columns': {'1': {'index': 1}, '2': {'index': 2}}})
        self.assertEqual(pending['step'], 'needs_semantics')
        corrected = self.advance(pending['state'], {'columns': {'1': {'type': 'numeric'}}})
        self.assertEqual(corrected['step'], 'needs_confirmation')
        ready = self.advance(corrected['state'], {'confirm': True})
        self.assertEqual(ready['step'], 'ready')
        again = self.advance(ready['state'])
        self.assertEqual(again['step'], 'ready')
        self.assertEqual(again['summary']['columns'][0]['type_source'], 'user')

    def test_editing_source_data_invalidates_previous_confirmation(self):
        pending = self.selected()
        ready = self.advance(pending['state'], {'confirm': True})
        self.assertEqual(ready['step'], 'ready')
        self.frame.iloc[:8].to_csv(self.csv, index=False)
        changed = self.advance(ready['state'])
        self.assertEqual(changed['step'], 'needs_confirmation')
        self.assertEqual(changed['summary']['n'], 8)
        self.assertFalse(changed['state']['confirmed'])

    def test_select_cli_accepts_state_and_outputs_only_ready_argv(self):
        request = self.root / 'request.json'
        request.write_text(json.dumps({'action': {'input': str(self.csv), 'columns': {'1': {'index': 1}, '2': {'index': 2}}, 'explicit': True}}))
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'data_relationship.py'), 'select', '--request', str(request)],
                              capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['step'], 'ready')
        self.assertEqual(result['analysis_args'][0], 'analyze')
        request.write_text('{broken')
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'data_relationship.py'), 'select', '--request', str(request)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
