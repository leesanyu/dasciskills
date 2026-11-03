"""Incremental selection; computes a method plan without running statistics."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pandas as pd

import data_relationship as dr
import selection as nav
import plotting
import field_widget


TYPES = {'auto', 'numeric', 'boolean', 'categorical', 'ordinal', 'datetime'}


def _object(value, allowed: set[str], label: str):
    if not isinstance(value, dict) or set(value) - allowed:
        raise dr.UserError(f'{label} 必须是对象，且只能包含：{", ".join(sorted(allowed))}。')


def _typed_fields(value: dict, schema: dict):
    for key, expected in schema.items():
        if key in value and type(value[key]) is not expected:
            raise dr.UserError(f'{key} 的类型必须为 {expected.__name__}。')


def _selector(value: dict, *, semantics: bool):
    allowed = {'name', 'index'} | ({'type', 'order'} if semantics else set())
    _object(value, allowed, '选择器')
    _typed_fields(value, {'name': str, 'index': int, 'type': str, 'order': list})
    if 'index' in value and value['index'] < 1:
        raise dr.UserError('编号必须从 1 开始。')
    if value.get('type', 'auto') not in TYPES:
        raise dr.UserError('字段类型不受支持。')


def _columns_patch(value):
    _object(value, {'1', '2'}, '字段槽位')
    for column in value.values():
        if column is not None:
            _selector(column, semantics=True)


def _pair(value):
    _object(value, {'x', 'y'}, '坐标字段')
    if set(value) != {'x', 'y'}:
        raise dr.UserError('请同时指定 X 轴和 Y 轴字段。')
    for column in value.values():
        _selector(column, semantics=True)


def _validate(request: dict):
    _object(request, {'state', 'action', 'view', 'host'}, '请求')
    action = request.get('action', {})
    _object(action, {'input', 'sheet', 'columns', 'pair', 'context_key', 'methods', 'plot_x', 'explicit', 'confirm', 'source'}, '操作')
    _typed_fields(action, {'input': str, 'methods': str, 'explicit': bool, 'confirm': bool, 'source': str, 'plot_x': str, 'context_key': str})
    if action.get('source', 'submitted') not in {'submitted', 'default'}:
        raise dr.UserError('source 只能为 submitted 或 default。')
    if action.get('sheet') is not None:
        _selector(action['sheet'], semantics=False)
    if 'columns' in action:
        _columns_patch(action['columns'])
    if 'pair' in action:
        _pair(action['pair'])
        if {'columns', 'plot_x'} & action.keys():
            raise dr.UserError('pair 已指定字段和方向，不能同时传 columns 或 plot_x。')
    view = request.get('view', {})
    _object(view, {'page', 'search', 'all_columns'}, '目录视图')
    _typed_fields(view, {'page': int, 'search': str, 'all_columns': bool})
    host = request.get('host', {})
    _object(host, {'questions', 'multi_select', 'max_options', 'max_questions', 'inline_widget', 'tools'}, '宿主能力')
    _typed_fields(host, {'questions': bool, 'multi_select': bool, 'max_options': int, 'max_questions': int, 'inline_widget': bool, 'tools': list})
    if any(not isinstance(name, str) for name in host.get('tools', [])):
        raise dr.UserError('tools 必须是当前会话工具名组成的字符串数组。')
    if 'max_options' in host and host['max_options'] < 1:
        raise dr.UserError('max_options 必须至少为 1。')
    if host.get('max_questions', 2) < 1:
        raise dr.UserError('max_questions 必须至少为 1。')
    state = request.get('state', {})
    _object(state, {'input', 'sheet', 'columns', 'pending_columns', 'pending_pair', 'methods', 'plot_x', 'confirmed', 'confirmation_key'}, '状态')
    _typed_fields(state, {'methods': str, 'confirmed': bool, 'plot_x': str})
    if state.get('plot_x', 'auto') not in plotting.PLOT_X_CHOICES:
        raise dr.UserError('状态 plot_x 只能为 auto、col1 或 col2。')
    if state.get('input') is not None and not isinstance(state['input'], str):
        raise dr.UserError('状态 input 必须是路径字符串或 null。')
    if state.get('confirmation_key') is not None and not isinstance(state['confirmation_key'], str):
        raise dr.UserError('confirmation_key 必须是字符串或 null。')
    if state.get('sheet') is not None:
        _selector(state['sheet'], semantics=False)
    columns = state.get('columns', [None, None])
    if not isinstance(columns, list) or len(columns) != 2:
        raise dr.UserError('状态 columns 必须包含两个字段槽位。')
    for column in columns:
        if column is None:
            continue
        _object(column, {'index', 'original_name', 'display_name', 'type', 'order'}, '已绑定字段')
        _typed_fields(column, {'index': int, 'display_name': str, 'type': str})
        if not {'index', 'original_name', 'display_name', 'type', 'order'} <= column.keys():
            raise dr.UserError('已绑定字段缺少物理位置或语义。')
        if column['index'] < 1 or column['type'] not in TYPES:
            raise dr.UserError('已绑定字段的编号或类型无效。')
        if column['original_name'] is not None and not isinstance(column['original_name'], str):
            raise dr.UserError('原始列头必须为字符串或 null。')
        if column['order'] is not None and not isinstance(column['order'], list):
            raise dr.UserError('有序水平必须为数组或 null。')
    if 'pending_columns' in state:
        _columns_patch(state['pending_columns'])
    if state.get('pending_pair') is not None:
        _pair(state['pending_pair'])


def _field_question(items: list[dict], host: dict, detail: str | None, context_key: str) -> dict:
    title = '请同时选择 X 轴字段和 Y 轴字段；也可回复 #2 → #7（左 X、右 Y）。'
    if detail:
        title = detail + ' ' + title
    # sendPrompt is injected into the widget window, not an agent tool.
    if host.get('inline_widget', False) or {'widget_guidelines', 'show_widget'} <= set(host.get('tools', [])):
        return {'mode': 'widget', 'kind': 'needs_columns', 'title': title,
                'widget': field_widget.render(items, context_key, detail),
                'context_key': context_key, 'tool_arguments': None, 'submit_as': 'pair'}
    options = [{'label': f'#{item["index"]} {item["name"]}',
                'description': item.get('semantic_hint') or '', 'value': {'index': item['index']}}
               for item in items if item['selectable']]
    if 'max_options' in host and len(options) > host['max_options']:
        options = []  # Keep the full catalog available; accept field names/numbers.
    tool = host.get('questions', False)
    if tool and host.get('max_questions', 2) >= 2:
        questions = [{'id': axis, 'header': axis.upper() + ' 轴字段',
                      'title': f'请选择 {axis.upper()} 轴字段（名称或 #编号）', 'options': deepcopy(options),
                      'min_select': 1, 'max_select': 1, 'allows_text': True} for axis in ('x', 'y')]
    else:
        questions = [{'id': 'pair', 'header': '字段与方向', 'title': title, 'options': [],
                      'min_select': 1, 'max_select': 1, 'allows_text': True}]
    arguments = None
    if tool and len(questions) == 2 and len(options) >= 2:
        arguments = {'questions': [
            {'id': question['id'], 'header': question['header'], 'question': question['title'],
             'options': [{key: option[key] for key in ('label', 'description')} for option in options],
             'multi_select': False} for question in questions]}
    return {'mode': 'tool' if tool else 'text', 'kind': 'needs_columns', 'title': title,
            'questions': questions, 'submit_as': 'pair', 'options': [],
            'fields': items, 'tool_arguments': arguments, 'context_key': context_key,
            'min_select': 1, 'max_select': 1, 'allows_text': True}


def _question(step: str, catalog: dict | None, host: dict, detail: str | None,
              field_items: list[dict], context_key: str | None) -> dict | None:
    if step == 'ready':
        return None
    if step == 'needs_columns':
        return _field_question(field_items, host, detail, context_key)
    titles = {'needs_file': '请提供要分析的 CSV 或 Excel 文件路径。',
              'needs_sheet': '请选择工作表名称或 #编号；可翻页或按名称查找。',
              'needs_semantics': '请补齐字段业务类型/有序水平或修正方法选择。',
              'needs_confirmation': '是否按以上字段、横纵轴和方法计划开始分析？'}
    items = catalog['items'] if catalog else []
    choices = [{'label': f'#{item["index"]} {item["name"]}',
                'description': item.get('reason') or item.get('semantic_hint') or ''}
               for item in items if item.get('selectable', True)]
    if step == 'needs_semantics':
        choices = []  # Business meaning and full ordinal order require a text answer.
    if step == 'needs_confirmation':
        choices = [{'label': '开始分析', 'description': '按摘要中的组合运行分析。'},
                   {'label': '修改字段', 'description': '只修改需要调整的字段或语义。'}]
    can_use_tool = host.get('questions', False) and bool(choices) and (
        'max_options' not in host or len(choices) <= host['max_options'])
    return {'mode': 'tool' if can_use_tool else 'text', 'kind': step,
            'title': detail or titles[step], 'options': choices,
            'min_select': 1, 'max_select': 1, 'allows_text': True}


def advance(request: dict) -> dict:
    """Apply one submitted action, preserving valid choices and confirmation scope."""
    _validate(request)
    state = {'input': None, 'sheet': None, 'columns': [None, None], 'pending_columns': {},
             'pending_pair': None,
             'methods': 'auto', 'plot_x': 'auto', 'confirmed': False, 'confirmation_key': None,
             **deepcopy(request.get('state', {}))}
    action = request.get('action', {})
    if action.get('source') == 'default':
        action = {}
    if 'pair' in action:
        state['pending_pair'] = deepcopy(action['pair'])
    view, host = request.get('view', {}), request.get('host', {})
    catalog, preview, summary, semantic_context = None, None, None, None
    field_items, context_key = [], None
    warnings = []
    prior_key = state['confirmation_key']

    def finish(step: str, error: str | None = None, *, detail: str | None = None,
               analysis_args: list[str] | None = None):
        if step != 'ready':
            state['confirmed'] = False
        return {'ok': error is None, 'step': step, 'state': state, 'error': error,
                'catalog': catalog, 'preview': preview, 'summary': summary, 'semantic_context': semantic_context,
                'warnings': warnings,
                'question': _question(step, catalog, host, detail or error, field_items, context_key),
                'analysis_args': analysis_args}

    if action.get('plot_x', 'auto') not in plotting.PLOT_X_CHOICES:
        return finish('needs_confirmation', 'plot_x 只能为 auto、col1 或 col2；请指定所选两字段中的横轴。')
    if 'plot_x' in action:
        state['plot_x'] = action['plot_x']
    if 'methods' in action:
        state['methods'] = action['methods']
    raw_input = action.get('input', state['input'])
    if not raw_input:
        if 'sheet' in action:
            state['sheet'] = deepcopy(action['sheet'])
        state['pending_columns'].update(deepcopy(action.get('columns', {})))
        return finish('needs_file')
    try:
        path = dr.resolve_input(raw_input)
    except dr.UserError as exc:
        state.update(input=None, sheet=None, columns=[None, None], plot_x=action.get('plot_x', 'auto'), confirmed=False, confirmation_key=None)
        return finish('needs_file', str(exc))
    if str(path) != state['input']:
        pending = state['pending_columns'] if state['input'] is None else {}
        pending_sheet = state['sheet'] if state['input'] is None else None
        if state['input'] is not None:
            state['plot_x'] = action.get('plot_x', 'auto')
        state.update(input=str(path), sheet=pending_sheet, columns=[None, None], pending_columns=pending,
                     confirmed=False, confirmation_key=None)
    state['pending_columns'].update(deepcopy(action.get('columns', {})))
    is_excel = path.suffix.lower() in dr.EXCEL_SUFFIXES
    if is_excel:
        sheets = dr.list_sheets(path)
        selected_sheet = action.get('sheet', state['sheet'])
        if selected_sheet is None:
            catalog = nav.page_options(sheets, page=view.get('page', 1), search=view.get('search'))
            if any(state['columns']):
                state['plot_x'] = action.get('plot_x', 'auto')
            state.update(sheet=None, columns=[None, None], confirmed=False, confirmation_key=None)
            return finish('needs_sheet')
        try:
            actual = nav.resolve_option(sheets, name=selected_sheet.get('name'), index=selected_sheet.get('index'),
                                        label='工作表', step='needs_sheet')
        except dr.UserError as exc:
            catalog = nav.page_options(sheets)
            if any(state['columns']):
                state['plot_x'] = action.get('plot_x', 'auto')
            state.update(sheet=None, columns=[None, None], confirmed=False, confirmation_key=None)
            return finish('needs_sheet', str(exc))
        identity = {'name': actual['name'], 'index': actual['index']}
        if state['sheet'] is not None and {'name', 'index'} <= state['sheet'].keys() and state['sheet'] != identity:
            state['columns'] = [None, None]
            state['plot_x'] = action.get('plot_x', 'auto')
            state['pending_columns'] = deepcopy(action.get('columns', {}))
            state['confirmed'] = False
        state['sheet'] = identity
    elif action.get('sheet') is not None:
        return finish('needs_sheet', 'CSV/TSV 文件没有工作表，请移除 sheet 选择。')

    frame, _ = dr.load_table(path, sheet_index=state['sheet']['index'] if state['sheet'] else None)
    frame, warnings = dr.normalize_frame(frame)
    if is_excel and actual['state'] != 'visible':
        warnings.append('当前明确选择了隐藏工作表。')
    columns = dr.prepare_columns(frame)
    options = [nav.column_option(column.profile()) for column in columns]
    catalog, preview = dr.column_view(frame, columns, **view)
    stat = path.stat()
    context_key = hashlib.sha256(json.dumps(
        [str(path), state['sheet'], stat.st_size, stat.st_mtime_ns],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def needs_columns(error=None):
        nonlocal catalog, preview, field_items
        remaining = [column for column in state['columns'] if column is not None]
        excluded = remaining[0]['index'] if len(remaining) == 1 else None
        catalog, preview = dr.column_view(frame, columns, **view, exclude_index=excluded)
        candidates = {option['index']: option for option in options}
        for bound in remaining:
            if bound['type'] == 'auto' or bound['index'] not in candidates:
                continue
            try:
                typed = dr.prepare_frame_column(frame, bound['index'] - 1,
                                                kind=bound['type'], order=bound['order'])
                candidates[bound['index']] = nav.column_option(typed.profile())
            except dr.UserError as exc:
                candidates[bound['index']] = {**candidates[bound['index']], 'selectable': False, 'reason': str(exc)}
        field_items = field_widget.field_items(list(candidates.values()), search=view.get('search'))
        return finish('needs_columns', error)

    if 'context_key' in action and action['context_key'] != context_key:
        state.update(pending_pair=None, pending_columns={}, columns=[None, None],
                     confirmed=False, confirmation_key=None)
        return needs_columns('源文件或工作表已变化，请在更新后的完整字段列表中重新选择。')

    pair = state['pending_pair']
    if pair is not None:
        state['pending_pair'] = None
        try:
            resolved = {axis: nav.resolve_column(options, name=selector.get('name'),
                        index=selector.get('index'), label=f'{axis.upper()} 轴字段')
                        for axis, selector in pair.items()}
        except dr.UserError as exc:
            return needs_columns(str(exc))
        x, y = resolved['x']['index'], resolved['y']['index']
        if x == y:
            return needs_columns('X 轴与 Y 轴不能使用同一字段。')
        current = {col['index']: col for col in state['columns'] if col is not None}
        indices = [col['index'] for col in state['columns'] if col is not None]
        if set(indices) != {x, y}:
            indices = sorted((x, y))
        patches = {}
        for axis, index in (('x', x), ('y', y)):
            old = current.get(index, {})
            selector = pair[axis]
            patch = {'index': index, 'type': selector.get('type', old.get('type', 'auto'))}
            order = selector.get('order', old.get('order'))
            if order is not None:
                patch['order'] = order
            patches[str(indices.index(index)+1)] = patch
        state['pending_columns'] = patches
        action = {**action, 'plot_x': f'col{indices.index(x)+1}'}
        state['plot_x'] = action['plot_x']

    column_error = None
    changed_slots = list(state['pending_columns'])
    for slot, patch in state['pending_columns'].items():
        index = int(slot) - 1
        current = state['columns'][index]
        if patch is None:
            state['plot_x'] = action.get('plot_x', 'auto')
            state['columns'][index] = None
            continue
        try:
            chosen = nav.resolve_column(options, name=patch.get('name'),
                                        index=patch.get('index') if 'name' in patch or 'index' in patch else (current['index'] if current else None),
                                        label=f'第 {slot} 列')
        except dr.UserError as exc:
            state['plot_x'] = action.get('plot_x', 'auto')
            state['columns'][index] = None
            column_error = str(exc)
            continue
        same = current is not None and current['index'] == chosen['index']
        if current is not None and not same:
            state['plot_x'] = action.get('plot_x', 'auto')
        state['columns'][index] = {'index': chosen['index'], 'original_name': chosen['original_name'],
                                  'display_name': chosen['display_name'],
                                  'type': patch.get('type', current['type'] if same else 'auto'),
                                  'order': patch.get('order', current['order'] if same else None)}
    state['pending_columns'] = {}
    for index, bound in enumerate(state['columns']):
        if bound is not None and (bound['index'] > len(columns) or
                                  options[bound['index'] - 1]['original_name'] != bound['original_name']):
            state['columns'][index] = None
            state['plot_x'] = action.get('plot_x', 'auto')
            column_error = '原字段已变化，请重新选择该字段。'
    if all(state['columns']) and state['columns'][0]['index'] == state['columns'][1]['index']:
        last_slot = int(changed_slots[-1]) - 1 if changed_slots else 1
        state['columns'][last_slot] = None
        state['plot_x'] = action.get('plot_x', 'auto')
        column_error = '两列不能相同，请只重选冲突的字段。'
    if any(column is None for column in state['columns']):
        return needs_columns(column_error)

    prepared = []
    for slot, bound in enumerate(state['columns'], start=1):
        option = options[bound['index'] - 1]
        semantic_context = {'slot': slot, 'column': option,
                            'observed_levels': list(pd.unique(frame.iloc[:, bound['index'] - 1].dropna()))}
        if bound['type'] == 'auto' and (option['effective_kind'] == 'id' or option['suggested_kind'] == 'ordinal'):
            return finish('needs_semantics', detail=f'字段 #{bound["index"]} {bound["display_name"]}：{option["semantic_hint"]}')
        if bound['type'] == 'ordinal' and bound['order'] is None:
            return finish('needs_semantics', detail=f'第 {slot} 列已选择有序分类，请按业务含义给出全部观察水平的顺序。')
        try:
            column = dr.prepare_frame_column(frame, bound['index'] - 1, kind=bound['type'], order=bound['order'])
        except dr.UserError as exc:
            return finish('needs_semantics', str(exc), detail=f'第 {slot} 列：{exc}')
        if not nav.column_option(column.profile())['selectable']:
            state['columns'][slot - 1] = None
            state['plot_x'] = action.get('plot_x', 'auto')
            return needs_columns(nav.column_option(column.profile())['reason'])
        prepared.append(column)
    semantic_context = None
    try:
        cleaning = dr.prepare_pair(frame, *prepared)
    except dr.UserError as exc:
        return needs_columns(str(exc))
    try:
        plan = dr.multi.build_method_plan(*prepared, methods=state['methods'])
    except dr.multi.MethodRequestError as exc:
        return finish('needs_semantics', str(exc))
    summary = {'input_path': str(path), 'sheet': state['sheet'], 'columns': [column.profile() for column in prepared],
               'n': cleaning['n'], 'cleaning': cleaning, 'method_plan': plan,
               'plot': plotting.resolve_plan([column.profile() for column in prepared], state['plot_x']),
               'warnings': warnings + [warning for column in prepared for warning in column.warnings],
               'note': '这是按类型和共同样本形成的候选计划；实际适用状态由分析时逐项计算。'}
    binding = {'input': state['input'], 'sheet': state['sheet'], 'columns': state['columns'],
               'methods': state['methods'], 'size': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns,
               'n': cleaning['n'], 'plot_x': state['plot_x'], 'plot': summary['plot']}
    key = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if state['confirmation_key'] != key:
        state['confirmed'] = False
    explicit = (action.get('explicit', False) and 'input' in action
                and all(action.get('columns', {}).get(slot) and {'name', 'index'} & action['columns'][slot].keys() for slot in ('1', '2'))
                and (not is_excel or action.get('sheet') is not None))
    if explicit or 'pair' in action or (action.get('confirm', False) and prior_key == key):
        state['confirmed'] = True
    state['confirmation_key'] = key
    if not state['confirmed']:
        return finish('needs_confirmation')
    argv = ['analyze', '--input', str(path)]
    if state['sheet']:
        argv += ['--sheet-index', str(state['sheet']['index'])]
    for slot, bound in enumerate(state['columns'], start=1):
        argv += [f'--col{slot}-index', str(bound['index']), f'--col{slot}-type', bound['type']]
        if bound['order'] is not None:
            argv += [f'--col{slot}-order', json.dumps(bound['order'], ensure_ascii=False)]
    argv += ['--methods', state['methods'], '--plot-x', state['plot_x']]
    return finish('ready', analysis_args=argv)
