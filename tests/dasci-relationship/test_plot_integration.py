"""Selection → CLI → complete publication keeps axis intent and raw statistics."""
from pathlib import Path
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from PIL import Image
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'
sys.path.insert(0,str(SCRIPTS))
import data_relationship as dr
import interaction
from test_statistics_methods import KINDS, make_pair


class AxisPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_pair(self,kinds,x,*,no_chart=False):
        frame,_=make_pair(*kinds,n=40);path=self.root/('-'.join(kinds)+'.csv')
        frame.to_csv(path,index=False)
        columns={str(i):{'index':i,'type':kind,**({'order':['低','中','高','未观察']} if kind=='ordinal' else {})}
                 for i,kind in enumerate(kinds,start=1)}
        selection=interaction.advance({'action':{'input':str(path),'columns':columns,'plot_x':x,'explicit':True}})
        self.assertEqual(selection['step'],'ready')
        argv=selection['analysis_args']+['--out',str(self.root/'reports'),'--permutations','3','--seed','17']
        if no_chart:argv.append('--no-chart')
        result=dr.cmd_analyze(dr.build_parser().parse_args(argv))
        self.assertEqual(result['plot'],selection['summary']['plot'])
        self.assertEqual(json.loads(Path(result['result_path']).read_text()),result)
        return result

    def test_all_15_pairs_publish_both_directions_with_identical_raw_statistics_and_csv(self):
        ignored={'plot','figures','publication','out_dir','report_html_path','report_md_path','result_path','chart_paths'}
        for kinds in itertools.combinations_with_replacement(KINDS,2):
            with self.subTest(kinds=kinds):
                values=[self.run_pair(kinds,x) for x in ('col1','col2')]
                a,b=values
                self.assertNotEqual(a['out_dir'],b['out_dir'])
                self.assertEqual({k:v for k,v in a.items() if k not in ignored},
                                 {k:v for k,v in b.items() if k not in ignored})
                csv=lambda r:{p.name:p.read_bytes() for p in Path(r['out_dir']).glob('*.csv')}
                self.assertEqual(csv(a),csv(b))
                for result in values:
                    plan=result['plot'];primary=result['figures'][0]
                    self.assertEqual(primary['axes'],{axis:plan[axis] for axis in ('x','y')})
                    soup=BeautifulSoup(Path(result['report_html_path']).read_text(),'html.parser')
                    md=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(Path(result['report_md_path']).read_text()),'html.parser')
                    for label in ('横轴：','纵轴：'):
                        self.assertNotIn(label,soup.select_one('#summary').get_text())
                        self.assertEqual(soup.select_one('#figures').get_text().count(label),
                                         sum(f['caption'].count(label) for f in result['figures']))
                        self.assertEqual(md.get_text().count(label),
                                         sum(f['caption'].count(label) for f in result['figures']))
                    for figure in result['figures']:
                        caption=soup.find(id=figure['id']).figcaption.get_text()
                        for label,axis in [('横轴','x'),('纵轴','y')]:
                            statement=label+'：'+figure['axes'][axis]['label']
                            self.assertIn(statement,caption)
                            self.assertIn(statement,md.get_text())
                    for image,figure in zip(soup.select('#figures img'),result['figures']):
                        self.assertEqual(figure['status'],'available')
                        with Image.open(Path(result['out_dir'])/figure['asset_path']) as png:
                            self.assertEqual((int(image['width']),int(image['height'])),png.size)
                            png.verify()
                    self.assertEqual(soup.select_one('[data-report-id]')['data-report-id'],result['publication']['run_id'])
                self.assertFalse(list((self.root/'reports').glob('.pending-*')))

    def test_no_chart_keeps_axes_in_captions_and_reproduction_request(self):
        r=self.run_pair(('numeric','numeric'),'col2',no_chart=True)
        soup=BeautifulSoup(Path(r['report_html_path']).read_text(),'html.parser')
        self.assertFalse(soup.select('img'))
        summary=soup.select_one('#summary')
        for label,axis in [('横轴','x'),('纵轴','y')]:
            self.assertNotIn(label+'：',summary.get_text())
            self.assertIn(label+'：'+r['plot'][axis]['label'],soup.select_one('figcaption').get_text())
        reproductions=[json.loads(code.get_text()) for code in soup.select('#attachments code')]
        reproduction=next(value for value in reproductions if 'plot_x' in value)
        self.assertEqual(reproduction['plot_x'],'col2')
        self.assertIn(r['plot']['x']['label'],soup.select_one('#figures').get_text())
        self.assertTrue(all(f['status']=='disabled' for f in r['figures']))

    def test_duplicate_and_html_names_bind_physical_columns_and_escape_report(self):
        path=self.root/'names.xlsx'
        pd.DataFrame([[i,i*i] for i in range(12)],columns=['<b>字段|同名','<b>字段|同名']).to_excel(path,index=False)
        s=interaction.advance({'action':{'input':str(path),'sheet':{'index':1},'columns':{'1':{'index':2,'type':'numeric'},'2':{'index':1,'type':'numeric'}},'plot_x':'col2','explicit':True}})
        self.assertEqual(s['step'],'ready',s['error'])
        r=dr.cmd_analyze(dr.build_parser().parse_args(s['analysis_args']+['--out',str(self.root/'names'),'--no-chart']))
        self.assertEqual(r['plot']['x']['column_index'],1);self.assertEqual(r['plot']['y']['column_index'],2)
        soup=BeautifulSoup(Path(r['report_html_path']).read_text(),'html.parser')
        self.assertFalse(soup.select('#summary b'))
        self.assertFalse(soup.select('figcaption b'))
        self.assertIn(r['plot']['x']['label'],soup.select_one('figcaption').get_text())

    def test_real_cli_process_emits_only_fully_published_current_result(self):
        path=self.root/'process.csv';pd.DataFrame({'a':range(12),'b':[i*i for i in range(12)]}).to_csv(path,index=False)
        args=[sys.executable,str(SCRIPTS/'data_relationship.py'),'analyze','--input',str(path),'--col1-index','1','--col2-index','2','--plot-x','col2','--out',str(self.root/'process')]
        proc=subprocess.run(args,capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        r=json.loads(proc.stdout)
        self.assertEqual(r['plot']['x']['column_index'],2)
        self.assertEqual(r['publication']['status'],'complete')
        self.assertEqual(r,json.loads(Path(r['result_path']).read_text()))
        self.assertTrue(Path(r['report_html_path']).is_file())


if __name__=='__main__':unittest.main()
