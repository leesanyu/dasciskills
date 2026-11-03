"""Request-wide Holm adjustment and traceable explanations; no extra tests run."""

from __future__ import annotations

from itertools import combinations


QUESTIONS = {
    'welch_anova': '多组均值',
    'fisher_exact': '类别分布与独立性',
    'g_test': '类别分布与独立性',
}
SIGNED_EFFECTS = {'pearson_r', 'spearman_rho', 'kendall_tau_b',
                  'point_biserial_r', 'cohen_d', 'rank_biserial', 'phi'}


def apply_holm(tests: list[dict], alpha: float) -> dict:
    """Adjust all valid leaf p-values, preserving input order and raw values."""
    valid = [test for test in tests if test['p_value'] is not None]
    m, previous = len(valid), 0.0
    for i, test in enumerate(sorted(valid, key=lambda test: test['p_value'])):
        previous = min(1.0, max(previous, (m - i) * test['p_value']))
        test.update(p_adjusted=previous, reject_adjusted=bool(previous < alpha), family_id='request')
    excluded = [test for test in tests if test['p_value'] is None]
    for test in excluded:
        test.update(p_adjusted=None, reject_adjusted=None, family_id=None)
    return {'family_id': 'request', 'test_ids': [test['id'] for test in valid],
            'm': m, 'adjustment': 'holm', 'alpha': alpha, 'scope': 'request',
            'excluded_test_ids': [test['id'] for test in excluded]}


def _question(method: dict) -> str:
    return QUESTIONS.get(method['id'], method['question'])


def _limitations(mids: set[str], effects: list[dict]) -> list[str]:
    notes = ['观测需相互独立；Holm 控制本请求检验族的家族错误率，不能修复单项检验假设或时间依赖。',
             '证据不足不能证明独立、相同或无关系；观察性关联不能证明因果。']
    if mids & {'pearson', 'spearman', 'kendall_tau_b', 'point_biserial'}:
        notes.append('线性或秩相关系数接近零仍不能排除 U 形等非单调依赖。')
    if mids & {'mann_whitney', 'kruskal_wallis'}:
        notes.append('U/KW 针对秩分布；只有分布形状等附加条件满足时才能解释为位置或中位数差异。')
    if mids & {'welch_t', 'anova', 'welch_anova'}:
        notes.append('均值推断依赖相应样本与方差条件，不能推及整个分布；ANOVA 启用规则不证明正态性。')
    if 'datetime_features' in mids:
        notes.append('日历模式是探索性筛选，每项只回答该特征的问题；容器没有整体 p，不能替代整体独立性结论。')
    if any(effect['interval'] is not None for effect in effects):
        notes.append('效应区间为未随 Holm 校正的单项区间，不提供全部方法的同时覆盖保证。')
    if len(mids) > 1:
        notes.append('多个相关或等价检验不构成独立重复验证，不能按多数显著或最小原始 p 决策。')
    return notes


def _status(methods: list[dict], tests: list[dict]) -> str:
    decisions = [test['reject_adjusted'] for test in tests if test['p_adjusted'] is not None]
    if not decisions:
        return 'not_applicable' if all(method['status'] == 'not_applicable' for method in methods) else 'descriptive_only'
    if all(decisions):
        return 'evidence'
    return 'mixed_evidence' if any(decisions) else 'insufficient_evidence'


def _test_summary(test: dict, alpha: float) -> str:
    if test['p_adjusted'] is None:
        return f"{test['id']}：仅描述，p 不可用（{test['reason']}）"
    decision = '有证据拒绝该原假设' if test['reject_adjusted'] else '针对该原假设证据不足'
    return (f"{test['id']}：Holm p={test['p_adjusted']}，α={alpha:g}，{decision}"
            f"（原假设：{test['null_hypothesis']}）")


