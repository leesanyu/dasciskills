"""C6/C10: real offline Chromium layouts and a rendered Markdown reading copy.

Acceptance-only dependencies: websockets, markdown-it-py, Chromium and local CJK
fonts. None is required for normal skill execution. Evidence is ignored.
"""
import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import numpy as np
import pandas as pd
from markdown_it import MarkdownIt
from websockets.sync.client import connect

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import reporting as report


class Browser:
    def __init__(self,chrome):
        self.tmp=tempfile.TemporaryDirectory(prefix='report-browser-');self.seq=0;self.requests=[]
        self.proc=subprocess.Popen([str(chrome),'--headless','--no-sandbox','--disable-gpu',
                                   '--disable-background-networking','--no-first-run','--no-default-browser-check',
                                   '--remote-debugging-port=0','--user-data-dir='+self.tmp.name,'about:blank'],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        port_file=Path(self.tmp.name)/'DevToolsActivePort'
        for _ in range(200):
            if port_file.exists():break
            if self.proc.poll() is not None:raise RuntimeError('Chromium failed to start')
            time.sleep(.05)
        port=int(port_file.read_text().splitlines()[0])
        with urlopen(f'http://127.0.0.1:{port}/json/list') as response:targets=json.load(response)
        self.ws=connect(next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page'),max_size=64*1024*1024,proxy=None)
        self.call('Page.enable');self.call('Network.enable')
        self.call('Network.setBlockedURLs',{'urls':['http://*','https://*']})
        self.version=self.call('Browser.getVersion')

    def call(self,method,params=None):
        self.seq+=1;seq=self.seq;self.ws.send(json.dumps({'id':seq,'method':method,'params':params or {}}))
        while True:
            message=json.loads(self.ws.recv(timeout=20))
            if message.get('method')=='Network.requestWillBeSent':self.requests.append(message['params']['request']['url'])
            if message.get('id')==seq:
                if 'error' in message:raise RuntimeError(message['error'])
                return message.get('result',{})

    def evaluate(self,expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:raise RuntimeError(result['exceptionDetails'])
        return result['result'].get('value')

    def open(self,path,width,height):
        self.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
        self.call('Page.navigate',{'url':Path(path).resolve().as_uri()})
        for _ in range(200):
            if self.evaluate('document.readyState==="complete" && [...document.images].every(i=>i.complete)'):break
            time.sleep(.03)
        self.evaluate('document.fonts.ready.then(()=>true)')
        self.evaluate('window.scrollTo(0,0)')

    def screenshot(self,path):
        data=self.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})['data']
        path.write_bytes(base64.b64decode(data))

    def close(self):
        self.ws.close();self.proc.terminate()
        try:self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        self.tmp.cleanup()


def generate_samples(root):
    rng=np.random.default_rng(811);n=120
    long_name='含中文与空格的很长字段名称，用于检验报告在窄屏和图表中的文字呈现 | <script>仅文本</script>'
    samples=[('numeric',pd.DataFrame({long_name:np.arange(n), '响应值':np.arange(n)*.3+rng.normal(size=n)}),['numeric','numeric'],False),
             ('categorical',pd.DataFrame({'地区类别':[f'地区{i%17:02d} 中文长标签' for i in range(544)],'产品分类':[f'产品{(i//17)%16:02d}' for i in range(544)]}),['categorical','categorical'],False),
             ('mixed',pd.DataFrame({'业务分组':['甲','乙','丙']*40,'观测数量':rng.normal(size=n)+np.arange(n)%3}),['categorical','numeric'],False),
             ('datetime',pd.DataFrame({'记录时间':pd.date_range('2024-01-01',periods=n).strftime('%Y-%m-%d'),'业务状态':['进行中','已完成']*60}),['datetime','boolean'],False),
             ('no-chart',pd.DataFrame({'有序等级':['低','中','高']*4,'业务数量':range(12)}),['ordinal','numeric'],True)]
    results={}
    for name,frame,kinds,no_chart in samples:
        path=root/f'{name}.csv';frame.to_csv(path,index=False);out=root/name
        argv=['analyze','--input',str(path),'--col1-index','1','--col2-index','2','--col1-type',kinds[0],'--col2-type',kinds[1],
              '--permutations','0' if no_chart else '3','--out',str(out)]
        if no_chart:argv+=['--no-chart']
        if kinds[0]=='ordinal':argv+=['--col1-order','["低","中","高"]']
        result=dr.cmd_analyze(dr.build_parser().parse_args(argv));results[name]={'result':result,'argv':argv}
    return results


CHECK="""(()=>{
const style=s=>getComputedStyle(document.querySelector(s));
const images=[...document.images].map(i=>({loaded:i.complete&&i.naturalWidth>0,width:i.getBoundingClientRect().width,parent:i.parentElement.getBoundingClientRect().width}));
return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,
sections:[...document.querySelectorAll('main>section')].map(s=>s.id),
sectionBoxes:[...document.querySelectorAll('main>section')].map(s=>({left:s.getBoundingClientRect().left,right:s.getBoundingClientRect().right})),
nav:[...document.querySelectorAll('nav a')].every(a=>!!document.querySelector(a.getAttribute('href'))),
template:{id:document.documentElement.dataset.templateId,version:document.documentElement.dataset.templateVersion},
styles:{background:style('body').backgroundColor,text:style('body').color,font:style('body').fontFamily,size:style('body').fontSize,line:style('body').lineHeight,
radius:style('section').borderRadius,h1:style('h1').fontSize,h2:style('h2').fontSize,card:style('.card').backgroundColor,columns:style('.cards').gridTemplateColumns},
images,overflowTables:[...document.querySelectorAll('.table-scroll')].filter(t=>t.scrollWidth>t.clientWidth).length,
closedDetails:[...document.querySelectorAll('main > section > details')].map(d=>({id:d.parentElement.id,closed:!d.open})),
readingTable:{columns:document.querySelectorAll('#reading-overview th').length,
width:document.querySelector('#reading-overview').getBoundingClientRect().width,
parent:document.querySelector('#reading-overview').parentElement.clientWidth},
collapsedCells:[...document.querySelectorAll('td details.cell-details')].every(d=>!d.open),
comparisonCount:document.querySelectorAll('#differences .comparison-card').length,
chinese:document.body.innerText.includes('数据关系分析报告'),
css:document.querySelector('style').textContent};})()"""


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--chrome',default='/root/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome')
    parser.add_argument('--out',default=str(Path(__file__).resolve().parents[2] / 'evidence' / 'dasci-relationship' / 'unified-analysis-report' / 't3' / 'visual'));args=parser.parse_args()
    root=Path(args.out).resolve();root.mkdir(parents=True,exist_ok=True)
    results=generate_samples(root);browser=Browser(args.chrome);records=[];css=None;reference={}
    try:
        for name,sample in results.items():
            path=Path(sample['result']['report_html_path'])
            for width,height in [(1440,1000),(390,844)]:
                browser.open(path,width,height);record=browser.evaluate(CHECK)
                assert record['documentWidth']<=width+1,(name,width,record['documentWidth'])
                assert record['sections']==report.SECTION_IDS
                assert record['nav'] and record['chinese']
                assert record['template']==sample['result']['report_template']
                assert all(i['loaded'] and i['width']<=i['parent']+1 for i in record['images'])
                assert all(s['left']>=0 and s['right']<=width+1 for s in record['sectionBoxes'])
                assert record['styles']['background']=='rgb(245, 247, 251)'
                assert record['styles']['radius']=='12px'
                assert record['styles']['size']=='16px'
                assert len(record['styles']['columns'].split())==(4 if width==1440 else 2)
                assert {d['id'] for d in record['closedDetails']}==report.COLLAPSED_SECTIONS
                assert all(d['closed'] for d in record['closedDetails'])
                assert record['readingTable']['columns']<=4
                assert record['readingTable']['width']<=record['readingTable']['parent']+1
                assert record['collapsedCells']
                assert record['comparisonCount']==len(sample['result']['comparisons'])
                if css is None:css=record['css']
                assert record.pop('css')==css
                if width in reference:assert record['styles']==reference[width],(name,width,'style drift')
                else:reference[width]=record['styles']
                browser.screenshot(root/f'{name}-{width}-top.png')
                browser.evaluate('document.querySelector("#figures").scrollIntoView({behavior:"instant"})')
                browser.screenshot(root/f'{name}-{width}-figures.png')
                browser.evaluate('document.querySelector("#comparison").scrollIntoView({behavior:"instant"})')
                browser.screenshot(root/f'{name}-{width}-reading.png')
                browser.evaluate('document.querySelector("#differences").scrollIntoView({behavior:"instant"})')
                browser.screenshot(root/f'{name}-{width}-differences.png')
                browser.evaluate('document.querySelector("#methods details summary").click()')
                interaction=browser.evaluate('''(()=>{
const detail=[...document.querySelectorAll('#methods td details.cell-details')].find(d=>d.querySelector('.json-key'));
const content=detail.querySelector('.cell-content');
const closed=!detail.open;
detail.querySelector('summary').click();
const key=detail.querySelector('.json-key'),string=detail.querySelector('.json-string');
return {closed,open:detail.open,visible:content.getBoundingClientRect().height>0,
complete:content.textContent.length>0,highlight:key&&string&&getComputedStyle(key).color!==getComputedStyle(string).color,
pageWidth:document.documentElement.scrollWidth};})()''')
                assert interaction['closed'] and interaction['open'] and interaction['visible'] and interaction['complete']
                assert interaction['highlight'] and interaction['pageWidth']<=width+1
                record['cellInteraction']=interaction
                if name=='categorical':
                    expanded=browser.evaluate('({open:document.querySelector("#methods details").open,overflow:[...document.querySelectorAll("#methods .table-scroll")].some(t=>t.scrollWidth>t.clientWidth),pageWidth:document.documentElement.scrollWidth})')
                    assert expanded['open'] and expanded['overflow'] and expanded['pageWidth']<=width+1
                    browser.evaluate('document.querySelector("#method-overview").scrollIntoView({behavior:"instant"})')
                    browser.screenshot(root/f'{name}-{width}-table.png')
                    record['expanded']=expanded
                records.append({'sample':name,'viewport':[width,height],**record})
        copy=root/'isolated';copy.mkdir(exist_ok=True);standalone=copy/'copied.html'
        shutil.copyfile(results['datetime']['result']['report_html_path'],standalone)
        browser.open(standalone,390,844)
        copied=browser.evaluate('({images:[...document.images].every(i=>i.naturalWidth>0),text:document.body.innerText.includes("日历")})')
        assert all(copied.values());browser.screenshot(root/'copied-html-390.png')
        reader=MarkdownIt('commonmark').enable('table');reading=[]
        for name,sample in results.items():
            md=Path(sample['result']['report_md_path'])
            # Reading copy stays beside the relative chart/CSV resources.
            page=md.parent/'markdown-reading.html'
            page.write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:16px/1.65 "Microsoft YaHei",sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{display:block;overflow:auto;border-collapse:collapse}td,th{border:1px solid #E2E8F0;padding:8px;min-width:100px}</style><body>'+reader.render(md.read_text())+'</body></html>')
            browser.open(page,1440,1000)
            state=browser.evaluate('({images:[...document.images].every(i=>i.complete&&i.naturalWidth>0),count:document.images.length,tables:document.querySelectorAll("table").length,chinese:document.body.innerText.includes("数据关系分析报告")})')
            assert state['images'] and state['chinese'] and state['tables']>0
            assert state['count']==len(sample['result']['chart_paths'])
            browser.screenshot(root/f'{name}-markdown.png');reading.append({'sample':name,**state})
        assert not any(url.startswith(('http:','https:')) for url in browser.requests),browser.requests
        (root/'acceptance.json').write_text(json.dumps({'browser':browser.version,'font':'Microsoft YaHei (system installed)',
            'markdown_reader':'markdown-it-py 3.0.0 commonmark + table','viewports':[[1440,1000],[390,844]],'reports':records,
            'copied_html':copied,'markdown_reading':reading,'remote_requests':[],
            'samples':{k:{'argv':v['argv'],'report_html_path':v['result']['report_html_path'],'report_md_path':v['result']['report_md_path']} for k,v in results.items()}},ensure_ascii=False,indent=2))
        print('PASS: 5 reports × 2 viewports; real computed styles/layout/images; isolated HTML; 5 Markdown reading copies; no remote requests.')
    finally:browser.close()


if __name__=='__main__':main()
