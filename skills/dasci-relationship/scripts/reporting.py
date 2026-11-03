"""One report model, fixed presentation order, no statistical computation."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import base64
import html
from pathlib import Path
import re
from string import Template

import theme
import plots
import plotting
from uuid import uuid4

import numpy as np

TEMPLATE = theme.TEMPLATE
ASSETS = theme.ASSETS
SECTION_IDS = ['summary', 'figures', 'comparison', 'differences', 'source', 'plan', 'methods', 'limitations', 'attachments']
SECTION_TITLES = ['先看结论', '从图上看', '换几个角度看结果', '方法差异怎么看', '数据从哪里来', '为什么用这些方法', '统计详情', '阅读时请留意', '附件与复查']
COLLAPSED_SECTIONS = {'source', 'plan', 'methods', 'attachments'}
STATUS = {'ok': '已计算', 'descriptive_only': '仅描述', 'not_applicable': '不适用',
          'available': '图像可用', 'disabled': '未生成图像', 'unavailable': '图不可用'}
FINDING_STATUS = {'evidence': '发现关联或差异', 'insufficient_evidence': '证据还不充分',
                  'mixed_evidence': '各项结果不同', 'descriptive_only': '仅能描述现象', 'not_applicable': '暂时无法判断'}
METHOD_NAMES = {'pearson': '皮尔森相关分析', 'spearman': '斯皮尔曼等级相关分析', 'kendall_tau_b': '肯德尔等级相关分析',
                'point_biserial': '点二列相关分析', 'welch_t': '韦尔奇 t 检验', 'mann_whitney': '曼–惠特尼 U 检验',
                'anova': '单因素方差分析', 'welch_anova': '韦尔奇方差分析',
                'kruskal_wallis': '克鲁斯卡尔–沃利斯检验', 'chi_square': '卡方独立性检验',
                'fisher_exact': '费舍尔精确检验', 'g_test': '似然比 G 检验', 'datetime_features': '日历特征筛选'}
METHOD_TERMS = {'pearson': 'Pearson correlation', 'spearman': 'Spearman rank correlation',
                'kendall_tau_b': 'Kendall tau-b', 'point_biserial': 'point-biserial correlation',
                'welch_t': 'Welch t-test', 'mann_whitney': 'Mann–Whitney U test',
                'anova': 'ANOVA', 'welch_anova': 'Welch ANOVA', 'kruskal_wallis': 'Kruskal–Wallis test',
                'chi_square': 'chi-square test', 'fisher_exact': 'Fisher exact test',
                'g_test': 'likelihood-ratio G test', 'datetime_features': 'calendar feature screening'}
QUESTIONS = {'线性关联': '直线关系', '单调关联': '总体增减趋势',
             '二分类与数量的线性关联': '类别与数值的关系', '两组均值': '两组平均值',
             '多组均值': '多组平均值', '异方差多组均值': '多组平均值',
             '两组秩分布': '两组整体分布', '多组秩分布': '多组整体分布',
             '类别分布与独立性': '类别搭配', '二分类独立性': '类别搭配', '日历模式': '日期与类别的关系'}
FEATURE_NAMES = {'year': '年份', 'month': '月份', 'day': '月内日期', 'weekday': '星期', 'hour': '小时', 'minute': '分钟'}
EFFECT_NAMES = {'pearson_r': '直线相关系数', 'spearman_rho': '排序相关系数', 'kendall_tau_b': '排序一致程度',
                'point_biserial_r': '类别与数值的相关系数', 'cohen_d': '标准化均值差', 'rank_biserial': '两组排序差异',
                'eta_squared': '组间差异占比 η²', 'omega_squared': '组间差异估计 ω²',
                'epsilon_squared': '排序差异 ε²', 'cramers_v': '类别关联程度 V', 'phi': '二分类关联系数',
                'odds_ratio': '优势比', 'mutual_information': '类别共享信息量（nat，仅描述）'}


def _method_name(mid, *, first=False):
    return METHOD_NAMES[mid]+('（'+METHOD_TERMS[mid]+'）' if first else '')


def _finding_text(conclusion):
    """Translate existing decisions, without creating a new inference."""
    positive = {'线性关联': '两列存在直线形式的关联。', '单调关联': '两列存在总体增减趋势。',
                '二分类与数量的线性关联': '类别与数值存在关联。', '两组均值': '两组平均值有差异。',
                '多组均值': '至少两组平均值有差异，具体分组还需比较。',
                '两组秩分布': '两组整体分布有差异，不等于中位数一定不同。',
                '多组秩分布': '至少两组整体分布有差异，不等于中位数一定不同。',
                '类别分布与独立性': '两列的类别搭配存在关联。',
                '日历模式': '各项可判断的日历特征都发现了差异，需逐项解读。'}
    return {'evidence': positive[conclusion['question']],
            'insufficient_evidence': '证据不足，暂不能确认存在关联或差异；也不能据此认定无关。',
            'mixed_evidence': '各项结果不一致，需要分别解读。',
            'descriptive_only': '只能描述这批样本，暂不能作统计判断。',
            'not_applicable': '数据不满足使用条件，暂时无法判断。'}[conclusion['status']]


def _method_reading(method, tests):
    if not tests:
        return STATUS[method['status']] + '：' + method['reason']
    def decision(test):
        if test['p_adjusted'] is None:
            return '只能描述：' + test['reason']
        return '发现关联或差异' if test['reject_adjusted'] else '证据还不充分'
    return '；'.join((FEATURE_NAMES[t['feature']] + '：' if t['feature'] else '') + decision(t) for t in tests)


def _effect_reading(effects):
    available = [e for e in effects if e['value'] is not None]
    if not available:
        return '暂无可用指标；原因见统计详情'
    parts=[]
    for effect in available:
        value=effect['value']
        part=(FEATURE_NAMES[effect['feature']]+'：' if effect['feature'] else '')
        part+=EFFECT_NAMES[effect['name']]+' ≈ '+format_value(value)
        if effect['name'] in {'pearson_r','spearman_rho','kendall_tau_b','point_biserial_r'}:
            part+='（样本中同向变化）' if value>0 else '（样本中反向变化）' if value<0 else '（系数为零）'
        elif effect['direction']:
            part+='（'+effect['direction']+'）'
        parts.append(part)
    return '；'.join(parts)


def _direction_reading(conclusion, effects):
    if conclusion['status']!='evidence':
        return ''
    signed=[e['value'] for e in effects if e['id'] in conclusion['effect_ids'] and e['value'] is not None
            and e['name'] in {'pearson_r','spearman_rho','kendall_tau_b'}]
    if not signed:
        return ''
    if all(value>0 for value in signed):
        return '一项越大，另一项也倾向越大。'
    if all(value<0 for value in signed):
        return '一项越大，另一项倾向越小。'
    return '记录的方向不一致，需要分别查看。'


def _comparison_reading(comparison):
    relation = {'same': '统计判断一致。', 'different': '统计判断不同，分别解读。',
                'incomplete': '部分结果不可用，暂不能完整比较。',
                'not_comparable': '日历特征逐项判断，不合并成总结果。'}[comparison['evidence_relation']]
    direction = {'same': '样本方向一致。', 'opposite': '样本方向相反。',
                 'zero_involved': '至少一个方向指标为零。',
                 'not_comparable': ''}[comparison['direction_agreement']]
    pair = set(comparison['method_ids'])
    if pair <= {'pearson', 'spearman', 'kendall_tau_b'}:
        if 'pearson' in pair:
            explanation = '直线关系与增减趋势关注点不同，不能相互替代。'
        else:
            explanation = '都看增减趋势，但算法不同，系数不能直接比大小。'
    elif pair <= {'chi_square', 'fisher_exact', 'g_test'}:
        explanation = '都看类别搭配，但计算方式和使用条件不同。'
    elif 'datetime_features' in pair:
        explanation = '时间偏早偏晚与月份、星期等规律是不同问题。'
    else:
        explanation = '平均值、整体分布和类别搭配关注不同问题。'
    return relation + direction + explanation


def format_value(value):
    if value is None:
        return '—'
    if isinstance(value, (bool, np.bool_)):
        return '是' if value else '否'
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            raise ValueError('报告数值必须有限，缺失值使用 None。')
        magnitude=abs(value)
        if magnitude and (magnitude<1e-6 or magnitude>=1e9):
            return format(value,'.4e')
        return format(0.0 if value==0 else value,'.6f' if 0<magnitude<1e-4 else '.4f')
    if isinstance(value, (dict, list, tuple)):
        return json_text(value)
    return str(value)


def json_text(value, *, pretty=False, depth=0):
    """Display JSON with bounded precision while keeping numbers as numbers."""
    if isinstance(value,(dict,list,tuple)):
        opening,closing=('{','}') if isinstance(value,dict) else ('[',']')
        items=value.items() if isinstance(value,dict) else enumerate(value)
        parts=[]
        for key,item in items:
            prefix=json.dumps(str(key),ensure_ascii=False)+': ' if isinstance(value,dict) else ''
            parts.append(('  '*(depth+1) if pretty else '')+prefix+json_text(item,pretty=pretty,depth=depth+1))
        if not parts:return opening+closing
        return opening+('\n' if pretty else '')+(',\n' if pretty else ', ').join(parts)+('\n'+'  '*depth if pretty else '')+closing
    if isinstance(value,(float,np.floating)):return format_value(value)
    if isinstance(value,np.generic):value=value.item()
    return json.dumps(value,ensure_ascii=False,default=str,allow_nan=False)


def _note_text(value):
    return value.replace('家族错误率','整体误报风险')


def _column_samples(column):
    if column['effective_kind']!='numeric':return column['sample']
    return [float(v) if isinstance(v,str) and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',v) else v
            for v in column['sample']]


def _calendar_labels(days, feature):
    dates = [datetime(1970,1,1)+timedelta(days=float(value)) for value in days]
    return [str(value) for value in sorted({date.weekday() if feature=='weekday' else getattr(date,feature) for date in dates})]


def _figure_specs(result, chart):
    """Adapt existing paired plot data, preserving ordinal labels and order."""
    columns = [result['col1'], result['col2']]
    plan = result['plot']
    ordinal = [i for i,c in enumerate(columns) if c['effective_kind'] == 'ordinal']
    spec = deepcopy(chart)
    current_x = (0 if spec['kind'] == 'scatter' else 1 if spec['kind'] == 'heatmap' else
                 next(i for i,c in enumerate(columns) if c['effective_kind'] not in {'boolean','categorical'}))
    order_note = ''
    if ordinal:
        order_note = '等级按用户确认顺序显示；编码仅表示顺序，不假定数量间距。'
        if spec['kind'] == 'scatter':
            axes = [np.asarray(spec['x']), np.asarray(spec['y'])]
            if len(ordinal) == 2:
                labels = [[str(level['value']) for level in c['levels']] for c in columns]
                table = np.zeros((len(labels[0]),len(labels[1])),dtype=int)
                for x,y in zip(*axes):
                    table[int(x),int(y)] += 1
                spec = {'kind':'heatmap', 'table':table.tolist(), 'row_labels':labels[0], 'col_labels':labels[1]}
                current_x = 1
            else:
                oi = ordinal[0]; mi = 1-oi
                current_x = mi
                labels = [str(level['value']) for level in columns[oi]['levels']]
                if columns[mi]['effective_kind'] == 'datetime':
                    spec = {'kind':'timeline', 'dates':axes[mi].tolist(), 'categories':[labels[int(v)] for v in axes[oi]],
                            'category_order':labels, 'x_label':columns[mi]['name'], 'y_label':columns[oi]['name']}
                else:
                    spec = {'kind':'box', 'groups':[axes[mi][axes[oi]==i].tolist() for i in range(len(labels))],
                            'labels':labels, 'x_label':columns[mi]['name']}
        elif spec['kind'] == 'box':
            oi = ordinal[0]
            current_x = 1-oi
            labels = [str(level['value']) for level in columns[oi]['levels']]
            spec = {'kind':'heatmap', 'row_labels':labels, 'col_labels':spec['labels'],
                    'table':[[sum(int(v)==i for v in group) for group in spec['groups']] for i in range(len(labels))]}
    assert spec['kind'] == plan['kind'], 'plot plan and paired presentation disagree'
    requested_x = int(plan['x']['slot'][-1])-1
    if spec['kind'] == 'scatter' and requested_x != current_x:
        spec['x'], spec['y'] = spec['y'], spec['x']
        spec['x_date'], spec['y_date'] = spec.get('y_date', False), spec.get('x_date', False)
    elif spec['kind'] == 'heatmap' and requested_x != current_x:
        spec['table'] = np.asarray(spec['table']).T.tolist()
        spec['row_labels'], spec['col_labels'] = spec['col_labels'], spec['row_labels']
    elif spec['kind'] == 'box':
        spec['orientation'] = 'horizontal' if requested_x == current_x else 'vertical'
    elif spec['kind'] == 'timeline':
        spec['time_axis'] = 'x' if requested_x == current_x else 'y'
    axes = {key: deepcopy(plan[key]) for key in ('x','y')}
    spec.update(x_label=axes['x']['label'], y_label=axes['y']['label'])
    specs = [('relationship', spec, [m['id'] for m in result['methods']], order_note, axes)]
    calendar = next((m for m in result['methods'] if m['id']=='datetime_features'), None)
    if calendar:
        specs[0] = ('time-position', spec, [m['id'] for m in result['methods'] if m['id']!='datetime_features'], order_note, axes)
        group = next(c for c in columns if c['effective_kind'] in {'boolean','categorical'})
        labels = [str(level['value']) for level in group['levels']]
        group_slot = columns.index(group)
        date_slot = 1-group_slot
        for feature, detail in calendar['details']['tables'].items():
            # Leaf tables already come from AnalysisResult; no tests or effects are recomputed.
            table = detail['table']
            a = np.asarray(table)
            calendar_axes = {'x': plotting.axis(group, group_slot),
                             'y': plotting.axis(columns[date_slot], date_slot, feature,
                                                columns[date_slot]['display_name']+'（'+FEATURE_NAMES[feature]+'）')}
            specs.append((f'calendar-{feature}', {'kind':'heatmap','table':a.tolist(),
                          'row_labels':_calendar_labels(chart['dates'], feature),
                          'col_labels':labels[:a.shape[1]], 'x_label':calendar_axes['x']['label'],
                          'y_label':calendar_axes['y']['label']}, ['datetime_features'],
                          f'按{FEATURE_NAMES[feature]}分组；各项检验与完整次数见统计详情。', calendar_axes))
    figures = []
    for fid, spec, mids, note, axes in specs:
        kind = spec['kind']
        scope = {'scatter':f'每个点代表一行记录，图中最多显示 {min(5000,result["n"]):,} 个点。',
                 'box':f'显示至多 15 组，每组至多 40 个离群点；保留原分组顺序。',
                 'heatmap':'显示前 14 × 14 个类别，完整次数见统计详情或 CSV 附件。',
                 'timeline':'显示至多 12 个类别；时间轴为实际日期。'}[kind]
        title = {'scatter':'配对散点图','box':'分组分布图','heatmap':'类别频数热图','timeline':'时间与类别分布'}[kind]
        questions = list(dict.fromkeys(QUESTIONS[m['question']] for m in result['methods'] if m['id'] in mids))
        mapping = ''
        if kind == 'heatmap':
            mapping = '颜色表示记录数。热图列标记：' + '；'.join(f'C{i+1}={label}' for i,label in enumerate(spec['col_labels'][:14])) + '。'
        caption = f'{columns[0]["name"]} × {columns[1]["name"]}。横轴：{axes["x"]["label"]}；纵轴：{axes["y"]["label"]}。{scope}统计使用完整配对数据。{note}{mapping} 图形帮助观察分布与趋势，统计判断已考虑同时使用多种检验的影响；关联不代表因果。'
        figures.append({'id':fid, 'method_ids':mids, 'question':' / '.join(questions), 'title':title,
                        'method_names':[_method_name(mid) for mid in mids], 'axes':axes,
                        'caption':caption,'alt':caption, 'asset_path':None, 'status':'unavailable',
                        'reason':'尚未生成图像', 'spec':spec})
    return figures


def build_model(result, chart, extra, *, generated_at=None, report_id=None):
    result = deepcopy(result)
    model = {key: result[key] for key in ('method_plan','methods','tests','effects','multiplicity','conclusions',
                                          'comparisons','assumptions','warnings')}
    model.update(schema_version='1.1', report_id=report_id or uuid4().hex,
                 generated_at=generated_at or datetime.now(timezone.utc).isoformat(), html_template=TEMPLATE.copy(),
                 source={key:result[key] for key in ('input_path','sheet','sheet_index','format','cleaning')},
                 columns=[result['col1'],result['col2']], plot=deepcopy(result['plot']), transformations=result['transformations'],
                 summary={'n':result['n'], 'computed_methods':sum(m['status']!='not_applicable' for m in result['methods']),
                          'm':result['multiplicity']['m'], 'alpha':result['alpha'], 'inference_status':result['inference_status']},
                 tables=[], figures=_figure_specs(result,chart), attachments=[],
                 reproduction={'seed':result['seed'],'permutations_requested':result['permutations_requested'],
                               'plot_x':result['plot']['requested_x'],'plot':deepcopy(result['plot'])})
    model['summary'].update(original_rows=result['cleaning']['original_rows'],
                            excluded_rows=result['cleaning']['original_rows']-result['n'])
    model['sections'] = [{'id':key,'title':title,'collapsed':key in COLLAPSED_SECTIONS,'blocks':[]} for key,title in zip(SECTION_IDS,SECTION_TITLES)]
    sections = {s['id']:s['blocks'] for s in model['sections']}
    def text(section, value):
        sections[section].append({'kind':'text','value':value})
    def heading(section, value):
        sections[section].append({'kind':'heading','value':value})
    def table(section, tid, headers, rows, note=''):
        value={'id':tid,'headers':headers,'rows':rows,'note':note}
        model['tables'].append(value);sections[section].append({'kind':'table','table':value})
    def attach(path, purpose):
        model['attachments'].append({'path':path,'purpose':purpose})
    def structured(section, title, value):
        sections[section].append({'kind':'json','title':title,'value':value})

    family=result['multiplicity']
    text('methods','多次检验的整体误报风险（family-wise error rate，FWER）：同一组检验中，至少一次把本来不存在的关系误判为存在的概率。这里用逐步多重检验校正（Holm adjustment）控制这项风险。')
    text('methods',f'本次共 {family["m"]} 项有效检验，判断门槛为 {format_value(family["alpha"])}。检验编号、原始 p 值（p-value）和校正后 p 值见下表；无可用 p 值的项目不计入校正。')
    text('methods','关系或差异的大小称为效应量（effect size）；估计的不确定范围用置信区间（confidence interval，CI）表示。这里各区间只针对单项估计，不保证多个区间同时覆盖。')
    text('methods','展示数字通常保留 4 位小数，小数值保留 6 位或使用科学计数法。统计决定使用舍入前的原始值；完整精度见 result.json 和 CSV 附件。')

    text('summary', f'本次使用 {result["n"]:,} 行两列都有有效值的数据，从不同角度查看它们的关系。')
    if result['inference_status']=='descriptive_only':
        text('summary','本次仅作描述，不能判断是否存在关联。')
    seen_methods=set()
    for conclusion in result['conclusions']:
        method_names=[_method_name(mid,first=mid not in seen_methods) for mid in conclusion['method_ids']]
        seen_methods.update(conclusion['method_ids'])
        sections['summary'].append({'kind':'finding','title':QUESTIONS[conclusion['question']],
                                    'method_names':method_names,
                                    'status':conclusion['status'],'value':_direction_reading(conclusion,result['effects']) or _finding_text(conclusion)})
        heading('methods',conclusion['question']+'：原始判断与依据')
        text('methods','判断：'+FINDING_STATUS[conclusion['status']]+'。完整数值与判断条件见下方检验记录。')
        text('methods',f'方法：{", ".join(conclusion["method_ids"])}；检验引用：{", ".join(conclusion["test_ids"])}；效应引用：{", ".join(conclusion["effect_ids"])}')
        sections['methods'].append({'kind':'list','items':[_note_text(v) for v in conclusion['limitations']]})
    text('summary', '关联不代表因果；是否有实际意义，还要看关系大小和业务背景。')
    for key,label in [('input_path','文件'),('sheet','工作表'),('sheet_index','工作表编号'),('format','文件格式')]:
        text('source',f'{label}：{format_value(model["source"][key])}')
    table('source','columns',['#','原始列名','显示名','推断类型','有效类型','来源','非空','缺失','唯一值','水平/编码','单位','示例'],
          [[c['index'],c.get('original_name',c['name']),c.get('display_name',c['name']),c['inferred_kind'],c['effective_kind'],
            c['type_source'],c['non_null'],c['missing'],c['unique'],c['levels'],c['unit'],_column_samples(c)] for c in model['columns']],
          '数值示例按报告精度展示；原始值及原始文本保留在源文件和 result.json 中。')
    cleaning=result['cleaning']
    table('source','cleaning',['计数','行数'],[[label,cleaning[key]] for key,label in
          [('original_rows','原始数据行'),('empty_rows','全空行'),('conversion_failure_rows','转换失败配对行'),('missing_pair_rows','其余缺失配对行'),('n','最终配对 N')]])
    text('source','行排除原因互斥；同一行两列转换失败只排除一次。缺失不保证随机。')
    structured('source','各列数据清理记录',cleaning['columns'])
    heading('source','类型转换与编码')
    for transformation in result['transformations']: structured('source','转换记录',transformation)
    table('plan','plan',['分析方法','回答的问题','适用条件'],[[_method_name(i['id']),QUESTIONS[i['question']],i['conditions']] for i in result['method_plan']['items']])
    text('plan',f'请求：{result["method_plan"]["requested"]}；候选计划保留全部方法，实际状态见对照。')
    text('comparison','下面的方法使用同一批有效数据。判断已考虑一次尝试多个检验时更容易碰巧出现结果的影响；不同角度的结果应分别理解。')
    rows=[];reading_rows=[]
    for method in result['methods']:
        tests=[t for t in result['tests'] if t['id'] in method['test_ids']]
        effects=[e for e in result['effects'] if e['id'] in method['effect_ids']]
        reading_rows.append([_method_name(method['id']),QUESTIONS[method['question']],
                             _method_reading(method,tests),_effect_reading(effects)])
        effect_text='；'.join(f'{e["name"]}={format_value(e["value"])}' for e in effects)
        intervals=[{'指标':e['name'],'置信区间':e['interval'],
                    '说明':e['reason'] or ('仅针对这一项估计' if e['interval'] else '未提供该指标的区间')} for e in effects]
        for test in tests or [None]:
            rows.append([_method_name(method['id']),test['id'] if test else method['id'],method['question'],method['n'],
                         test['statistic_name'] if test else None,test['statistic_value'] if test else None,
                         test['df'] if test else None,test['p_value'] if test else None,test['p_adjusted'] if test else None,
                         effect_text,intervals,STATUS[method['status']],method['reason']])
        heading('methods',f'{_method_name(method["id"])} · {method["id"]}')
        text('methods',f'问题：{method["question"]}；N={method["n"]}；状态：{STATUS[method["status"]]}。适用条件：{method["conditions"]}')
        if method['reason']: text('methods',method['reason'])
        test_keys=['id','null_hypothesis','statistic_name','statistic_value','df','p_value','p_adjusted','reject_adjusted','p_method',
                   'alternative','permutations_requested','permutations_used','seed','p_resolution','mc_standard_error','reason']
        test_headers=['检验','原假设','统计量','值','df','原始 p','Holm p','校正后拒绝','p 校准','方向','请求 B','实际 B','种子','分辨率','MC 标准误','说明']
        table('methods',method['id']+'-tests',test_headers,[[t[key] for key in test_keys] for t in tests])
        effect_keys=['id','name','value','definition','direction','interval','reason']
        table('methods',method['id']+'-effects',['效应引用','效应','值','定义','编码方向','置信区间','说明'],[[e[key] for key in effect_keys] for e in effects])
        if method['details']: structured('methods',_method_name(method['id'])+'：计算明细',method['details'])
    table('comparison','reading-overview',['分析方法','想了解什么','这次的结果','关系或差异的大小'],reading_rows)
    text('comparison','数字已适度舍入，完整精度见附件。正负方向按记录编码解释；不同指标不能直接比大小，有证据也不代表关系很强。')
    if any(m['id'] in {'pearson','spearman','kendall_tau_b','point_biserial'} for m in result['methods']):
        text('comparison','相关系数在 −1 到 1 之间：越接近两端，对应角度的关系越明显；越接近 0，这种关系越弱。但接近 0 仍可能存在 U 形等其他关系。')
    table('methods','method-overview',['方法','检验编号','问题','N','统计量','值','df','原始 p','校正后 p','效应量','区间与限制','状态','原因'],rows)
    text('methods','效应量区间是单项区间，不提供同时覆盖保证；r、V、η² 等不同量纲不作强度排名。')
    if any(t['permutations_used'] for t in result['tests']):
        text('methods','置换 p=(极端次数+1)/(B+1)，分辨率为 1/(B+1)。MC 标准误是 sqrt(p*(1-p)/B) 的近似估计，不是置信区间；p=1 的零估计不代表无模拟误差。two_sided 为双侧，greater 为统计量上尾。')
    if 'table' in extra:
        t=extra['table'];nr,nc=t.shape
        table('methods','contingency',['行 / 列']+[str(c) for c in t.columns[:10]],
              [[str(t.index[i])]+t.iloc[i,:10].tolist() for i in range(min(nr,10))],
              f'显示前 {min(nr,10)} × {min(nc,10)}；总范围 {nr} × {nc}。统计使用完整配对数据，完整频数见 contingency.csv。')
        attach('contingency.csv','完整观测频数')
        if 'expected' in extra: attach('expected_counts.csv','完整期望频数')
    if 'group_summary' in extra:
        keys=['group','n','mean','std','median','min','max']
        table('methods','group-summary',keys,[[g[k] for k in keys] for g in extra['group_summary']]);attach('group_summary.csv','完整分组描述统计')
    if result['descriptives'].get('ordinal_frequencies'):
        heading('methods','分组等级频数')
        structured('methods','分组等级频数',result['descriptives']['ordinal_frequencies'])
    if 'features' in extra: attach('datetime_features.csv','日历叶子检验及请求级 Holm 校正明细')
    for comparison in result['comparisons']:
        sections['differences'].append({'kind':'comparison','title':' 与 '.join(_method_name(mid) for mid in comparison['method_ids']),
                                        'status':comparison['evidence_relation'],'value':_comparison_reading(comparison),'details':comparison})
    if not result['comparisons']: text('differences','本次没有需要对照的方法对，按各问题的结果及限制解释。')
    readable_warnings=[w.replace('Holm 不修复单项检验的假设或时间依赖；不能按最小原始 p 或多数显著决策。',
                                 '同时检查多个问题时所作的调整，不能弥补数据不满足方法要求的问题。')
                       .replace('categorical 或 ordinal','分类或有顺序的等级') for w in result['warnings']]
    sections['limitations'].append({'kind':'list','items':[
        '数据中的关联不能证明因果，也可能受其他没有纳入分析的因素影响。',
        '只使用两列都有有效值的行；被排除的数据可能影响结论，不能假定这些缺失是随机的。',
        '每行数据应能视为独立观察。同一对象反复记录或连续时间数据，可能不满足这一条件。',
        '目前证据不足，不等于证明没有关系；相关系数接近零，也可能存在 U 形等关系。',
        '多种方法是从不同角度看同一批数据，不能当成多次独立验证。']+readable_warnings})
    heading('methods','原始假设与数据提醒')
    sections['methods'].append({'kind':'list','items':[_note_text(v) for v in result['assumptions']+result['warnings']]})
    text('attachments','HTML 单文件包含正文与图表；完整 CSV 复查附件需复制整个输出目录。Markdown 需连同相对图像资源保存。')
    text('attachments',f'report_id：{model["report_id"]}；generated_at：{model["generated_at"]}')
    structured('attachments','复现参数',model['reproduction'])
    structured('attachments','完整方法计划',result['method_plan'])
    return model


class ReportError(RuntimeError):
    """A required report asset or output failed; callers must not claim success."""


def md_text(value):
    value = html.escape(str(value), quote=False)
    value = value.replace('\\','\\\\')
    value = re.sub(r'([`*{\}\[\]#|!])',r'\\\1',value)
    value = re.sub(r'(?<!\w)_|_(?!\w)', r'\\_', value)
    return value.replace('\r','').replace('\n','<br>')


def render_figures(model, out_dir, *, disabled=False):
    out_dir=Path(out_dir)
    for figure in model['figures']:
        figure.update(asset_path=None,status='disabled' if disabled else 'unavailable',reason='用户指定 --no-chart' if disabled else None)
        if disabled:
            continue
        spec=figure['spec'];relative=f'charts/{figure["id"]}.png';target=out_dir/relative
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            kind=spec['kind']
            if kind=='scatter':
                path=plots.scatter(spec['x'],spec['y'],spec['x_label'],spec['y_label'],target,figure['title'],
                                   x_date=spec.get('x_date',False),y_date=spec.get('y_date',False))
            elif kind=='box':
                path=plots.boxplot(spec['groups'],spec['labels'],spec['x_label'],target,figure['title'],
                                   y_label=spec['y_label'],orientation=spec['orientation'])
            elif kind=='heatmap':
                path=plots.heatmap(spec['table'],spec['row_labels'],spec['col_labels'],target,figure['title'],
                                   x_label=spec['x_label'],y_label=spec['y_label'])
            elif kind=='timeline':
                path=plots.timeline(spec['dates'],spec['categories'],spec['x_label'],spec['y_label'],target,figure['title'],
                                    category_order=spec.get('category_order'),time_axis=spec['time_axis'])
            else:
                raise AssertionError(f'Unknown figure kind: {kind}')
            if path is None:
                figure['reason']='绘图依赖 Pillow 不可用或没有可绘制数据。'
            else:
                figure.update(status='available',asset_path=relative,reason=None)
        except (ImportError,OSError,plots.ChartUnavailable) as exc:
            figure['reason']=f'图表生成失败：{exc}'


JSON_TOKENS = re.compile(r'(?P<key>"(?:\\.|[^"\\])*"(?=\s*:))|(?P<string>"(?:\\.|[^"\\])*")|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<literal>\b(?:true|false|null)\b)')
LONG_CELL_LENGTH = 80


def _json_html(value):
    source=json_text(value,pretty=True)
    output=[];end=0
    for match in JSON_TOKENS.finditer(source):
        output.append(html.escape(source[end:match.start()]))
        output.append(f'<span class="json-{match.lastgroup}">{html.escape(match.group())}</span>')
        end=match.end()
    output.append(html.escape(source[end:]))
    return '<pre class="json-code"><code>'+''.join(output)+'</code></pre>'


def _json_details(value, title):
    return ('<details class="json-details"><summary><span>'+html.escape(title)
            +'</span><span class="chevron" aria-hidden="true">⌄</span></summary>'
            +_json_html(value)+'</details>')


def _long_cell(value):
    return isinstance(value,(dict,list,tuple)) or len(format_value(value))>LONG_CELL_LENGTH or '\n' in format_value(value)


def _json_md(value):
    source=json_text(value,pretty=True)
    # A string value may contain backticks; choose a fence it cannot close.
    length=max([len(m.group()) for m in re.finditer(r'`+',source)]+[2])+1
    fence='`'*length
    return fence+'json\n'+source+'\n'+fence


def _table_html(table):
    def cell(value,tag,label=None):
        numeric=isinstance(value,(int,float,np.number)) and not isinstance(value,(bool,np.bool_))
        content=html.escape(format_value(value))
        if tag=='td' and _long_cell(value):
            structured=isinstance(value,(dict,list,tuple))
            content=('<details class="cell-details"><summary><span>'
                     +('查看 JSON' if structured else '展开全文')
                     +'</span><span class="chevron" aria-hidden="true">⌄</span></summary>'
                     +'<div class="cell-content"'+(' data-format="json"' if structured else '')+'>'
                     +(_json_html(value) if structured else content)+'</div></details>')
        return (f'<{tag}'+(' class="num"' if numeric else '')
                +(f' data-label="{html.escape(label)}"' if label is not None else '')
                +'>'+content+f'</{tag}>')
    heads=''.join(cell(v,'th') for v in table['headers'])
    rows=''.join('<tr>'+''.join(cell(v,'td',label) for v,label in zip(row,table['headers']))+'</tr>' for row in table['rows'])
    return (f'<div class="table-scroll" tabindex="0" role="region" aria-label="{html.escape(" / ".join(table["headers"]))}">'
            f'<table id="{html.escape(table["id"])}"><thead><tr>{heads}</tr></thead><tbody>{rows}</tbody></table></div>'
            + (f'<p class="note">{html.escape(table["note"])}</p>' if table['note'] else '')
            + ('<p class="empty">此项没有可用记录；见方法状态与原因。</p>' if not table['rows'] else ''))


def _table_md(table):
    rows=[table['headers'],['---']*len(table['headers'])]
    output=['| '+' | '.join(md_text(v) for v in row)+' |' for row in rows];details=[]
    for ri,row in enumerate(table['rows'],1):
        cells=[]
        for ci,value in enumerate(row,1):
            if _long_cell(value):
                cid=f'cell-{table["id"]}-{ri}-{ci}'
                cells.append('[查看详情](#'+cid+')')
                structured=isinstance(value,(dict,list,tuple))
                body=_json_md(value) if structured else md_text(format_value(value))
                details.append(f'<div class="cell-detail" id="{html.escape(cid)}"'+(' data-format="json"' if structured else '')+'>\n\n'
                               +'**'+md_text(table['headers'][ci-1])+f' · 第 {ri} 行**\n\n'+body+'\n\n</div>')
            else:cells.append(md_text(format_value(value)))
        output.append('| '+' | '.join(cells)+' |')
    if table['note']:output.append('\n'+md_text(table['note']))
    output.extend('\n'+detail for detail in details)
    return '\n'.join(output)


def _figure_html(figure,out_dir):
    label=html.escape(STATUS[figure['status']])
    image=''
    if figure['status']=='available':
        path=Path(out_dir)/figure['asset_path']
        with plots.Image.open(path) as png:
            width,height=png.size
        data=base64.b64encode(path.read_bytes()).decode('ascii')
        image=f'<img src="data:image/png;base64,{data}" alt="{html.escape(figure["alt"])}" width="{width}" height="{height}">'
    else:
        image=f'<p class="empty">{html.escape(figure["reason"])}</p>'
    badge=f' <span class="badge">{label}</span>' if figure['status']!='available' else ''
    return (f'<figure id="{html.escape(figure["id"])}"><h3>{html.escape(figure["title"])}{badge}</h3>'
            f'<p class="note">{html.escape(figure["question"])} · {html.escape("、".join(figure["method_names"]))}</p>'
            +image+f'<figcaption>{html.escape(figure["caption"])}</figcaption></figure>')


def _figure_md(figure):
    lines=['### '+md_text(figure['title'])+' · '+STATUS[figure['status']],
           md_text(figure['question'])+' · '+md_text('、'.join(figure['method_names']))]
    if figure['status']=='available':
        lines.append('!['+md_text(figure['alt'])+']('+figure['asset_path']+')')
    else:
        lines.append(md_text(figure['reason']))
    lines.append(md_text(figure['caption']))
    return '\n\n'.join(lines)


CARD_LABELS={'original_rows':'原始数据行','n':'纳入分析的行','excluded_rows':'未纳入的行','computed_methods':'已计算的方法'}


def _reading_date(value):
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def render_html(model,out_dir):
    slots={'title','subtitle','css','nav','body','report_id','generated_at','template_id','template_version'}
    try:
        template=Template((ASSETS/'report.html').read_text(encoding='utf-8'))
        css=theme.css_variables()+'\n'+(ASSETS/'report.css').read_text(encoding='utf-8')
    except OSError as exc:
        raise ReportError(f'report.html 模板资源读取失败：{exc}') from exc
    if not template.is_valid() or set(template.get_identifiers())!=slots:
        raise ReportError('report.html 模板必需槽位缺失或存在未知槽位。')
    assert model['html_template']==TEMPLATE, 'ReportModel template differs from shipped renderer'
    body=[]
    for section in model['sections']:
        blocks=[f'<h2>{html.escape(section["title"])}</h2>']
        if section['collapsed']:
            blocks=[f'<details><summary><h2>{html.escape(section["title"])}</h2><span class="expand-label" aria-hidden="true"></span></summary><div class="detail-body">']
        if section['id']=='figures':
            blocks.extend(_figure_html(f,out_dir) for f in model['figures'])
            if not model['figures']:blocks.append('<p class="empty">本次无可绘制的图形。</p>')
        for block in section['blocks']:
            kind=block['kind']
            if kind=='text': blocks.append('<p>'+html.escape(block['value'])+'</p>')
            elif kind=='heading': blocks.append('<h3>'+html.escape(block['value'])+'</h3>')
            elif kind=='list': blocks.append('<ul>'+''.join('<li>'+html.escape(item)+'</li>' for item in block['items'])+'</ul>')
            elif kind=='table':blocks.append(_table_html(block['table']))
            elif kind=='json':blocks.append(_json_details(block['value'],block['title']))
            elif kind=='comparison':
                label={'same':'判断一致','different':'判断不同','incomplete':'暂无法比较','not_comparable':'分别解读'}[block['status']]
                blocks.append('<article class="comparison-card" data-status="'+html.escape(block['status'])+'">'
                              +'<div class="comparison-heading"><h3>'+html.escape(block['title'])+'</h3><span class="badge">'+label+'</span></div>'
                              +'<p class="comparison-reading">'+html.escape(block['value'])+'</p>'
                              +_json_details(block['details'],'查看比较依据（JSON）')+'</article>')
            elif kind=='finding':
                blocks.append(f'<article class="finding" data-status="{html.escape(block["status"])}">'
                              f'<h3>{html.escape(block["title"])}</h3>'
                              f'<span class="badge">{FINDING_STATUS[block["status"]]}</span>'
                              f'<p>{html.escape(block["value"])}</p>'
                              +'<p class="finding-methods"><strong>分析方法：</strong><br>'
                              +'<br>'.join(html.escape(name) for name in block['method_names'])+'</p></article>')
            else:raise AssertionError(kind)
        if section['id']=='summary':
            blocks.append('<div class="cards">'+''.join(f'<div class="card"><div class="card-label">{label}</div><div class="card-value">{model["summary"][key]:,}</div></div>' for key,label in CARD_LABELS.items())+'</div>')
        if section['id']=='attachments':
            blocks.append('<ul>'+''.join(f'<li><a href="{html.escape(a["path"])}">{html.escape(a["path"])}</a> — {html.escape(a["purpose"])}</li>' for a in model['attachments'])+'</ul>')
        if section['collapsed']:
            blocks.append('</div></details>')
        body.append(f'<section id="{section["id"]}">'+''.join(blocks)+'</section>')
    values={'title':'数据关系分析报告','subtitle':' × '.join(c['name'] for c in model['columns']),
            'report_id':model['report_id'],'generated_at':_reading_date(model['generated_at']),
            'template_id':TEMPLATE['id'],'template_version':TEMPLATE['version']}
    values={key:html.escape(value) for key,value in values.items()}
    values.update(css=css,body=''.join(body),nav=''.join(f'<a href="#{s["id"]}">{html.escape(s["title"])}</a>' for s in model['sections'] if s['id'] in {'summary','figures','comparison','methods','attachments'}))
    return template.substitute(values)


def render_markdown(model):
    lines=['# 数据关系分析报告',' × '.join(md_text(c['name']) for c in model['columns'])]
    for section in model['sections']:
        lines.append('## '+section['title'])
        if section['id']=='figures':
            lines.extend(_figure_md(f) for f in model['figures'])
            if not model['figures']: lines.append('本次无可绘制的图形。')
        for block in section['blocks']:
            kind=block['kind']
            if kind=='text':lines.append(md_text(block['value']))
            elif kind=='heading':lines.append('### '+md_text(block['value']))
            elif kind=='list':lines.append('\n'.join('- '+md_text(item) for item in block['items']))
            elif kind=='table':lines.append(_table_md(block['table']))
            elif kind=='json':lines.extend(['### '+md_text(block['title']),_json_md(block['value'])])
            elif kind=='comparison':
                lines.extend(['### '+md_text(block['title']),md_text(block['value']),
                              '比较依据：',_json_md(block['details'])])
            elif kind=='finding':
                lines.extend(['### '+md_text(block['title']),
                              '**'+FINDING_STATUS[block['status']]+'**',md_text(block['value']),
                              '**分析方法：**\n\n'+'\n'.join('- '+md_text(name) for name in block['method_names'])])
            else:raise AssertionError(kind)
        if section['id']=='summary':
            lines.append('；'.join(f'{label}：{model["summary"][key]:,}' for key,label in CARD_LABELS.items()))
        if section['id']=='attachments':
            lines.extend(f'- [{a["path"]}]({a["path"]}) — {md_text(a["purpose"])}' for a in model['attachments'])
    lines.append(f'数据科学:相关性分析 / {TEMPLATE["version"]}；统计显著不等于因果。')
    return '\n\n'.join(lines)+'\n'


def write_reports(model, extra, out_dir):
    """Write both required formats and the original full CSV review attachments."""
    import pandas as pd

    out_dir=Path(out_dir)
    model['attachments'].append({'path':'result.json','purpose':'完整统计结果、路径与模板版本'})
    contents={'report.html':render_html(model,out_dir),'report.md':render_markdown(model)}
    for filename,text in contents.items():
        try:
            (out_dir/filename).write_text(text,encoding='utf-8')
        except OSError as exc:
            raise ReportError(f'{filename} 写入失败：{exc}') from exc
    csvs={}
    if 'table' in extra:
        csvs['contingency.csv']=(extra['table'],True)
    if 'expected' in extra:
        csvs['expected_counts.csv']=(extra['expected'],True)
    if 'group_summary' in extra:
        csvs['group_summary.csv']=(pd.DataFrame(extra['group_summary']),False)
    if 'features' in extra:
        csvs['datetime_features.csv']=(pd.DataFrame(extra['features']),False)
    for filename,(frame,index) in csvs.items():
        try:
            frame.to_csv(out_dir/filename,index=index,encoding='utf-8-sig')
        except OSError as exc:
            raise ReportError(f'{filename} 写入失败：{exc}') from exc
    return {'report_html_path':str(out_dir/'report.html'),'report_md_path':str(out_dir/'report.md'),
            'chart_paths':list(dict.fromkeys(str(out_dir/f['asset_path']) for f in model['figures'] if f['status']=='available')),
            'result_path':str(out_dir/'result.json'),'out_dir':str(out_dir)}