def _basis(a: str, b: str) -> tuple[str, str] | None:
    pair = {a, b}
    if pair <= {'pearson', 'spearman', 'kendall_tau_b'}:
        if 'pearson' in pair:
            return ('线性相关与单调秩关联，使用同一完整配对样本',
                    '线性/单调定义、离群值、并列秩或有限样本等可能影响结果；不能据此确定差异原因。')
        return ('平均秩相关与一致/不一致对的单调关联，使用同一完整配对样本',
                'Spearman 与 Kendall 的系数定义及并列秩处理不同，数值不能直接作强度排名。')
    if 'mann_whitney' in pair and pair & {'spearman', 'kendall_tau_b'}:
        return ('同一二分类分组与显式等级上的 U 秩分布和单调秩关联',
                'U 与秩相关可能等价或高度相关，假设及校准仍分别记录；有符号效应按同一 0/1 与等级方向解释，不能视作独立重复验证。')
    if pair <= {'point_biserial', 'welch_t', 'mann_whitney'}:
        if 'mann_whitney' in pair:
            return ('二分类数量关联/两组均值与两组秩分布，保留同一编码及样本',
                    '均值/秩分布回答的问题和假设不同，分布形状、离群值或并列秩可能影响差异；不能据此确定原因。U 不无条件检验中位数。')
        return ('0/1 编码的线性相关与两组均值，保留同一编码及样本',
                '点二列参数检验与 Welch 的方差假设不同，不能当作独立验证或按较小 p 选择结论。')
    if pair <= {'anova', 'welch_anova', 'kruskal_wallis'}:
        if 'kruskal_wallis' in pair:
            return ('多组均值与多组秩分布，使用相同全部分组',
                    '均值/秩分布回答的问题和假设不同，组内形状、离群值或并列秩可能影响差异；不能据此确定原因。KW 不无条件检验中位数。')
        return ('相同多组均值问题下的经典 ANOVA 与 Welch ANOVA',
                '经典 ANOVA 与 Welch 的方差假设及权重不同，异方差可能影响结果；不能据此确定差异原因。')
    if pair <= {'chi_square', 'fisher_exact', 'g_test'}:
        return ('相同类别独立性问题下的不同统计量与校准方式',
                'χ²/G/Fisher 的统计量、条件化与精确/渐近/置换校准不同，有限样本和模拟误差可能影响差异；不能据此确定机制。')
    if pair == {'kruskal_wallis', 'chi_square'}:
        return ('有序等级的多组秩分布与忽略顺序的类别独立性，使用同一完整配对样本',
                'KW 使用等级顺序，卡方忽略顺序关注类别分布；问题和假设不同，不能用较小 p 选择整体结论或确定差异原因。')
    if 'datetime_features' in pair and pair & {'mann_whitney', 'kruskal_wallis'}:
        return ('时间戳位置的秩分布与日历特征模式，使用同一完整配对样本',
                '时间先后位置与日历周期回答不同问题，各叶子分别解释，不把日历最小 p 当作整体独立性检验。')
    return None


def _directions(methods: list[dict], effects: list[dict]) -> list[dict]:
    directions = []
    for method in methods:
        effect = next((effect for effect in effects if effect['method_id'] == method['id']
                       and effect['name'] in SIGNED_EFFECTS and effect['value'] is not None), None)
        if effect is not None:
            value = effect['value']
            directions.append({'method_id': method['id'], 'effect_id': effect['id'], 'value': value,
                               'sign': 'positive' if value > 0 else 'negative' if value < 0 else 'zero',
                               'definition': effect['definition'], 'direction': effect['direction']})
    return directions


def summarize(methods: list[dict], tests: list[dict], effects: list[dict], *,
              alpha: float) -> tuple[list[dict], list[dict]]:
    """Describe each question and relevant method pair without selecting a winner."""
    groups: dict[str, list[dict]] = {}
    for method in methods:
        groups.setdefault(_question(method), []).append(method)
    conclusions = []
    for i, (question, members) in enumerate(groups.items()):
        mids = {method['id'] for method in members}
        leaves = [test for test in tests if test['method_id'] in mids]
        related_effects = [effect for effect in effects if effect['method_id'] in mids]
        statements = [_test_summary(test, alpha) for test in leaves]
        statements += [f"{method['id']}：{method['reason']}" for method in members if not method['test_ids']]
        conclusions.append({'id': f'question.{i + 1}', 'question': question,
                            'method_ids': [method['id'] for method in members],
                            'test_ids': [test['id'] for test in leaves],
                            'effect_ids': [effect['id'] for effect in related_effects],
                            'status': _status(members, leaves), 'summary': question + '：' + '；'.join(statements) + '。',
                            'limitations': _limitations(mids, related_effects)})
    comparisons = []
    for a, b in combinations(methods, 2):
        basis = _basis(a['id'], b['id'])
        if basis is None:
            continue
        leaves = [test for test in tests if test['method_id'] in {a['id'], b['id']}]
        by_method = [[test for test in leaves if test['method_id'] == method['id']] for method in (a, b)]
        if any(not subset or any(test['p_adjusted'] is None for test in subset) for subset in by_method):
            relation = 'incomplete'
        elif all(len(subset) == 1 for subset in by_method):
            relation = 'same' if by_method[0][0]['reject_adjusted'] == by_method[1][0]['reject_adjusted'] else 'different'
        else:
            relation = 'not_comparable'
        directions = _directions([a, b], effects)
        if len(directions) < 2:
            agreement = 'not_comparable'
        elif any(direction['sign'] == 'zero' for direction in directions):
            agreement = 'zero_involved'
        else:
            agreement = 'same' if directions[0]['sign'] == directions[1]['sign'] else 'opposite'
        relation_text = {'same': '两项校正后的拒绝决定相同', 'different': '两项校正后的拒绝决定不同',
                         'incomplete': '至少一项推断不可用，证据对照不完整',
                         'not_comparable': '含多个日历叶子，逐项查看校正证据，不合成方法级显著性'}[relation]
        comparisons.append({'id': f"{a['id']}__{b['id']}", 'method_ids': [a['id'], b['id']],
                            'test_ids': [test['id'] for test in leaves], 'basis': basis[0],
                            'directions': directions, 'direction_agreement': agreement, 'evidence_relation': relation,
                            'explanation': relation_text + '。' + basis[1] + '多个相关检验不构成独立重复验证；不能按多数显著或最小原始 p 决策。'})
    return conclusions, comparisons
