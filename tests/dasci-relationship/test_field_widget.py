"""Exercise the shipped inline widget, including host message submission."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/dasci-relationship/scripts'))
import interaction as flow


class FieldWidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private-data.csv'
        pd.DataFrame({f'字段{i}': range(12) for i in range(1, 66)}).to_csv(self.path, index=False)

    def widget(self, **extra):
        result = flow.advance({'action': {'input': str(self.path)},
                               'host': {'inline_widget': True, 'max_options': 4}, **extra})
        self.assertEqual(result['step'], 'needs_columns')
        self.assertIsNone(result['analysis_args'])
        soup = BeautifulSoup(result['question']['widget']['widget_code'], 'html.parser')
        return result, soup, json.loads(soup.select_one('#field-data').string)

    def test_all_fields_are_present_and_scroll_independent_of_preview(self):
        result, soup, model = self.widget(view={'page': 3})
        self.assertEqual(len(result['catalog']['items']), 20)
        self.assertEqual([f['index'] for f in model['fields']], list(range(1, 66)))
        self.assertRegex(soup.style.string, r'\.field-list\{[^}]*overflow-y:auto')
        self.assertIsNone(soup.find(['html', 'head', 'body']))
        self.assertIsNone(soup.find('form'))  # WorkBuddy's widget ingress rejects form tags.
        self.assertEqual(json.loads(result['question']['widget']['loading_messages']), ['正在准备完整字段列表'])

    def test_markup_names_are_text_and_payload_omits_raw_cells_and_paths(self):
        name = '</script><script>globalThis.injected=true</script><img src=x onerror=boom()>'
        pd.DataFrame({name: ['private-cell-' + str(i) for i in range(12)], 'B': range(12)}).to_csv(self.path, index=False)
        result, soup, model = self.widget()
        self.assertEqual(model['fields'][0]['name'], name)
        code = result['question']['widget']['widget_code']
        self.assertNotIn(name, code)
        self.assertNotIn('private-cell-', code)
        self.assertNotIn(str(self.path), code)
        self.assertEqual(len(soup.find_all('script')), 2)
        self.assertEqual(len(soup.find_all('img')), 0)
        self.assertNotRegex(code, r'\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(')

    def test_unavailable_fields_keep_reasons_and_user_type_override_is_retained(self):
        pd.DataFrame({'customer_id': range(100, 112), 'amount': range(12),
                      '常量': [1] * 12, '空列': [None] * 12}).to_csv(self.path, index=False)
        initial, _, model = self.widget()
        self.assertFalse(model['fields'][0]['selectable'])
        for item in model['fields'][2:]:
            self.assertFalse(item['selectable'])
            self.assertTrue(item['reason'])
        state = flow.advance({'state': initial['state'], 'action': {'columns': {
            '1': {'index': 1, 'type': 'numeric'}}}})['state']
        result = flow.advance({'state': state, 'host': {'inline_widget': True}})
        soup = BeautifulSoup(result['question']['widget']['widget_code'], 'html.parser')
        item = json.loads(soup.select_one('#field-data').string)['fields'][0]
        self.assertTrue(item['selectable'])
        self.assertEqual(item['kind'], 'numeric')
        ready = flow.advance({'state': result['state'], 'action': {
            'pair': {'x': {'index': 1}, 'y': {'index': 2}},
            'context_key': result['question']['context_key']}})
        self.assertEqual(ready['step'], 'ready')
        self.assertEqual(ready['state']['columns'][0]['type'], 'numeric')

    def test_explicit_search_filters_without_renumbering(self):
        _, _, model = self.widget(view={'search': '字段65'})
        self.assertEqual([f['index'] for f in model['fields']], [65])

    @unittest.skipUnless(shutil.which('node'), 'Node is used for widget-script verification')
    def test_real_script_searches_swaps_submits_and_cancels(self):
        result, soup, model = self.widget()
        # Include an unavailable field to exercise button state and its reason.
        model['fields'].append({'index': 66, 'name': '常量', 'kind': 'numeric',
                                'selectable': False, 'reason': '常量', 'semantic_hint': None})
        script = soup.find_all('script')[1].string
        harness = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
class Element {
  constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.attributes={};this.disabled=false;this.value='';this.textContent='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(k,v){this.attributes[k]=v;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  fire(name){if(!this.disabled)this.listeners[name]?.({target:this,preventDefault(){}});}
}
function start(){
  const ids=['field-data','x','y','search-x','search-y','swap','submit','cancel','direction','status','count-x','count-y'];
  const elements=new Map(ids.map(id=>[id,new Element()]));
  elements.get('field-data').textContent=JSON.stringify(input.model);
  const messages=[];
  vm.runInContext(input.script,vm.createContext({document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag)},sendPrompt:text=>messages.push(text)}));
  return {e:id=>elements.get(id),messages};
}
const {e,messages}=start();
assert.equal(e('x').children.length,66);assert.equal(e('y').children.length,66);
assert.equal(e('x').children[65].disabled,true);
assert.equal(e('submit').disabled,true);assert.equal(e('swap').disabled,true);
assert.equal(messages.length,0);
e('submit').fire('click');assert.equal(messages.length,0);
e('search-x').value='字段65';e('search-x').fire('input');
assert.equal(e('x').children.length,1);assert.match(e('x').children[0].children[0].textContent,/#65/);
e('x').children[0].fire('click');
e('search-y').value='#65 ';e('search-y').fire('input');e('y').children[0].fire('click');
assert.equal(e('submit').disabled,true);e('submit').fire('click');assert.equal(messages.length,0);
e('search-y').value='字段13';e('search-y').fire('input');e('y').children[0].fire('click');
assert.equal(e('submit').disabled,false);
e('search-x').value='不存在';e('search-x').fire('input');assert.equal(e('x').children.length,0);
assert.equal(e('submit').disabled,false); // Filtering never changes a deliberate choice.
e('swap').fire('click');assert.equal(e('x').children.length,66);assert.equal(e('y').children.length,66);
assert.equal(e('direction').textContent,'#13 字段13 → #65 字段65');assert.equal(messages.length,0);
e('submit').fire('click');e('submit').fire('click');
assert.equal(messages.length,1);assert.ok(messages[0].length<500);
const payload=JSON.parse(messages[0]);
assert.deepEqual(payload,{pair:{x:{index:13},y:{index:65}},context_key:input.model.context_key});
for(const id of ['submit','swap','cancel','search-x','search-y'])assert.equal(e(id).disabled,true);
assert.ok(e('x').children.every(button=>button.disabled));
const cancelled=start();cancelled.e('x').children[0].fire('click');cancelled.e('y').children[1].fire('click');
cancelled.e('cancel').fire('click');cancelled.e('submit').fire('click');
assert.equal(cancelled.messages.length,0);assert.equal(cancelled.e('submit').disabled,true);
process.stdout.write(JSON.stringify(payload));
'''
        proc = subprocess.run(['node', '-e', harness], input=json.dumps({'model': model, 'script': script}),
                              capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertNotIn(str(self.path), proc.stdout)
        ready = flow.advance({'state': result['state'], 'action': payload})
        self.assertEqual(ready['step'], 'ready')
        self.assertEqual(ready['summary']['plot']['x']['column_index'], 13)
        self.assertEqual(ready['summary']['plot']['y']['column_index'], 65)


if __name__ == '__main__':
    unittest.main()
