"""A fixed multi-method plan over one prepared pair; no I/O or SciPy imports."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

import stats as st
import inference


KINDS = ("numeric", "boolean", "categorical", "ordinal", "datetime")
MATRIX = {
    ("numeric", "numeric"): ("pearson", "spearman", "kendall_tau_b"),
    ("numeric", "boolean"): ("point_biserial", "welch_t", "mann_whitney"),
    ("numeric", "categorical"): ("anova", "welch_anova", "kruskal_wallis"),
    ("numeric", "ordinal"): ("spearman", "kendall_tau_b"),
    ("numeric", "datetime"): ("pearson", "spearman", "kendall_tau_b"),
    ("boolean", "boolean"): ("chi_square", "fisher_exact", "g_test"),
    ("boolean", "categorical"): ("chi_square", "g_test"),
    ("boolean", "ordinal"): ("mann_whitney", "spearman", "kendall_tau_b"),
    ("boolean", "datetime"): ("mann_whitney", "datetime_features"),
    ("categorical", "categorical"): ("chi_square", "g_test"),
    ("categorical", "ordinal"): ("kruskal_wallis", "chi_square"),
    ("categorical", "datetime"): ("kruskal_wallis", "datetime_features"),
    ("ordinal", "ordinal"): ("spearman", "kendall_tau_b"),
    ("ordinal", "datetime"): ("spearman", "kendall_tau_b"),
    ("datetime", "datetime"): ("pearson", "spearman", "kendall_tau_b"),
}

# label, question, null hypothesis, applicability. This metadata is fixed
# before any p-value is computed; effects never add tests to the plan.
METHODS = {
    "pearson": ("皮尔逊相关（Pearson r）", "线性关联", "总体线性相关系数为零", "N≥3，两列有变异，观测独立"),
    "spearman": ("Spearman 秩相关", "单调关联", "总体 Spearman 秩相关为零", "N≥3；N<30 置换，否则渐近 p"),
    "kendall_tau_b": ("Kendall τ-b", "单调关联", "总体 Kendall 秩关联为零", "N≥3，并列秩校正；N<30 置换，否则渐近 p"),
    "point_biserial": ("点二列相关", "二分类与数量的线性关联", "数量与 0/1 编码的总体线性相关为零", "N≥3，有两个有效类别"),
    "welch_t": ("Welch t 检验", "两组均值", "两组总体均值相等", "每组≥2，均值标准误大于零"),
    "mann_whitney": ("Mann-Whitney U", "两组秩分布", "独立两组来自同一分布", "两组非空；任一组<10 置换，否则渐近 p"),
    "anova": ("单因素 ANOVA", "多组均值", "各组总体均值相等", "≤20 组，每组≥3，组内 SD>0，最大/最小 SD≤3"),
    "welch_anova": ("Welch ANOVA", "异方差多组均值", "各组总体均值相等", "每组≥2，所有组方差>0"),
    "kruskal_wallis": ("Kruskal-Wallis", "多组秩分布", "独立各组来自同一分布", "N≥3，至少两组；任一组<5 置换，否则渐近 p"),
    "chi_square": ("卡方独立性检验（χ²）", "类别分布与独立性", "两个分类变量相互独立", "至少 2×2 非空边际；稀疏时置换校准"),
    "fisher_exact": ("双侧 Fisher 精确检验", "二分类独立性", "固定边际下两个二分类变量独立", "2×2 非空边际，双侧概率排序"),
    "g_test": ("似然比 G 检验", "类别分布与独立性", "两个分类变量相互独立", "至少 2×2 非空边际；稀疏时按 G 统计量置换"),
    "datetime_features": ("日历特征筛选", "日历模式", "各日历特征与分类变量独立", "仅纳入有变异特征；各叶子分别校准，探索性筛选"),
}


class MethodRequestError(ValueError):
    """An unknown or type-incompatible explicit method request."""


@dataclass
class Column:
    name: str
    kind: str
    values: np.ndarray
    labels: list[str]
    dates: pd.Series | None = None


def _columns(p1: Any, p2: Any) -> tuple[list[Column], list[dict[str, Any]]]:
    columns, transformations = [], []
    for prepared in (p1, p2):
        series = prepared.analysis_series
        kind = prepared.kind
        labels: list[str] = []
        dates = None
        if kind not in KINDS:
            raise MethodRequestError(f"列 “{prepared.name}” 的 {kind} 类型不能直接分析。")
        if kind == "categorical" and series.nunique() == 2:
            kind = "boolean"
        if prepared.kind == "boolean":
            values = series.astype(int).to_numpy()
            labels = list(prepared.value_labels)
        elif kind in {"boolean", "categorical"}:
            strings = series.astype(str)
            labels = list(pd.unique(strings))
            if kind == "boolean" and prepared.type_source == "inferred":
                labels.sort()
            values = pd.Categorical(strings, categories=labels).codes
        elif kind == "ordinal":
            values = series.cat.codes.to_numpy()
            labels = list(series.cat.categories)
            transformations.append({"column": prepared.name, "kind": "ordinal_order",
                                    "levels": prepared.levels,
                                    "note": "编码仅表示顺序，不假定等级间距相等"})
        elif kind == "datetime":
            dates = series
            timezone = str(series.dt.tz) if series.dt.tz is not None else "naive"
            if series.dt.tz is not None:
                dates = series.dt.tz_convert("UTC").dt.tz_localize(None)
            values = ((dates - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)).to_numpy()
            transformations.append({"column": prepared.name, "kind": "epoch_days", "unit": "day",
                                    "epoch": "1970-01-01", "timezone": timezone,
                                    "timezone_handling": "converted_to_UTC" if timezone != "naive" else "as_recorded"})
        else:
            values = series.to_numpy(dtype=float)
        if kind == "boolean":
            transformations.append({"column": prepared.name, "kind": "binary_coding",
                                    "levels": [{"value": value, "code": i} for i, value in enumerate(labels)]})
        columns.append(Column(prepared.name, kind, np.asarray(values, dtype=float), labels, dates))
    assert len(columns[0].values) == len(columns[1].values)
    assert p1.analysis_series.index.equals(p2.analysis_series.index)
    return columns, transformations


def _plan(columns: list[Column], methods: str) -> dict[str, Any]:
    kinds = tuple(sorted((column.kind for column in columns), key=KINDS.index))
    available = list(MATRIX[kinds])
    if methods == "auto":
        candidates = available.copy()
    else:
        candidates = list(dict.fromkeys(value.strip() for value in methods.split(",")))
        invalid = [value for value in candidates if value not in available]
        if invalid:
            raise MethodRequestError(f"未知或不适用的方法：{', '.join(invalid)}；适用方法：{', '.join(available)}。")
    return {"candidate_ids": candidates, "available_ids": available, "requested": methods,
            "items": [{"id": mid, "question": METHODS[mid][1], "conditions": METHODS[mid][3]} for mid in candidates],
            "effective_kinds": [column.kind for column in columns]}


def build_method_plan(p1: Any, p2: Any, methods: str = "auto") -> dict[str, Any]:
    columns, _ = _columns(p1, p2)
    return _plan(columns, methods)


def _finite(value: Any) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _test(mid: str, n: int, statistic_name: str, statistic: float | None, p: float | None,
          p_method: str, *, df: Any = None, reason: str | None = None,
          feature: str | None = None, alternative: str | None = None) -> dict[str, Any]:
    if (statistic is not None and _finite(statistic) is None) or (p is not None and _finite(p) is None):
        reason = reason or "统计量或 p 非有限，使用 null；不据此作推断"
    p = _finite(p)
    return {"id": mid if feature is None else f"{mid}.{feature}", "method_id": mid, "n": n,
            "feature": feature, "null_hypothesis": METHODS[mid][2],
            "statistic_name": statistic_name, "statistic_value": _finite(statistic), "df": df,
            "p_value": p, "p_method": p_method, "p_adjusted": None,
            "reject_adjusted": None, "family_id": None,
            "alternative": alternative or ("greater" if mid in {"anova", "welch_anova", "kruskal_wallis", "chi_square", "g_test", "datetime_features"} else "two_sided"),
            "status": "ok" if p is not None else "descriptive_only", "reason": reason}


def _calibration(test: dict, permutations: int, seed: int,
                 result: st.PermutationResult | None = None) -> None:
    test.update(permutations_requested=permutations, permutations_used=result.used if result else 0,
                seed=seed, permutation_extreme=result.extreme if result else None,
                p_resolution=result.resolution if result else None,
                mc_standard_error=result.mc_standard_error if result else None)
    if result:
        test["alternative"] = result.alternative
        if test["method_id"] in {"spearman", "kendall_tau_b"}:
            test["null_hypothesis"] = "固定两列边际分布下随机重新配对，以对应秩关联统计量检验；独立观测在该原假设下可交换"
        else:
            test["null_hypothesis"] += "；置换依赖独立观测在原假设下可交换"


def _effect(mid: str, name: str, value: Any, definition: str, *,
            direction: str | None = None, interval: dict | None = None,
            reason: str | None = None, feature: str | None = None) -> dict[str, Any]:
    if _finite(value) is None:
        reason = reason or "效应量未定义或非有限，使用 null"
    return {"id": f"{mid}.{feature + '.' if feature else ''}{name}", "method_id": mid,
            "name": name, "value": _finite(value), "definition": definition,
            "direction": direction, "interval": interval, "reason": reason, "feature": feature}


def _finish(mid: str, n: int, tests: list, effects: list, *,
            details: dict | None = None, unavailable: str | None = None) -> tuple[dict, list, list]:
    status = "not_applicable" if unavailable else ("ok" if any(t["p_value"] is not None for t in tests) else "descriptive_only")
    reason = unavailable or (None if status == "ok" else "; ".join(dict.fromkeys(t["reason"] for t in tests if t["reason"])))
    method = {"id": mid, "label": METHODS[mid][0], "question": METHODS[mid][1], "conditions": METHODS[mid][3],
              "n": n, "status": status, "reason": reason, "test_ids": [t["id"] for t in tests],
              "effect_ids": [e["id"] for e in effects], "related_method_ids": [], "details": details or {}}
    return method, tests, effects


def _grouped(columns: list[Column]) -> tuple[Column, Column, list[np.ndarray], list[str]]:
    group = next(column for column in columns if column.kind in {"boolean", "categorical"})
    measure = columns[1] if group is columns[0] else columns[0]
    codes = np.unique(group.values).astype(int)
    return group, measure, [measure.values[group.values == code] for code in codes], [group.labels[code] for code in codes]


def _summaries(groups: list[np.ndarray], labels: list[str]) -> list[dict[str, Any]]:
    return [{"group": label, "n": len(values), "mean": float(values.mean()),
             "std": float(values.std(ddof=1)) if len(values) > 1 else None,
             "median": float(np.median(values)), "min": float(values.min()), "max": float(values.max())}
            for label, values in zip(labels, groups)]


def _table(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ua, ca = np.unique(a, return_inverse=True)
    ub, cb = np.unique(b, return_inverse=True)
    table = np.bincount(ca * len(ub) + cb, minlength=len(ua) * len(ub)).reshape(len(ua), len(ub))
    return table, ua, ub, ca, cb


def _contingency_leaf(mid: str, a: np.ndarray, b: np.ndarray, permutations: int, seed: int,
                      *, feature: str | None = None) -> tuple[dict, list, dict]:
    table, _, _, ca, cb = _table(a, b)
    n = len(a)
    expected = np.outer(table.sum(axis=1), table.sum(axis=0)) / n
    chi = float(np.sum((table - expected) ** 2 / expected))
    sparse = (expected.min() < 5 if table.shape == (2, 2)
              else expected.min() < 1 or np.mean(expected < 5) > 0.2)
    fisher = mid == "fisher_exact" or (feature is not None and table.shape == (2, 2) and sparse)
    df = (table.shape[0] - 1) * (table.shape[1] - 1)
    reason, calibration = None, None
    effects = [_effect(mid, "cramers_v", math.sqrt(chi / (n * (min(table.shape) - 1))),
                       "sqrt(未校正 Pearson χ² / (N * min(r-1,c-1)))", feature=feature)]
    if fisher:
        p, odds = st.fisher_exact_2x2(table)
        statistic, statistic_name, p_method, df = odds, "odds_ratio", "fisher_exact_two_sided", None
        if not math.isfinite(odds):
            reason = "优势比无穷或未定义，使用 null；Fisher 精确 p 仍有效"
        effects.append(_effect(mid, "odds_ratio", odds, "(n00*n11)/(n01*n10)", feature=feature,
                               direction="按表中行/列标签顺序", reason="分母为零，优势比未定义或无穷" if not math.isfinite(odds) else None))
    else:
        is_g = mid == "g_test"
        if is_g:
            g = st.likelihood_ratio(table)
            statistic, p = g.g, g.p
            effects.append(_effect(mid, "mutual_information", g.mutual_information,
                                   "G/(2N)，自然对数，单位 nat；仅描述，不是新增检验", feature=feature))
        else:
            statistic = float(np.sum(np.maximum(0, np.abs(table - expected) - .5) ** 2 / expected)) if table.shape == (2, 2) and not sparse else chi
            p = st.chi2_sf(statistic, df)
        statistic_name, p_method = ("G" if is_g else "chi_square"), ("chi_square_asymptotic" if is_g or table.shape != (2, 2) else "chi_square_yates")
        if sparse:
            p, p_method = None, "not_computed"
            if permutations:
                rng, extreme = np.random.default_rng(seed), 0
                k1, k2 = table.shape
                for _ in range(permutations):
                    perm = np.bincount(ca * k2 + rng.permutation(cb), minlength=k1 * k2).reshape(k1, k2)
                    if is_g:
                        positive = perm > 0
                        value = float(2 * np.sum(perm[positive] * np.log(perm[positive] / expected[positive])))
                    else:
                        value = float(np.sum((perm - expected) ** 2 / expected))
                    extreme += value >= statistic - 1e-12
                calibration = st.PermutationResult.from_extreme(extreme, permutations, seed, "greater")
                p, p_method = calibration.p, "permutation"
            else:
                reason = "列联表稀疏且置换已禁用，仅报告描述统计量"
    test = _test(mid, n, statistic_name, statistic, p, p_method, df=df, reason=reason, feature=feature,
                 alternative="two_sided" if fisher else "greater")
    _calibration(test, permutations, seed, calibration)
    details = {"table": table.tolist(), "expected": expected.tolist(), "min_expected": float(expected.min()),
               "pct_expected_lt5": float(100 * np.mean(expected < 5))}
    return test, effects, details


def _execute(mid: str, columns: list[Column], alpha: float, permutations: int, seed: int) -> tuple[dict, list, list]:
    n = len(columns[0].values)
    if mid in {"pearson", "spearman", "kendall_tau_b", "point_biserial"}:
        if n < 3:
            return _finish(mid, n, [], [], unavailable="相关计算至少需要 3 个完整配对")
        x, y = (column.values for column in columns)
        interval, ci_reason = None, None
        if mid == "kendall_tau_b":
            result = st.kendall_tau_b(x, y)
            value, p, df, name = result.tau_b, result.p, None, "kendall_tau_b"
        else:
            result = st.spearman(x, y, alpha) if mid == "spearman" else st.pearson(x, y, alpha)
            value, p, df = result.r, result.p, result.df
            name = {"pearson": "pearson_r", "spearman": "spearman_rho", "point_biserial": "point_biserial_r"}[mid]
            if mid != "spearman":
                if n > 3 and abs(value) < 1:
                    interval = {"low": result.ci_low, "high": result.ci_high, "level": 1 - alpha,
                                "method": "fisher_z", "scope": "individual"}
                else:
                    ci_reason = "N≤3 或完全相关，Fisher-z 区间不可用"
        reason, calibration = None, None
        p_method = "kendall_tie_corrected_normal" if mid == "kendall_tau_b" else "rank_t_asymptotic" if mid == "spearman" else "student_t"
        if mid in {"spearman", "kendall_tau_b"} and n < 30:
            df = None
            if permutations:
                calibration = st.permutation_rank_test(mid, x, y, n_permutations=permutations, seed=seed)
                p, p_method = calibration.p, "permutation"
            else:
                p, reason = None, "N<30 且置换已禁用，仅描述秩关联；渐近条件不满足"
        test = _test(mid, n, name, value, p, p_method if p is not None else "not_computed", df=df, reason=reason)
        _calibration(test, permutations, seed, calibration)
        definitions = {"pearson": "cov(X,Y)/(SD(X)*SD(Y))，线性相关",
                       "point_biserial": "数量与记录的二分类 0/1 编码的 Pearson r",
                       "spearman": "平均秩转换后的 Pearson r，处理并列秩",
                       "kendall_tau_b": "(一致对数-不一致对数)/sqrt((总对数-X并列对数)*(总对数-Y并列对数))"}
        if mid in {"spearman", "kendall_tau_b"}:
            ci_reason = "当前未估计该秩系数的置信区间；不套用 Pearson Fisher-z 区间"
        effect = _effect(mid, name, value, definitions[mid], interval=interval,
                         direction="正值表示两列数量/显式顺序/0→1 同向增加", reason=ci_reason)
        return _finish(mid, n, [test], [effect])

    if mid in {"welch_t", "mann_whitney", "anova", "welch_anova", "kruskal_wallis"}:
        group, measure, groups, labels = _grouped(columns)
        sizes = [len(values) for values in groups]
        details = {"group_labels": labels, "group_sizes": sizes}
        if measure.kind == "ordinal":
            details["level_counts"] = [{"group": label, "counts": {measure.labels[int(v)]: int(np.sum(values == v)) for v in np.unique(values)}}
                                       for label, values in zip(labels, groups)]
        else:
            details["group_summary"] = _summaries(groups, labels)
        effects, reason, calibration = [], None, None
        if mid == "welch_t":
            if min(sizes) < 2 or sum(values.var(ddof=1) / len(values) for values in groups) <= 0:
                reason = "Welch t 需要每组≥2 且均值标准误大于零"
                effects.append(_effect(mid, "cohen_d", None, "(均值1-均值0)/合并组内标准差",
                                       reason="样本不足或合并组内标准差为零，Cohen's d 不可定义"))
                return _finish(mid, n, [], effects, details=details, unavailable=reason)
            result = st.welch_t_test(groups[1], groups[0])
            statistic, p, df, p_method = result.t, result.p, result.df, "welch_student_t"
            effects.append(_effect(mid, "cohen_d", result.cohen_d, "(均值1-均值0)/合并组内标准差",
                                   direction=f"正值表示 {labels[1]} 高于 {labels[0]}"))
        elif mid == "mann_whitney":
            result = st.mann_whitney(groups[1], groups[0])
            statistic, p, df, p_method = result.u, result.p, None, "tie_corrected_normal"
            effects.append(_effect(mid, "rank_biserial", result.rank_biserial, "2*U(编码1)/(n0*n1)-1，并列值计半",
                                   direction=f"正值表示 {labels[1]} 倾向高于 {labels[0]}"))
            if min(sizes) < 10:
                if permutations:
                    calibration = st.permutation_rank_test(mid, measure.values, group.values, n_permutations=permutations, seed=seed)
                    p, p_method = calibration.p, "permutation"
                else:
                    p, reason = None, "至少一组<10 且置换已禁用，仅描述秩差异；渐近条件不满足"
        elif mid == "anova":
            sds = [float(values.std(ddof=1)) if len(values) >= 2 else 0 for values in groups]
            if len(groups) > 20 or min(sizes) < 3 or min(sds) <= 0 or max(sds) / min(sds) > 3:
                return _finish(mid, n, [], [], details=details, unavailable=METHODS[mid][3])
            result = st.one_way_anova(groups)
            statistic, p, df, p_method = result.f, result.p, [result.df_between, result.df_within], "f_distribution"
            effects = [_effect(mid, "eta_squared", result.eta_squared, "组间平方和/总平方和"),
                       _effect(mid, "omega_squared", result.omega_squared, "偏差校正的解释方差比例，负估计截为0")]
        elif mid == "welch_anova":
            if min(sizes) < 2 or any(values.var(ddof=1) <= 0 for values in groups):
                return _finish(mid, n, [], [], details=details, unavailable=METHODS[mid][3])
            result = st.welch_anova(groups)
            statistic, p, df, p_method = result.f, result.p, [result.df_between, result.df_within], "welch_f_distribution"
        else:
            if n < 3:
                return _finish(mid, n, [], [], details=details, unavailable="Kruskal-Wallis 至少需要 3 个观测")
            result = st.kruskal_wallis(groups)
            statistic, p, df, p_method = result.h, result.p, result.df, "tie_corrected_chi_square"
            effects.append(_effect(mid, "epsilon_squared", result.epsilon_squared, "H/(N-1)，基于秩的解释比例"))
            if min(sizes) < 5:
                if permutations:
                    calibration = st.permutation_rank_test(mid, measure.values, group.values, n_permutations=permutations, seed=seed)
                    p, p_method = calibration.p, "permutation"
                else:
                    p, reason = None, "至少一组<5 且置换已禁用，仅描述秩差异；渐近条件不满足"
        test = _test(mid, n, {"welch_t": "t", "mann_whitney": "U", "anova": "F", "welch_anova": "F", "kruskal_wallis": "H"}[mid],
                     statistic, p, p_method if p is not None else "not_computed", df=df, reason=reason)
        _calibration(test, permutations, seed, calibration)
        return _finish(mid, n, [test], effects, details=details)

    if mid == "datetime_features":
        date = next(column for column in columns if column.kind == "datetime")
        category = columns[1] if date is columns[0] else columns[0]
        features = {"year": date.dates.dt.year, "month": date.dates.dt.month,
                    "day": date.dates.dt.day, "weekday": date.dates.dt.weekday}
        if (date.dates.dt.hour != 0).any() or (date.dates.dt.minute != 0).any():
            features.update(hour=date.dates.dt.hour, minute=date.dates.dt.minute)
        tests, effects, excluded, tables = [], [], [], {}
        for feature, values in features.items():
            if values.nunique() < 2:
                excluded.append({"feature": feature, "reason": "该日历特征无变异"})
                continue
            test, leaf_effects, table = _contingency_leaf(mid, values.to_numpy(), category.values, permutations, seed, feature=feature)
            tests.append(test)
            effects.extend(leaf_effects)
            tables[feature] = table
        return _finish(mid, n, tests, effects, details={"excluded_features": excluded, "tables": tables},
                       unavailable="无有变异的日历特征" if not tests else None)

    assert mid in {"chi_square", "g_test", "fisher_exact"}
    test, effects, details = _contingency_leaf(mid, columns[0].values, columns[1].values, permutations, seed)
    table, ua, ub, _, _ = _table(columns[0].values, columns[1].values)
    details.update(row_labels=[columns[0].labels[int(v)] for v in ua],
                   col_labels=[columns[1].labels[int(v)] for v in ub])
    if all(column.kind == "boolean" for column in columns):
        a, b, c, d = table.ravel()
        phi = (float(a) * d - float(b) * c) / math.sqrt(float(a + b) * float(c + d) * float(a + c) * float(b + d))
        effects.append(_effect(mid, "phi", phi, "(n00*n11-n01*n10)/sqrt(四个边际积)", direction="按两列记录的0/1方向；反转任一列符号反转"))
    return _finish(mid, n, [test], effects, details=details)


def _presentation(columns: list[Column], methods: list[dict], tests: list[dict]) -> tuple[dict, dict, dict]:
    a, b = columns
    extra, descriptives = {}, {}
    category_kinds = {"boolean", "categorical"}
    if a.kind in category_kinds and b.kind in category_kinds or ({a.kind, b.kind} == {"categorical", "ordinal"}):
        table, ua, ub, _, _ = _table(a.values, b.values)
        rows, cols = [a.labels[int(v)] for v in ua], [b.labels[int(v)] for v in ub]
        chart = {"kind": "heatmap", "table": table.tolist(), "row_labels": rows, "col_labels": cols}
        extra["table"] = pd.DataFrame(table, index=rows, columns=cols)
        extra["expected"] = pd.DataFrame(np.outer(table.sum(axis=1), table.sum(axis=0)) / len(a.values), index=rows, columns=cols)
        descriptives["contingency"] = {"row_labels": rows, "col_labels": cols, "observed": table.tolist(), "expected": extra["expected"].values.tolist()}
    elif a.kind in category_kinds or b.kind in category_kinds:
        _, measure, groups, labels = _grouped(columns)
        if measure.kind == "datetime":
            group = b if measure is a else a
            chart = {"kind": "timeline", "dates": measure.values.tolist(), "categories": [group.labels[int(v)] for v in group.values],
                     "x_label": measure.name, "y_label": group.name}
        else:
            chart = {"kind": "box", "groups": [values.tolist() for values in groups], "labels": labels, "x_label": measure.name}
        if measure.kind != "ordinal":
            extra["group_summary"] = _summaries(groups, labels)
            descriptives["group_summary"] = extra["group_summary"]
        else:
            descriptives["ordinal_frequencies"] = [{"group": label, "counts": {measure.labels[int(v)]: int(np.sum(values == v)) for v in np.unique(values)}} for label, values in zip(labels, groups)]
    else:
        chart = {"kind": "scatter", "x": a.values.tolist(), "y": b.values.tolist(), "x_label": a.name, "y_label": b.name,
                 "x_date": a.kind == "datetime", "y_date": b.kind == "datetime"}
    calendar = [test for test in tests if test["method_id"] == "datetime_features"]
    if any(method["id"] == "datetime_features" for method in methods):
        extra["features"] = [{"feature": test["feature"], "statistic": test["statistic_value"], "statistic_name": test["statistic_name"],
                              "df": test["df"], "p": test["p_value"], "p_adjusted": test["p_adjusted"],
                              "reject_adjusted": test["reject_adjusted"], "family_id": test["family_id"],
                              "test_used": test["p_method"], "status": test["status"]} for test in calendar]
    return chart, extra, descriptives


def analyze_pair(p1: Any, p2: Any, *, methods: str = "auto", alpha: float = .05,
                 permutations: int = 2000, seed: int = 20241102) -> tuple[dict, dict, dict]:
    columns, transformations = _columns(p1, p2)
    plan = _plan(columns, methods)
    results, tests, effects = [], [], []
    for mid in plan["candidate_ids"]:
        method, leaf_tests, method_effects = _execute(mid, columns, alpha, permutations, seed)
        results.append(method)
        tests.extend(leaf_tests)
        effects.extend(method_effects)
    for method in results:
        method["related_method_ids"] = [other["id"] for other in results if other["id"] != method["id"] and other["question"] == method["question"]]
    multiplicity = inference.apply_holm(tests, alpha)
    conclusions, comparisons = inference.summarize(results, tests, effects, alpha=alpha)
    chart, extra, descriptives = _presentation(columns, results, tests)
    analysis = {"method_plan": plan, "methods": results, "tests": tests, "effects": effects,
                "transformations": transformations, "descriptives": descriptives,
                "multiplicity": multiplicity, "conclusions": conclusions, "comparisons": comparisons,
                "inference_status": "adjusted" if multiplicity["m"] else "descriptive_only",
                "seed": seed, "permutations_requested": permutations}
    return analysis, chart, extra
