"""Shared content, escaped text, fixed assets and actual offline image resources."""
import base64
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import reporting as report
import theme
import plots
from test_report_model import result_for


def displayed_cell(cell, document=None):
    """Read the complete value, following a Markdown cell's detail reference."""
    link=cell.find('a',href=re.compile('^#cell-'))
    if link:
        target=document.find(id=link['href'][1:])
        if target.get('data-format')=='json':return json.loads(target.code.get_text())
        return target.find_all('p')[-1].get_text()
    content=cell.select_one('.cell-content')
    if content:
        if content.get('data-format')=='json':return json.loads(content.code.get_text())
        return content.get_text()
    return cell.get_text()


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def model(self, *kinds):
        return report.build_model(*result_for(*(kinds or ('numeric','numeric'))), report_id='fixed',generated_at='2026-11-02T00:00:00Z')

    def test_both_formats_keep_complete_formatted_tables_and_original_model(self):
        model=self.model();report.render_figures(model,self.root,disabled=True)
        original=deepcopy(model)
        soup=BeautifulSoup(report.render_html(model,self.root),'html.parser');md=report.render_markdown(model)
        from markdown_it import MarkdownIt
        reading=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(md),'html.parser')
        md_tables=reading.select('table')
        self.assertEqual(len(md_tables),len(model['tables']))
        for table in model['tables']:
            actual=soup.find('table',id=table['id'])
            expected=[[json.loads(report.format_value(v)) if isinstance(v,(dict,list,tuple)) else report.format_value(v) for v in row] for row in table['rows']]
            self.assertEqual([[displayed_cell(cell) for cell in row.find_all('td')] for row in actual.tbody.find_all('tr')],expected)
        for table in model['tables']:
            actual=soup.find('table',id=table['id'])
            self.assertIsNotNone(actual)
            md_table=md_tables[[s['table']['id'] for section in model['sections'] for s in section['blocks'] if s['kind']=='table'].index(table['id'])]
            self.assertEqual([[displayed_cell(cell,reading) for cell in row.find_all('td')] for row in md_table.select('tbody tr')],
                             [[displayed_cell(cell) for cell in row.find_all('td')] for row in actual.select('tbody tr')])
        self.assertEqual([s['id'] for s in soup.select('main > section')],report.SECTION_IDS)
        self.assertEqual(model,original)
        for finding in soup.select('#summary .finding'):
            self.assertIn(report.md_text(finding.p.get_text()),md)

    def test_five_shapes_reuse_identical_css_template_and_inline_actual_png(self):
        styles=[]
        for kinds in [('numeric','numeric'),('categorical','categorical'),('numeric','categorical'),('boolean','datetime'),('ordinal','ordinal')]:
            with self.subTest(kinds=kinds):
                model=self.model(*kinds);out=self.root/'-'.join(kinds);out.mkdir()
                report.render_figures(model,out)
                html=report.render_html(model,out);soup=BeautifulSoup(html,'html.parser');styles.append(soup.style.string)
                self.assertEqual(soup.html['data-template-id'],model['html_template']['id'])
                self.assertEqual(soup.html['data-template-version'],model['html_template']['version'])
                footer='数据科学:相关性分析 / '+model['html_template']['version']
                self.assertEqual(soup.footer.span.get_text(),footer)
                self.assertTrue(report.render_markdown(model).splitlines()[-1].startswith(footer+'；'))
                self.assertNotIn('模板 data-relationship-report',soup.get_text())
                self.assertTrue(soup.select('img'))
                self.assertFalse(soup.select('script, link, iframe'))
                md=report.render_markdown(model)
                for figure,image in zip(model['figures'],soup.select('img')):
                    self.assertEqual(figure['status'],'available')
                    self.assertTrue(image['src'].startswith('data:image/png;base64,'))
                    with Image.open(BytesIO(base64.b64decode(image['src'].split(',',1)[1]))) as pic: pic.verify()
                    self.assertTrue((out/figure['asset_path']).is_file());self.assertIn(']('+figure['asset_path']+')',md)
                copy=self.root/'copied';copy.mkdir(exist_ok=True);(copy/'standalone.html').write_text(html)
                self.assertNotIn(str(out),html)
        self.assertTrue(all(s==styles[0] for s in styles))

    def test_external_text_is_literal_in_html_and_markdown(self):
        model=self.model();evil='<script>alert(1)</script> & | [x](javascript:1)\n# title `code` *bold*'
        model['sections'][0]['blocks'].append({'kind':'text','value':evil})
        model['tables'][0]['rows'][0][1]=evil
        report.render_figures(model,self.root,disabled=True)
        html=report.render_html(model,self.root);soup=BeautifulSoup(html,'html.parser');md=report.render_markdown(model)
        self.assertFalse(soup.find_all('script'));self.assertIn(evil,soup.get_text());self.assertNotIn('<script>',md)
        from markdown_it import MarkdownIt
        rendered=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(md),'html.parser')
        self.assertFalse(rendered.find_all('script'));self.assertFalse(rendered.select('a[href^="javascript:"]'))
        self.assertIn('<script>alert(1)</script>',rendered.get_text())

    def test_no_chart_and_missing_pillow_keep_all_sections_without_broken_links(self):
        for disabled in (True,False):
            with self.subTest(disabled=disabled),patch.object(plots,'Image',None):
                model=self.model();report.render_figures(model,self.root,disabled=disabled)
                self.assertTrue(all(f['status']==('disabled' if disabled else 'unavailable') for f in model['figures']))
                soup=BeautifulSoup(report.render_html(model,self.root),'html.parser');md=report.render_markdown(model)
                self.assertFalse(soup.select('img'));self.assertNotIn('![' ,md)
                self.assertEqual([s['id'] for s in soup.select('main > section')],report.SECTION_IDS)
                for m in model['methods']: self.assertIn(m['id'],soup.get_text())

    def test_font_failure_is_explicit_and_unknown_chart_errors_propagate(self):
        model=self.model()
        with patch.object(plots,'_font',side_effect=plots.ChartUnavailable('没有可显示中文的字体')):
            report.render_figures(model,self.root)
        self.assertEqual(model['figures'][0]['status'],'unavailable');self.assertIn('字体',model['figures'][0]['reason'])
        with patch.object(plots,'scatter',side_effect=RuntimeError('internal defect')),self.assertRaisesRegex(RuntimeError,'internal defect'):
            report.render_figures(self.model(),self.root)

    def test_partial_figure_failure_retains_successful_resources_and_mapping(self):
        model=self.model('boolean','datetime')
        with patch.object(plots,'timeline',side_effect=OSError('failed image')):
            report.render_figures(model,self.root)
        self.assertEqual(model['figures'][0]['status'],'unavailable')
        self.assertTrue(all(f['status']=='available' for f in model['figures'][1:]))
        soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
        self.assertEqual(len(soup.select('img')),len(model['figures'])-1)
        self.assertIn('failed image',soup.get_text())

    def test_missing_template_and_unbound_required_slot_fail(self):
        model=self.model();report.render_figures(model,self.root,disabled=True)
        with patch.object(report,'ASSETS',self.root),self.assertRaises(report.ReportError): report.render_html(model,self.root)
        assets=Path(report.ASSETS)
        for name in ('report.html','report.css','theme.json'): shutil.copyfile(assets/name,self.root/name)
        path=self.root/'report.html';path.write_text(path.read_text().replace('$body',''))
        with patch.object(report,'ASSETS',self.root),self.assertRaisesRegex(report.ReportError,'槽位'): report.render_html(model,self.root)

    def test_theme_drives_page_and_charts_and_category_colors_are_stable(self):
        self.assertEqual(theme.THEME['colors']['background'],'#F5F7FB')
        self.assertEqual(theme.THEME['colors']['primary'],'#2563EB')
        self.assertEqual(plots.COLORS,[theme.rgb(c) for c in theme.THEME['palette']])
        self.assertEqual(plots.category_color('中文'),plots.category_color('中文'))
        font=plots._font(18)
        self.assertTrue(any(name in str(font.path) for name in ('msyh','PingFang','NotoSansCJK','wqy','simhei','simsun')))

    def test_reading_layer_follows_adjusted_decisions_and_retains_exact_audit(self):
        import inference
        for raw in ((.04,.4,.7),(.001,.4,.7),(.4,.001,.7),(.001,.002,.003)):
            with self.subTest(raw=raw):
                result,chart,extra=result_for()
                for test,p in zip(result['tests'],raw):test['p_value']=p
                inference.apply_holm(result['tests'],result['alpha'])
                result['conclusions'],result['comparisons']=inference.summarize(
                    result['methods'],result['tests'],result['effects'],alpha=result['alpha'])
                model=report.build_model(result,chart,extra)
                summary=next(s for s in model['sections'] if s['id']=='summary')
                findings=[b for b in summary['blocks'] if b['kind']=='finding']
                self.assertEqual([b['status'] for b in findings],[c['status'] for c in result['conclusions']])
                report.render_figures(model,self.root,disabled=True)
                soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
                for c in result['conclusions']:
                    for test_id in c['test_ids']:
                        self.assertIn(test_id,soup.select_one('#methods details').get_text())
                    self.assertNotIn(c['summary'],soup.select_one('#summary').get_text())
                for test in result['tests']:
                    self.assertNotIn(test['id'],soup.select_one('#summary').get_text())
                self.assertEqual(model['tests'],result['tests'])
                self.assertEqual(model['conclusions'],result['conclusions'])

    def test_progressive_disclosure_keeps_charts_early_and_all_details_accessible(self):
        model=self.model('boolean','datetime');report.render_figures(model,self.root,disabled=True)
        soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
        ids=[s['id'] for s in soup.select('main > section')]
        self.assertLess(ids.index('figures'),ids.index('methods'))
        for sid in ('source','plan','methods','attachments'):
            detail=soup.select_one('#'+sid+' > details')
            self.assertIsNotNone(detail)
            self.assertFalse(detail.has_attr('open'))
            self.assertIsNotNone(detail.select_one('summary'))
        reading=soup.select('#comparison table')
        self.assertEqual(len(reading),1)
        self.assertLessEqual(len(reading[0].select('thead th')),4)
        self.assertEqual(len(reading[0].select('tbody tr')),len(model['methods']))
        self.assertIsNotNone(soup.select_one('#methods #method-overview'))
        self.assertFalse(soup.select('script,link,iframe'))

    def test_unavailable_and_descriptive_results_never_gain_inferential_findings(self):
        for n in (2,12):
            with self.subTest(n=n):
                result,chart,extra=result_for(n=n,permutations=0)
                model=report.build_model(result,chart,extra)
                findings=[b for s in model['sections'] if s['id']=='summary' for b in s['blocks'] if b['kind']=='finding']
                self.assertEqual([b['status'] for b in findings],[c['status'] for c in result['conclusions']])
                unavailable={c['status'] for c in result['conclusions'] if c['status'] in {'not_applicable','descriptive_only'}}
                self.assertTrue(unavailable)
                report.render_figures(model,self.root,disabled=True)
                md=report.render_markdown(model)
                for finding in findings:self.assertIn(report.md_text(finding['value']),md)

    def test_long_cells_and_nested_json_are_collapsed_complete_and_safe(self):
        long='保留完整说明，而不是截断后丢失。'*20+'<script>不能执行</script>'
        nested={'interval':{'low':-.123456789,'high':.987654321},'flags':[True,None],
                'literal':'</code><script>alert(1)</script> ```json & <x>'}
        table={'id':'long-cells','headers':['普通字段','说明','任意结构化字段'],'rows':[['短文本',long,nested]],'note':''}
        soup=BeautifulSoup(report._table_html(table),'html.parser')
        cells=soup.select('tbody td')
        self.assertIsNone(cells[0].select_one('details'))
        for cell in cells[1:]:
            self.assertIsNotNone(cell.select_one('details.cell-details > summary'))
            self.assertFalse(cell.details.has_attr('open'))
        self.assertEqual(cells[1].select_one('.cell-content').get_text(),long)
        import json
        self.assertEqual(json.loads(cells[2].code.get_text()),json.loads(report.format_value(nested)))
        self.assertTrue(cells[2].select('.json-key,.json-number,.json-string,.json-literal'))
        self.assertFalse(soup.select('script'))
        from markdown_it import MarkdownIt
        reading=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(report._table_md(table)),'html.parser')
        self.assertFalse(reading.select('script'))
        self.assertEqual([displayed_cell(c,reading) for c in reading.select('tbody td')],
                         ['短文本',long,json.loads(report.format_value(nested))])

    def test_rounding_near_threshold_preserves_original_decisions_and_values(self):
        for p,decision in ((.049999999,True),(.050000001,False)):
            with self.subTest(p=p):
                result,chart,extra=result_for()
                result['methods']=result['methods'][:1]
                result['tests']=result['tests'][:1]
                result['effects']=result['effects'][:1]
                result['method_plan']['items']=result['method_plan']['items'][:1]
                result['method_plan']['candidate_ids']=['pearson']
                result['tests'][0]['p_value']=p
                import inference
                result['multiplicity']=inference.apply_holm(result['tests'],result['alpha'])
                result['conclusions'],result['comparisons']=inference.summarize(result['methods'],result['tests'],result['effects'],alpha=result['alpha'])
                model=report.build_model(result,chart,extra);report.render_figures(model,self.root,disabled=True)
                soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
                cells=soup.select('#pearson-tests tbody td')
                self.assertEqual(cells[6].get_text(),'0.0500')
                self.assertEqual(cells[7].get_text(),'是' if decision else '否')
                self.assertEqual(model['tests'][0]['p_value'],p)
                self.assertEqual(model['conclusions'][0]['status'],'evidence' if decision else 'insufficient_evidence')

    def test_comparisons_have_short_reading_and_collapsed_structured_evidence(self):
        model=self.model();report.render_figures(model,self.root,disabled=True)
        soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
        cards=soup.select('#differences .comparison-card')
        self.assertEqual(len(cards),len(model['comparisons']))
        for card,comparison in zip(cards,model['comparisons']):
            detail=card.select_one('details.json-details')
            self.assertIsNotNone(detail)
            self.assertFalse(detail.has_attr('open'))
            import json
            data=json.loads(detail.code.get_text())
            self.assertEqual(data['method_ids'],comparison['method_ids'])
            self.assertEqual(data['evidence_relation'],comparison['evidence_relation'])
            self.assertEqual(data['direction_agreement'],comparison['direction_agreement'])
            self.assertLess(len(card.select_one('.comparison-reading').get_text()),120)
        md=report.render_markdown(model)
        self.assertIn('```json',md)
        self.assertFalse(soup.select('script,link,iframe'))

    def test_statistical_terms_follow_first_chinese_occurrence_only(self):
        for kinds in (('numeric','numeric'),('boolean','numeric'),('categorical','numeric'),
                      ('categorical','categorical'),('boolean','datetime')):
            with self.subTest(kinds=kinds):
                model=self.model(*kinds);report.render_figures(model,self.root,disabled=True)
                documents=[BeautifulSoup(report.render_html(model,self.root),'html.parser').get_text(' '),
                           report.render_markdown(model)]
                terms=[('多次检验的整体误报风险','family-wise error rate，FWER'),
                       ('逐步多重检验校正','Holm adjustment'),('p 值','p-value'),
                       ('效应量','effect size'),('置信区间','confidence interval，CI')]
                for document in documents:
                    self.assertNotIn('家族错误率',document)
                    for chinese,english in terms:
                        bilingual=chinese+'（'+english+'）'
                        self.assertEqual(document.count(bilingual),1,bilingual)
                        self.assertEqual(document.index(chinese),document.index(bilingual),bilingual)

    def test_method_names_are_bilingual_once_then_chinese_and_always_visible(self):
        self.assertEqual(report.METHOD_NAMES['pearson'],'皮尔森相关分析')
        self.assertEqual(report.METHOD_NAMES['spearman'],'斯皮尔曼等级相关分析')
        self.assertEqual(report.METHOD_NAMES['kendall_tau_b'],'肯德尔等级相关分析')
        from markdown_it import MarkdownIt
        for kinds in (('numeric','numeric'),('boolean','numeric'),('categorical','numeric'),
                      ('categorical','categorical'),('boolean','datetime')):
            with self.subTest(kinds=kinds):
                model=self.model(*kinds);report.render_figures(model,self.root,disabled=True)
                soup=BeautifulSoup(report.render_html(model,self.root),'html.parser')
                md=report.render_markdown(model)
                reading=BeautifulSoup(MarkdownIt('commonmark').enable('table').render(md),'html.parser')
                label=lambda mid:report.METHOD_NAMES[mid]+'（'+report.METHOD_TERMS[mid]+'）'
                findings=soup.select('#summary .finding')
                self.assertEqual(len(findings),len(model['conclusions']))
                summary_md=md.split('## 先看结论',1)[1].split('\n## ',1)[0]
                for finding,conclusion in zip(findings,model['conclusions']):
                    methods=finding.select_one('.finding-methods')
                    self.assertIsNotNone(methods)
                    self.assertIsNone(methods.find_parent('details'))
                    for mid in conclusion['method_ids']:
                        self.assertIn(label(mid),methods.get_text())
                        self.assertIn(label(mid),summary_md)
                table=soup.select_one('#reading-overview')
                self.assertEqual(table.th.get_text(),'分析方法')
                expected=[report.METHOD_NAMES[m['id']] for m in model['methods']]
                self.assertEqual([r.td.get_text() for r in table.select('tbody tr')],expected)
                self.assertTrue(all(not r.td.select('details') for r in table.select('tbody tr')))
                self.assertIsNone(table.find_parent('details'))
                md_table=reading.select('table')[0]
                self.assertEqual([r.td.get_text() for r in md_table.select('tbody tr')],expected)
                self.assertTrue(all(not r.td.select('a') for r in md_table.select('tbody tr')))
                for heading,comparison in zip(soup.select('#differences .comparison-card h3'),model['comparisons']):
                    self.assertEqual(heading.get_text(),' 与 '.join(report.METHOD_NAMES[mid] for mid in comparison['method_ids']))
                    self.assertIsNone(heading.find_parent('details'))
                for document in (soup.get_text(' '),md):
                    for method in model['methods']:
                        name=label(method['id']);chinese=report.METHOD_NAMES[method['id']]
                        self.assertEqual(document.count(name),1,name)
                        self.assertEqual(document.index(chinese),document.index(name),name)
                        self.assertGreater(document.count(chinese),1)


if __name__=='__main__': unittest.main()
