"""A submitted X→Y pair chooses fields and direction in one action."""
from http.client import HTTPResponse
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import interaction as flow
import pair_picker


class PairPickerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data.csv'
        pd.DataFrame({'A': range(12), 'B': [v*v for v in range(12)],
                      '等级': ['低', '中', '高']*4, '常量': [1]*12}).to_csv(self.path, index=False)
        self.request = {'action': {'input': str(self.path)}}

    def pair(self, x=1, y=2, **extra):
        with patch.object(dr.multi, 'analyze_pair', side_effect=AssertionError('selection ran statistics')):
            return flow.advance({'action': {'input': str(self.path), 'pair': {
                'x': {'index': x}, 'y': {'index': y}}, **extra}})

    def test_ordered_pair_is_ready_without_second_confirmation(self):
        for x, y in ((1, 2), (2, 1)):
            with self.subTest(x=x):
                result = self.pair(x, y)
                self.assertEqual(result['step'], 'ready')
                self.assertIsNone(result['question'])
                self.assertEqual(result['summary']['plot']['x']['column_index'], x)
                self.assertEqual(result['summary']['plot']['y']['column_index'], y)
                self.assertEqual([c['index'] for c in result['state']['columns']], [1, 2])
                argv = result['analysis_args']
                self.assertEqual(argv[argv.index('--plot-x')+1], f'col{x}')

    def test_default_pair_and_duplicate_pair_never_run(self):
        default = self.pair(source='default')
        self.assertEqual(default['step'], 'needs_file')
        duplicate = self.pair(1, 1)
        self.assertFalse(duplicate['ok'])
        self.assertEqual(duplicate['step'], 'needs_columns')
        self.assertIsNone(duplicate['analysis_args'])

    def test_pair_preserves_existing_semantics_while_only_reversing_axes(self):
        initial = flow.advance({'action': {'input': str(self.path), 'columns': {
            '1': {'index': 3, 'type': 'ordinal', 'order': ['低', '中', '高']},
            '2': {'index': 1}}}})
        changed = flow.advance({'state': initial['state'], 'action': {
            'pair': {'x': {'index': 1}, 'y': {'index': 3}}}})
        self.assertEqual(changed['step'], 'ready')
        self.assertEqual(changed['state']['columns'], initial['state']['columns'])
        self.assertEqual(changed['state']['plot_x'], 'col2')

    def test_missing_semantics_is_still_required(self):
        result = self.pair(3, 1)
        self.assertEqual(result['step'], 'needs_semantics')
        self.assertIsNone(result['analysis_args'])
        corrected = flow.advance({'state': result['state'], 'action': {'pair': {
            'x': {'index': 3, 'type': 'ordinal', 'order': ['低', '中', '高']},
            'y': {'index': 1}}}})
        self.assertEqual(corrected['step'], 'ready')
        self.assertEqual(corrected['summary']['plot']['x']['column_index'], 3)

    def test_pair_can_wait_for_file_and_sheet_without_losing_direction(self):
        pending = flow.advance({'action': {'pair': {'x': {'name': 'B'}, 'y': {'name': 'A'}}}})
        self.assertEqual(pending['step'], 'needs_file')
        bound = flow.advance({'state': pending['state'], 'action': {'input': str(self.path)}})
        self.assertEqual(bound['summary']['plot']['x']['label'], 'B')
        excel = Path(self.tmp.name) / 'data.xlsx'
        pd.read_csv(self.path).to_excel(excel, index=False)
        pending = flow.advance({'action': {'input': str(excel), 'pair': {'x': {'index': 2}, 'y': {'index': 1}}}})
        self.assertEqual(pending['step'], 'needs_sheet')
        bound = flow.advance({'state': pending['state'], 'action': {'sheet': {'index': 1}}})
        self.assertEqual(bound['summary']['plot']['x']['column_index'], 2)

    def test_pair_rejects_conflicting_or_malformed_axes(self):
        for action in ({'pair': {'x': {'index': 1}}},
                       {'pair': {'x': {'index': 1}, 'y': {'index': 2}}, 'plot_x': 'col1'},
                       {'pair': {'x': {'index': 1}, 'y': {'index': 2}}, 'columns': {}},
                       {'pair': {'x': {'index': True}, 'y': {'index': 2}}}):
            with self.subTest(action=action), self.assertRaises(dr.UserError):
                flow.advance({'action': {'input': str(self.path), **action}})

    def server(self):
        session = pair_picker.PickerSession(self.request)
        session.origin = 'http://127.0.0.1:12345'
        return session

    def http(self, session, endpoint='', value=None, **headers):
        # Exercise BaseHTTPRequestHandler parsing and actual response framing
        # without opening a socket (the execution sandbox prohibits sockets).
        body = json.dumps(value).encode() if value is not None else b''
        headers = {'Host': '127.0.0.1:12345', 'Content-Type': 'application/json',
                   'Content-Length': str(len(body)), **headers}
        method = 'POST' if value is not None else 'GET'
        raw = f'{method} {session.session_path}{endpoint} HTTP/1.0\r\n'
        raw += ''.join(f'{k}: {v}\r\n' for k, v in headers.items())+'\r\n'
        class Transport:
            def __init__(self, data):
                self.input = BytesIO(data)
                self.output = BytesIO()
            def makefile(self, *args, **kwargs):
                return self.input
            def sendall(self, data):
                self.output.write(data)
        transport = Transport(raw.encode()+body)
        pair_picker.PickerHandler(transport, ('127.0.0.1', 1), SimpleNamespace(session=session))
        response = HTTPResponse(SimpleNamespace(makefile=lambda *a, **k: BytesIO(transport.output.getvalue())))
        response.begin()
        content = response.read()
        result = json.loads(content) if 'application/json' in response.headers['Content-Type'] else content.decode()
        return response.status, result

    def test_http_submission_matches_actual_published_report(self):
        server = self.server()
        status, page = self.http(server)
        self.assertEqual(status, 200)
        self.assertIn('交换', page)
        self.assertIsNone(server.result)
        status, result = self.http(server, 'pair', {'x': {'index': 2}, 'y': {'index': 1}})
        self.assertEqual(status, 200)
        self.assertEqual(result['step'], 'ready')
        argv = result['analysis_args']+['--out', self.tmp.name, '--no-chart', '--permutations', '3']
        analyzed = dr.cmd_analyze(dr.build_parser().parse_args(argv))
        self.assertEqual(analyzed['publication']['status'], 'complete')
        self.assertEqual(analyzed['plot'], result['summary']['plot'])

    def test_http_error_can_be_corrected_and_cancel_does_not_confirm(self):
        server = self.server()
        status, result = self.http(server, 'pair', {'x': {'index': 1}, 'y': {'index': 1}})
        self.assertEqual(status, 400)
        self.assertIsNone(server.result)
        status, cancelled = self.http(server, 'cancel', {})
        self.assertEqual(status, 200)
        self.assertTrue(cancelled['cancelled'])
        self.assertEqual(cancelled['step'], 'cancelled')
        self.assertIsNone(cancelled['question'])
        self.assertIsNone(cancelled['analysis_args'])
        self.assertFalse(cancelled['state']['confirmed'])

    def test_http_rejects_foreign_origin_and_changed_source(self):
        server = self.server()
        status, result = self.http(server, 'pair', {'x': {'index': 1}, 'y': {'index': 2}},
                                   Origin='https://example.invalid')
        self.assertEqual(status, 403)
        self.assertIsNone(server.result)
        with self.path.open('a') as stream:
            stream.write('12,144,低,1\n')
        status, result = self.http(server, 'pair', {'x': {'index': 1}, 'y': {'index': 2}})
        self.assertEqual(status, 409)
        self.assertIsNone(server.result['analysis_args'])

    def test_page_escapes_markup_and_retains_all_physical_fields(self):
        name = '</script><script>globalThis.injected=true</script>'
        pd.DataFrame({name: range(12), 'B': range(12)}).to_csv(self.path, index=False)
        state = flow.advance({'action': {'input': str(self.path), 'columns': {'1': {'index': 1}}}})['state']
        session = pair_picker.PickerSession({'state': state})
        self.assertEqual([c['index'] for c in session.model['columns']], [1, 2])
        self.assertNotIn(name, session.page.decode())
        encoded = re.search(r'<script type="application/json" id="data">(.*?)</script>', session.page.decode(), re.S)[1]
        self.assertEqual(json.loads(encoded)['columns'][0]['display_name'], name)

    def test_page_preserves_a_single_explicit_business_type(self):
        pd.DataFrame({'customer_id': range(100, 112), 'amount': range(12)}).to_csv(self.path, index=False)
        initial = flow.advance({'action': {'input': str(self.path), 'columns': {
            '1': {'index': 1, 'type': 'numeric'}}}})
        session = pair_picker.PickerSession({'state': initial['state']})
        first = session.model['columns'][0]
        self.assertTrue(first['selectable'])
        self.assertEqual(first['effective_kind'], 'numeric')
        self.assertEqual(first['type_source'], 'user')

    @unittest.skipUnless(shutil.which('node'), 'Node is used only for page-script verification')
    def test_page_events_swap_and_submit_one_ordered_pair(self):
        session = self.server()
        script = re.findall(r'<script>(.*?)</script>', session.page.decode(), re.S)[0]
        # A minimal DOM adapter executes the shipped script and event handlers.
        # This is component coverage, not a browser rendering assertion.
        harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Element{
  constructor(tag='div'){this.tag=tag;this.options=[];this.children=[];this.listeners={};this.disabled=false;this._value='';this.textContent='';}
  get value(){return this._value;}
  set value(v){this._value=this.tag==='select'&&!this.options.some(o=>o.value===String(v))?'':String(v);}
  replaceChildren(...children){this.children=children;if(this.tag==='select'){this.options=[...children];this._value=children[0]?.value||'';}}
  add(option){this.options.push(option);}
  append(child){this.children.push(child);}
  insertRow(){const row=new Element('tr');this.children.push(row);return row;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  fire(name){if(!this.disabled)this.listeners[name]?.({target:this,preventDefault(){}});}
}
const elements=new Map();
for(const id of ['data','context','x','y','swap','submit','error','direction','preview','catalog','form','cancel','search-x','search-y'])elements.set(id,new Element(['x','y'].includes(id)?'select':'div'));
elements.get('data').textContent=JSON.stringify(input.model);
const document={getElementById:id=>elements.get(id),createElement:tag=>new Element(tag)};
let requests=[];
const context=vm.createContext({document,URL,location:{href:'http://127.0.0.1:12345/session/'},
  Option:class{constructor(text,value){this.text=text;this.value=String(value);}},
  fetch:async(url,options)=>{requests.push({url:String(url),body:JSON.parse(options.body)});return {ok:true,json:async()=>({step:'ready'})};}});
vm.runInContext(input.script,context);
const e=id=>elements.get(id);
assert.equal(e('submit').disabled,true);assert.equal(e('swap').disabled,true);
e('x').value='1';e('x').fire('change');e('y').value='1';e('y').fire('change');assert.equal(e('submit').disabled,true);
e('y').value='2';e('y').fire('change');assert.equal(e('submit').disabled,false);
assert.equal(requests.length,0);
e('swap').fire('click');assert.equal(e('x').value,'2');assert.equal(e('y').value,'1');
assert.equal(e('direction').textContent,'B → A（X → Y）');assert.equal(requests.length,0);
e('form').fire('submit');
setImmediate(()=>{
  assert.equal(requests.length,1);assert.deepEqual(requests[0].body,{x:{index:2},y:{index:1}});
  assert.equal(e('submit').disabled,true);assert.equal(e('swap').disabled,true);
  assert.match(e('direction').textContent,/已提交/);
  process.stdout.write(JSON.stringify({pair:requests[0].body,requests:requests.length,direction:'B → A',browser_rendering_verified:false}));
});
'''
        proc = subprocess.run(['node', '-e', harness], input=json.dumps({'model': session.model, 'script': script}),
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
        captured = json.loads(proc.stdout)
        result = flow.advance({'state': session.state, 'action': {'pair': captured['pair']}})
        self.assertEqual(result['step'], 'ready')
        self.assertEqual(result['summary']['plot']['x']['label'], 'B')
        self.assertEqual(result['summary']['plot']['y']['label'], 'A')


if __name__ == '__main__':
    unittest.main()
