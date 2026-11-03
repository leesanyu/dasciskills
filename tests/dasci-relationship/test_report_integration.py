"""Actual analyze outputs, no compatibility aliases, failures and content parity."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import itertools
import os
import subprocess
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import reporting as report
import plots
from test_statistics_methods import KINDS, make_pair
from test_report_model import result_for
from test_report_rendering import displayed_cell


class ReportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def argv(self,kinds=('numeric','numeric'),*,no_chart=False):
        frame,_=make_pair(*kinds,n=40);path=self.root/'原始 数据.csv';frame.to_csv(path,index=False)
        argv=['analyze','--input',str(path),'--col1-index','1','--col2-index','2','--col1-type',kinds[0],
              '--col2-type',kinds[1],'--out',str(self.root/'output'),'--permutations','3']
        for i,kind in enumerate(kinds,1):
            if kind=='ordinal':argv += [f'--col{i}-order','["低","中","高","未观察"]']
        return argv+(['--no-chart'] if no_chart else [])

    def run_analysis(self,*args,**kwargs):
        return dr.cmd_analyze(dr.build_parser().parse_args(self.argv(*args,**kwargs)))

    def test_all_15_cli_pairs_default_both_formats_exact_table_parity_and_machine_result(self):
        reader=MarkdownIt('commonmark').enable('table')
        for kinds in itertools.combinations_with_replacement(KINDS,2):
            with self.subTest(kinds=kinds):
                r=self.run_analysis(kinds,no_chart=True)
                self.assertTrue({'report_path','chart_path'}.isdisjoint(r))
                self.assertEqual(r['chart_paths'],[])
                self.assertEqual(json.loads(Path(r['result_path']).read_text()),r)
                html=BeautifulSoup(Path(r['report_html_path']).read_text(),'html.parser')
                md=BeautifulSoup(reader.render(Path(r['report_md_path']).read_text()),'html.parser')
                self.assertEqual(html.html['data-template-version'],r['report_template']['version'])
                self.assertEqual([[displayed_cell(c,html) for c in row.select('th,td')] for row in html.select('table tr')],
                                 [[displayed_cell(c,md) for c in row.select('th,td')] for row in md.select('table tr')])
                for test in r['tests']:
                    row=next(row for row in html.find('table',id=test['method_id']+'-tests').select('tbody tr') if row.select_one('td').get_text()==test['id'])
                    cells=[c.get_text() for c in row.select('td')]
                    self.assertEqual(cells[5],report.format_value(test['p_value']))
                    self.assertEqual(cells[6],report.format_value(test['p_adjusted']))
                self.assertEqual([c['data-status'] for c in html.select('#summary .finding')],[c['status'] for c in r['conclusions']])
                self.assertTrue(all(m['id'] in html.get_text() for m in r['methods']))

    def test_real_cli_process_returns_two_existing_reports_and_no_old_paths(self):
        proc=subprocess.run([sys.executable,str(Path(dr.__file__))]+self.argv(no_chart=True),capture_output=True,text=True,
                            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        result=json.loads(proc.stdout)
        self.assertTrue({'report_path','chart_path'}.isdisjoint(result))
        self.assertTrue(Path(result['report_html_path']).is_file())
        self.assertTrue(Path(result['report_md_path']).is_file())

    def test_successful_figures_are_relative_in_md_inline_in_html_and_mapped_to_methods(self):
        r=self.run_analysis(('boolean','datetime'))
        self.assertGreater(len(r['chart_paths']),1)
        self.assertEqual(len(set(r['chart_paths'])),len(r['chart_paths']))
        self.assertTrue(all(Path(p).is_file() for p in r['chart_paths']))
        html=BeautifulSoup(Path(r['report_html_path']).read_text(),'html.parser')
        self.assertEqual(len(html.select('img')),len(r['chart_paths']))
        self.assertTrue(all(img['src'].startswith('data:image/png;base64,') for img in html.select('img')))
        md=Path(r['report_md_path']).read_text()
        self.assertTrue(all(']('+str(Path(p).relative_to(Path(r['out_dir'])))+')' in md for p in r['chart_paths']))
        self.assertEqual({mid for f in r['figures'] for mid in f['method_ids']},{m['id'] for m in r['methods']})
        self.assertTrue((Path(r['out_dir'])/'datetime_features.csv').is_file())

    def test_disabled_pillow_and_partial_failure_have_both_reports_without_bad_references(self):
        with patch.object(plots,'Image',None): r=self.run_analysis()
        self.assertTrue(r['ok']);self.assertEqual(r['chart_paths'],[])
        self.assertIn('Pillow',Path(r['report_md_path']).read_text())
        with patch.object(plots,'timeline',side_effect=OSError('partial failure')): r=self.run_analysis(('boolean','datetime'))
        self.assertTrue(r['chart_paths']);self.assertEqual(r['figures'][0]['status'],'unavailable')
        self.assertIn('partial failure',Path(r['report_md_path']).read_text())

    def test_required_writes_fail_without_publishing_or_damaging_previous_run(self):
        previous=self.run_analysis(('categorical','numeric'),no_chart=True)
        base=self.root/'output';old=Path(previous['out_dir'])
        snapshot={str(p.relative_to(old)):p.read_bytes() for p in old.rglob('*') if p.is_file()}
        runs=set(base.iterdir());write=Path.write_text;csv=pd.DataFrame.to_csv
        for filename in ('report.html','report.md','group_summary.csv','result.json'):
            with self.subTest(filename=filename):
                argv=self.argv(('categorical','numeric'),no_chart=True);stdout=StringIO()
                def fail_write(path,*args,**kwargs):
                    if path.name==filename:raise OSError('injected '+filename)
                    return write(path,*args,**kwargs)
                def fail_csv(frame,path,*args,**kwargs):
                    if Path(path).name==filename:raise OSError('injected '+filename)
                    return csv(frame,path,*args,**kwargs)
                with patch.object(Path,'write_text',fail_write),patch.object(pd.DataFrame,'to_csv',fail_csv),redirect_stdout(stdout):
                    code=dr.main(argv)
                payload=json.loads(stdout.getvalue())
                self.assertEqual(code,1);self.assertFalse(payload['ok']);self.assertIn(filename,payload['error'])
                self.assertEqual(set(base.iterdir()),runs)
                self.assertEqual({str(p.relative_to(old)):p.read_bytes() for p in old.rglob('*') if p.is_file()},snapshot)

    def test_one_directory_publish_happens_only_after_all_outputs_are_verified(self):
        argv=self.argv(('boolean','datetime'));base=self.root/'output';rename=Path.rename;published=[]
        def observe(stage,target):
            target=Path(target)
            self.assertEqual(stage.parent,base)
            self.assertTrue(stage.name.startswith('.pending-'))
            self.assertFalse(target.exists())
            self.assertFalse(list(base.glob('run-*')))
            value=json.loads((stage/'result.json').read_text())
            self.assertEqual(value['publication'],{'status':'complete','run_id':target.name.removeprefix('run-')})
            self.assertEqual(Path(value['out_dir']),target)
            self.assertNotIn(str(stage),(stage/'result.json').read_text())
            for filename in ('report.html','report.md','datetime_features.csv','result.json'):
                self.assertGreater((stage/filename).stat().st_size,0)
            self.assertTrue(all((stage/Path(path).relative_to(target)).is_file() for path in value['chart_paths']))
            published.append(target)
            return rename(stage,target)
        with patch.object(Path,'rename',observe):result=dr.cmd_analyze(dr.build_parser().parse_args(argv))
        self.assertEqual(published,[Path(result['out_dir'])])
        self.assertEqual(list(base.iterdir()),published)
        self.assertEqual(json.loads(Path(result['result_path']).read_text()),result)

    def test_repeated_runs_are_distinct_and_no_report_appears_at_shared_base(self):
        first=self.run_analysis(no_chart=True);old=Path(first['out_dir']);base=self.root/'output'
        self.assertEqual(old.parent,base)
        snapshot={p.name:p.read_bytes() for p in old.iterdir() if p.is_file()}
        analyze=dr._analyze_columns
        def observe(*args,**kwargs):
            self.assertFalse((base/'report.html').exists())
            self.assertEqual(list(base.glob('run-*')),[old])
            return analyze(*args,**kwargs)
        with patch.object(dr,'_analyze_columns',observe):second=self.run_analysis(no_chart=True)
        self.assertNotEqual(first['out_dir'],second['out_dir'])
        self.assertNotEqual(first['publication']['run_id'],second['publication']['run_id'])
        self.assertEqual({p.name:p.read_bytes() for p in old.iterdir() if p.is_file()},snapshot)
        self.assertEqual(len(list(base.iterdir())),2)
        for value in (first,second):
            page=BeautifulSoup(Path(value['report_html_path']).read_text(),'html.parser')
            self.assertEqual(page.select_one('[data-report-id]')['data-report-id'],value['publication']['run_id'])

    def test_missing_or_wrong_run_outputs_are_not_published(self):
        for damage in ('missing_csv','wrong_html_id','wrong_result'):
            with self.subTest(damage=damage):
                argv=self.argv(('categorical','numeric'),no_chart=True);write=Path.write_text;reports=report.write_reports
                def damage_reports(model,extra,stage):
                    paths=reports(model,extra,stage)
                    if damage=='missing_csv':(Path(stage)/'group_summary.csv').unlink()
                    if damage=='wrong_html_id':
                        p=Path(stage)/'report.html';write(p,p.read_text().replace(model['report_id'],'wrong-run'))
                    return paths
                def damage_result(path,text,*args,**kwargs):
                    if path.name=='result.json' and damage=='wrong_result':text='{}'
                    return write(path,text,*args,**kwargs)
                stdout=StringIO()
                with patch.object(report,'write_reports',damage_reports),patch.object(Path,'write_text',damage_result),redirect_stdout(stdout):
                    code=dr.main(argv)
                self.assertEqual(code,1);self.assertFalse(json.loads(stdout.getvalue())['ok'])
                self.assertFalse(list((self.root/'output').iterdir()))

    def test_publish_failure_cleans_staging_and_keeps_previous_run(self):
        previous=self.run_analysis(no_chart=True);base=self.root/'output';old=Path(previous['out_dir'])
        argv=self.argv(no_chart=True);stdout=StringIO()
        with patch.object(Path,'rename',side_effect=OSError('publish denied')),redirect_stdout(stdout):code=dr.main(argv)
        self.assertEqual(code,1);self.assertIn('publish denied',json.loads(stdout.getvalue())['error'])
        self.assertEqual(list(base.iterdir()),[old])
        self.assertEqual(json.loads(Path(previous['result_path']).read_text()),previous)

    def test_required_template_failure_and_unknown_plot_error_are_not_success(self):
        with patch.object(report,'ASSETS',self.root),redirect_stdout(StringIO()) as stdout:
            code=dr.main(self.argv(no_chart=True))
        self.assertEqual(code,1);self.assertIn('模板',json.loads(stdout.getvalue())['error'])
        with patch.object(plots,'scatter',side_effect=RuntimeError('plot defect')),redirect_stdout(StringIO()) as stdout:
            code=dr.main(self.argv())
        self.assertEqual(code,1);self.assertIn('plot defect',json.loads(stdout.getvalue())['error'])

    def test_html_and_markdown_literals_keep_chinese_html_pipe_and_newline_names(self):
        path=self.root/'evil.csv';name='<script>危险</script> | 名称\n下一行'
        pd.DataFrame({name:range(40),'另一个字段':range(40)}).to_csv(path,index=False)
        argv=['analyze','--input',str(path),'--col1-index','1','--col2-index','2','--out',str(self.root/'escaped'),'--no-chart']
        r=dr.cmd_analyze(dr.build_parser().parse_args(argv))
        html=BeautifulSoup(Path(r['report_html_path']).read_text(),'html.parser')
        self.assertFalse(html.select('script'));self.assertIn(name,html.get_text())
        rendered=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(Path(r['report_md_path']).read_text()),'html.parser')
        self.assertFalse(rendered.select('script'));self.assertIn('危险',rendered.get_text())

    def test_raw_significance_contrasting_directions_single_and_all_descriptive_are_preserved(self):
        import inference
        for scenario in ('consistent','mixed','single','one-valid','descriptive'):
            with self.subTest(scenario=scenario):
                result,chart,extra=result_for(n=40 if scenario!='descriptive' else 2,permutations=0)
                if scenario=='mixed':
                    for t,p in zip(result['tests'],(.04,.4,.7)): t['p_value']=p
                    result['effects'][0]['value']=-.2
                    inference.apply_holm(result['tests'],.05)
                    result['conclusions'],result['comparisons']=inference.summarize(result['methods'],result['tests'],result['effects'],alpha=.05)
                if scenario=='single':
                    _,columns=make_pair('numeric','numeric',n=40)
                    analysis,chart,extra=dr.multi.analyze_pair(*columns,methods='pearson',permutations=0)
                    result.update(analysis)
                if scenario=='one-valid':
                    result,chart,extra=result_for('numeric','boolean',n=3,permutations=0)
                    self.assertEqual(result['multiplicity']['m'],1)
                    self.assertEqual([m['status'] for m in result['methods']],['ok','not_applicable','descriptive_only'])
                model=report.build_model(result,chart,extra);report.render_figures(model,self.root,disabled=True)
                html=BeautifulSoup(report.render_html(model,self.root),'html.parser')
                self.assertEqual(model['methods'],result['methods']);self.assertEqual(model['tests'],result['tests'])
                self.assertEqual([c['data-status'] for c in html.select('#summary .finding')],[c['status'] for c in result['conclusions']])
                if scenario=='mixed':
                    self.assertFalse(result['tests'][0]['reject_adjusted']);self.assertGreater(result['tests'][0]['p_adjusted'],.05)
                    self.assertIn('-0.2',html.get_text())
                    self.assertTrue(any(c['direction_agreement']=='opposite' for c in model['comparisons']))
                if scenario=='single':self.assertEqual(model['method_plan']['candidate_ids'],['pearson'])
                if scenario=='descriptive':self.assertIn('仅作描述',html.get_text())


if __name__=='__main__':unittest.main()
