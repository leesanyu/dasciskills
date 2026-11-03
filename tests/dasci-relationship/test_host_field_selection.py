"""An in-conversation form submits fields with explicit axis identities."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from bs4 import BeautifulSoup

SCRIPTS=Path(__file__).resolve().parents[2]/'skills'/'dasci-relationship'/'scripts'
sys.path.insert(0,str(SCRIPTS))
import data_relationship as dr
import interaction as flow


class NativeFieldSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'data.csv'
        pd.DataFrame({'温度':range(12),'含,逗号':[v*v for v in range(12)],
                      '<b>同名</b>':[v+3 for v in range(12)],'常量':[1]*12}).to_csv(self.path,index=False)

    def fields(self,host=None,**extra):
        with patch.object(dr.multi,'analyze_pair',side_effect=AssertionError('selection ran statistics')):
            return flow.advance({'action':{'input':str(self.path)},'host':host or {'questions':True},**extra})

    def test_two_single_select_questions_do_not_require_multiselect(self):
        r=self.fields({'questions':True,'multi_select':False,'max_questions':2,'max_options':20})
        q=r['question']
        self.assertEqual(q['mode'],'tool');self.assertEqual(q['submit_as'],'pair')
        self.assertEqual(q['options'],[]);self.assertIsNone(r['analysis_args'])
        self.assertEqual([item['id'] for item in q['questions']],['x','y'])
        for item in q['questions']:
            self.assertEqual((item['min_select'],item['max_select']),(1,1))
            self.assertEqual({opt['value']['index'] for opt in item['options']},{1,2,3})
            self.assertTrue(all('default' not in opt and 'recommended' not in opt for opt in item['options']))
            self.assertIn('#2 含,逗号',[opt['label'] for opt in item['options']])
        self.assertEqual(r['state']['columns'],[None,None])

    def test_limit_applies_per_question_and_overflow_uses_free_text_without_dropping_catalog(self):
        for cap in (2,3):
            with self.subTest(cap=cap):
                r=self.fields({'questions':True,'max_options':cap})
                self.assertEqual(r['question']['mode'],'tool')
                self.assertEqual(len(r['question']['questions']),2)
                for item in r['question']['questions']:
                    self.assertEqual(len(item['options']),0 if cap==2 else 3)
                    self.assertTrue(item['allows_text'])
                self.assertEqual(len(r['catalog']['items']),4)

    def test_single_question_and_no_tool_keep_ordered_input_inside_conversation(self):
        for host in ({'questions':True,'max_questions':1},{'questions':False}):
            with self.subTest(host=host):
                r=self.fields(host);q=r['question']
                self.assertEqual(q['mode'],'tool' if host['questions'] else 'text')
                self.assertEqual(len(q['questions']),1)
                self.assertEqual(q['questions'][0]['id'],'pair')
                self.assertEqual(q['questions'][0]['options'],[])
                self.assertIn('X',q['questions'][0]['title']);self.assertIn('Y',q['questions'][0]['title'])
                self.assertIn('→',q['questions'][0]['title'])
                self.assertIsNone(r['analysis_args'])

    def test_partial_legacy_selection_remains_available_in_form_and_state(self):
        pending=flow.advance({'action':{'input':str(self.path),'columns':{'1':{'index':1}}}})
        before=deepcopy(pending['state']['columns'][0])
        r=flow.advance({'state':pending['state'],'host':{'questions':True}})
        self.assertEqual(r['state']['columns'][0],before)
        self.assertNotIn(1,[c['index'] for c in r['catalog']['items']])
        for q in r['question']['questions']:
            self.assertIn(1,[o['value']['index'] for o in q['options']])
        self.assertIsNone(r['analysis_args'])

    def test_field_search_and_duplicate_headers_keep_physical_identity(self):
        path=self.root/'duplicates.xlsx'
        pd.DataFrame([[v,v*v,v+1] for v in range(12)],columns=['A','A','B']).to_excel(path,index=False)
        r=flow.advance({'action':{'input':str(path),'sheet':{'index':1}},'host':{'questions':True}})
        options=r['question']['questions'][0]['options']
        self.assertEqual([o['value']['index'] for o in options],[1,2,3])
        self.assertNotEqual(options[0]['label'],options[1]['label'])
        searched=self.fields(view={'search':'逗号'})
        self.assertEqual(searched['catalog']['matched'],1)
        for q in searched['question']['questions']:
            self.assertEqual(q['options'][0]['value'],{'index':2})
            self.assertTrue(q['allows_text'])

    def test_answers_bind_by_axis_id_and_publish_both_directions_without_more_confirmation(self):
        initial=self.fields();q=initial['question'];stats=[]
        for x,y in ((1,2),(2,1)):
            # Host answers may arrive in any order. Their question ids bind the axes.
            answers=[{'id':item['id'],'value':next(o['value'] for o in item['options']
                       if o['value']['index']=={'x':x,'y':y}[item['id']])}
                     for item in reversed(q['questions'])]
            pair={answer['id']:answer['value'] for answer in answers}
            r=flow.advance({'state':initial['state'],'action':{'pair':pair}})
            self.assertEqual(r['step'],'ready');self.assertIsNone(r['question'])
            result=dr.cmd_analyze(dr.build_parser().parse_args(r['analysis_args']+
                ['--out',str(self.root/'out'),'--permutations','3']))
            self.assertEqual(result['publication']['status'],'complete')
            self.assertEqual(result['plot'],r['summary']['plot'])
            self.assertEqual(result['plot']['x']['column_index'],x)
            self.assertEqual(result['plot']['y']['column_index'],y)
            soup=BeautifulSoup(Path(result['report_html_path']).read_text(),'html.parser')
            self.assertNotIn('横轴：',soup.select_one('#summary').get_text())
            self.assertIn('横轴：'+result['plot']['x']['label'],soup.figcaption.get_text())
            self.assertEqual(soup.footer.span.get_text(),'数据科学:相关性分析 / 1.4.1')
            stats.append({key:result[key] for key in ('methods','tests','effects','conclusions','comparisons')})
        self.assertEqual(stats[0],stats[1])

    def test_default_partial_and_duplicate_answers_cannot_start_analysis(self):
        initial=self.fields();pair={'x':{'index':1},'y':{'index':2}}
        default=flow.advance({'state':initial['state'],'action':{'pair':pair,'source':'default'},'host':{'questions':True}})
        self.assertEqual(default['step'],'needs_columns');self.assertIsNone(default['analysis_args'])
        with self.assertRaises(dr.UserError):
            flow.advance({'state':initial['state'],'action':{'pair':{'x':{'index':1}}}})
        duplicate=flow.advance({'state':initial['state'],'action':{'pair':{'x':{'index':1},'y':{'index':1}}},'host':{'questions':True}})
        self.assertFalse(duplicate['ok']);self.assertIsNone(duplicate['analysis_args'])
        self.assertEqual(duplicate['question']['mode'],'tool')
        fixed=flow.advance({'state':duplicate['state'],'action':{'pair':pair}})
        self.assertEqual(fixed['step'],'ready')

    def test_real_cli_emits_native_form_and_accepts_submitted_pair(self):
        request=self.root/'request.json'
        def cli(payload):
            request.write_text(json.dumps(payload,ensure_ascii=False))
            proc=subprocess.run([sys.executable,str(SCRIPTS/'data_relationship.py'),'select','--request',str(request)],
                                capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            return json.loads(proc.stdout)
        r=cli({'action':{'input':str(self.path)},'host':{'questions':True,'max_questions':2,'max_options':4}})
        self.assertEqual(r['question']['mode'],'tool')
        self.assertEqual(len(r['question']['questions']),2)
        ready=cli({'state':r['state'],'action':{'pair':{'x':{'index':2},'y':{'index':1}}}})
        self.assertEqual(ready['step'],'ready')
        self.assertEqual(ready['summary']['plot']['x']['column_index'],2)

    def test_invalid_host_question_limits_fail_at_ingress(self):
        for key in ('max_questions','max_options'):
            for cap in (0,-1,True,'2'):
                with self.subTest(key=key,cap=cap),self.assertRaises(dr.UserError):
                    self.fields({'questions':True,key:cap})
        with self.assertRaises(dr.UserError):
            self.fields({'inline_widget':'true'})
        with self.assertRaises(dr.UserError):
            self.fields(action={'input':str(self.path),'context_key':True})

    def test_all_65_fields_are_native_options_independent_of_preview_page(self):
        pd.DataFrame({f'字段{i}':range(12) for i in range(1,66)}).to_csv(self.path,index=False)
        r=self.fields()
        self.assertEqual(len(r['catalog']['items']),20)
        self.assertEqual(len(r['question']['questions'][0]['options']),65)
        arguments=r['question']['tool_arguments']
        for question in arguments['questions']:
            self.assertEqual([opt['label'] for opt in question['options']],
                             [f'#{i} 字段{i}' for i in range(1,66)])
            self.assertFalse(question['multi_select'])
            self.assertNotIn('字段1',question['question'])
        r=self.fields(view={'page':3})
        self.assertEqual(len(r['question']['questions'][0]['options']),65)

    def test_widget_keeps_all_fields_despite_four_option_host_limit(self):
        pd.DataFrame({f'字段{i}':range(12) for i in range(1,14)}).to_csv(self.path,index=False)
        r=self.fields({'questions':True,'max_options':4,'inline_widget':True})
        self.assertEqual(r['question']['mode'],'widget')
        self.assertIn('widget_code',r['question']['widget'])
        self.assertIsNone(r['analysis_args'])
        self.assertIsNone(r['question']['tool_arguments'])

    def test_workbuddy_widget_tools_do_not_require_a_sendprompt_tool(self):
        for flags in ({}, {'questions':False}, {'questions':False,'inline_widget':False}):
            with self.subTest(flags=flags):
                r=self.fields({'tools':['widget_guidelines','show_widget'],**flags})
                self.assertEqual(r['question']['mode'],'widget')
                self.assertIsNone(r['analysis_args'])
                self.assertIsNone(r['question']['tool_arguments'])
                self.assertEqual(r['state']['columns'],[None,None])

    def test_incomplete_widget_tool_list_keeps_explicit_native_or_text_flow(self):
        for names in ([],['show_widget'],['widget_guidelines'],['sendPrompt']):
            with self.subTest(names=names):
                native=self.fields({'tools':names,'questions':True})
                self.assertEqual(native['question']['mode'],'tool')
                text=self.fields({'tools':names,'questions':False})
                self.assertEqual(text['question']['mode'],'text')

    def test_tool_names_are_validated_at_request_boundary(self):
        for names in ('show_widget',[None],[42],{'show_widget':True}):
            with self.subTest(names=names),self.assertRaises(dr.UserError):
                self.fields({'tools':names})

    def test_widget_context_rejects_old_file_and_valid_pair_is_ready(self):
        r=self.fields({'questions':True,'inline_widget':True})
        action={'pair':{'x':{'index':2},'y':{'index':1}},'context_key':r['question']['context_key']}
        ready=flow.advance({'state':r['state'],'action':action})
        self.assertEqual(ready['step'],'ready')
        with self.path.open('a') as out:out.write('12,144,15,1\n')
        stale=flow.advance({'state':r['state'],'action':action,'host':{'inline_widget':True}})
        self.assertEqual(stale['step'],'needs_columns');self.assertFalse(stale['ok'])
        self.assertIsNone(stale['analysis_args'])
        self.assertNotEqual(stale['question']['context_key'],action['context_key'])

    def test_widget_context_cannot_be_reused_for_another_sheet(self):
        path=self.root/'sheets.xlsx'
        frame=pd.DataFrame({'A':range(12),'B':[v*v for v in range(12)]})
        with pd.ExcelWriter(path) as writer:
            frame.to_excel(writer,sheet_name='一月',index=False)
            frame.to_excel(writer,sheet_name='二月',index=False)
        initial=flow.advance({'action':{'input':str(path),'sheet':{'index':1}},
                              'host':{'inline_widget':True}})
        result=flow.advance({'state':initial['state'],'action':{
            'sheet':{'index':2},'pair':{'x':{'index':1},'y':{'index':2}},
            'context_key':initial['question']['context_key']},'host':{'inline_widget':True}})
        self.assertEqual(result['step'],'needs_columns');self.assertFalse(result['ok'])
        self.assertIsNone(result['analysis_args'])
        self.assertEqual(result['state']['sheet']['index'],2)
        self.assertNotEqual(result['question']['context_key'],initial['question']['context_key'])


if __name__=='__main__':unittest.main()
