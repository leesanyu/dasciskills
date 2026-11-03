"""Dependency-light statistics for the dasci-relationship skill.

Only NumPy is required.  The bundled DSH Python does not ship SciPy, so the
small set of distributions used here (normal, Student t, chi-square, F) and the
2x2 Fisher exact test are implemented directly.  Formulas follow Numerical
Recipes and standard textbook definitions.

All functions expect already-cleaned one-dimensional arrays without NaN/None.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Iterable, Sequence

import numpy as np

_EPS = 3.0e-14
_FPMIN = 1.0e-300
_NORMAL = NormalDist()


# ---------------------------------------------------------------------------
# Special functions
# ---------------------------------------------------------------------------

def _gser(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a,x), series expansion."""
    if x <= 0.0:
        return 0.0
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(10000):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * _EPS:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gcf(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x), continued fraction."""
    b = x + 1.0 - a
    c = 1.0 / _FPMIN
    d = 1.0 / b if abs(b) > _FPMIN else 1.0 / _FPMIN
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = b + an / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def gammaincc(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a,x) = 1 - P(a,x)."""
    if a <= 0.0 or x < 0.0:
        raise ValueError("gammaincc requires a > 0 and x >= 0")
    if x == 0.0:
        return 1.0
    if x < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _gser(a, x)))
    return max(0.0, min(1.0, _gcf(a, x)))


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b)."""
    if a <= 0.0 or b <= 0.0:
        raise ValueError("betainc requires a,b > 0")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return max(0.0, min(1.0, bt * _betacf(a, b, x) / a))
    return max(0.0, min(1.0, 1.0 - bt * _betacf(b, a, 1.0 - x) / b))


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def t_sf(t: float, df: float) -> float:
    """P(T > t) for a Student t distribution; t may be negative."""
    if df <= 0:
        raise ValueError("t distribution requires df > 0")
    if math.isinf(t):
        return 0.0 if t > 0 else 1.0
    x = df / (df + t * t)
    one_tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return one_tail if t >= 0 else 1.0 - one_tail


def t_two_sided_p(t: float, df: float) -> float:
    return min(1.0, 2.0 * t_sf(abs(t), df))


def f_sf(f: float, df1: float, df2: float) -> float:
    if df1 <= 0 or df2 <= 0:
        raise ValueError("F distribution requires positive dfs")
    if f <= 0:
        return 1.0
    if math.isinf(f):
        return 0.0
    return max(0.0, min(1.0, betainc(df2 / 2.0, df1 / 2.0, df2 / (df2 + df1 * f))))


def chi2_sf(x: float, df: float) -> float:
    if df <= 0:
        raise ValueError("chi-square requires df > 0")
    if x <= 0:
        return 1.0
    return gammaincc(df / 2.0, x / 2.0)


def normal_critical(alpha: float = 0.05) -> float:
    """Two-sided normal critical value."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    return _NORMAL.inv_cdf(1.0 - alpha / 2.0)


# ---------------------------------------------------------------------------
# Ranking and correlation
# ---------------------------------------------------------------------------

def rankdata(values: Sequence[float]) -> np.ndarray:
    """Average ranks, ties handled like scipy.stats.rankdata(method='average')."""
    a = np.asarray(values, dtype=float)
    n = a.size
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_a[j] == sorted_a[i]:
            j += 1
        average_rank = (i + 1 + j) / 2.0
        ranks[order[i:j]] = average_rank
        i = j
    return ranks


@dataclass
class CorrelationResult:
    n: int
    r: float
    p: float
    df: int
    t: float
    ci_low: float | None
    ci_high: float | None
    ci_note: str = ""


def pearson(x: Sequence[float], y: Sequence[float], alpha: float = 0.05) -> CorrelationResult:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size != y.size:
        raise ValueError("x and y must have the same length")
    n = int(x.size)
    if n < 3:
        raise ValueError("Pearson correlation needs at least 3 complete pairs")
    if np.std(x) == 0 or np.std(y) == 0:
        raise ValueError("a constant column has no correlation")
    r = float(np.corrcoef(x, y)[0, 1])
    df = n - 2
    if 1 - abs(r) <= 4 * np.finfo(float).eps:
        r = math.copysign(1.0, r)
        t = math.inf if r > 0 else -math.inf
        p = 0.0
        return CorrelationResult(n, r, p, df, t, None, None, "r = ±1; Fisher-z CI is undefined")
    t = r * math.sqrt(df / (1.0 - r * r))
    p = t_two_sided_p(t, df)
    if n <= 3:
        return CorrelationResult(n, r, p, df, t, None, None, "N≤3; Fisher-z CI is undefined")
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    crit = normal_critical(alpha)
    ci_low = math.tanh(z - crit * se)
    ci_high = math.tanh(z + crit * se)
    return CorrelationResult(n, r, p, df, t, ci_low, ci_high)


def spearman(x: Sequence[float], y: Sequence[float], alpha: float = 0.05) -> CorrelationResult:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size != y.size:
        raise ValueError("x and y must have the same length")
    n = int(x.size)
    if n < 3:
        raise ValueError("Spearman correlation needs at least 3 complete pairs")
    rx = rankdata(x)
    ry = rankdata(y)
    if np.std(rx) == 0 or np.std(ry) == 0:
        raise ValueError("a constant column has no correlation")
    rho = float(np.corrcoef(rx, ry)[0, 1])
    df = n - 2
    ci_note = "Spearman CI not estimated; Pearson Fisher-z interval does not apply"
    if 1 - abs(rho) <= 4 * np.finfo(float).eps:
        rho = math.copysign(1.0, rho)
        return CorrelationResult(n, rho, 0.0, df, math.inf if rho > 0 else -math.inf, None, None, ci_note)
    t = rho * math.sqrt(df / (1.0 - rho * rho))
    p = t_two_sided_p(t, df)
    return CorrelationResult(n, rho, p, df, t, None, None, ci_note)


# ---------------------------------------------------------------------------
# Contingency tables
# ---------------------------------------------------------------------------

@dataclass
class ChiSquareResult:
    n: int
    chi2: float
    chi2_pearson: float
    chi2_yates: float | None
    df: int
    p: float
    p_chi2: float
    p_fisher: float | None
    test_used: str
    cramers_v: float
    table: np.ndarray
    row_labels: list[str]
    col_labels: list[str]
    expected: np.ndarray
    min_expected: float
    pct_expected_lt5: float
    fisher_odds_ratio: float | None
    residuals: np.ndarray
    note: str = ""


def _chi2_from_table(table: np.ndarray) -> tuple[float, np.ndarray]:
    row_tot = table.sum(axis=1)
    col_tot = table.sum(axis=0)
    n = table.sum()
    expected = np.outer(row_tot, col_tot) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        terms = np.where(expected > 0, (table - expected) ** 2 / expected, 0.0)
    return float(terms.sum()), expected


def chi_square(table: Sequence[Sequence[int]], row_labels: Sequence[str] | None = None,
               col_labels: Sequence[str] | None = None) -> ChiSquareResult:
    table = np.asarray(table, dtype=float)
    if table.ndim != 2:
        raise ValueError("contingency table must be two-dimensional")
    if (table < 0).any():
        raise ValueError("contingency counts cannot be negative")
    table = table[np.ix_(table.sum(axis=1) > 0, table.sum(axis=0) > 0)]
    if table.shape[0] < 2 or table.shape[1] < 2:
        raise ValueError("one of the columns is constant; a contingency test needs at least 2 x 2 cells")
    n = int(table.sum())
    chi2_pearson, expected = _chi2_from_table(table)
    df = int((table.shape[0] - 1) * (table.shape[1] - 1))
    p_chi2 = chi2_sf(chi2_pearson, df)

    chi2_yates = None
    p_yates = None
    if table.shape == (2, 2):
        if (expected > 0).all():
            chi2_yates = float((np.maximum(0.0, np.abs(table - expected) - 0.5) ** 2 / expected).sum())
            p_yates = chi2_sf(chi2_yates, 1)
        else:
            chi2_yates = chi2_pearson
            p_yates = p_chi2

    p_fisher = None
    odds_ratio = None
    if table.shape == (2, 2):
        p_fisher, odds_ratio = fisher_exact_2x2(table)

    min_expected = float(expected.min())
    pct_lt5 = float((expected < 5).mean() * 100.0)

    if table.shape == (2, 2) and min_expected < 5.0:
        test_used = "fisher"
        p_value = p_fisher if p_fisher is not None else p_chi2
        chi2 = chi2_pearson
        note = "2x2 table has an expected count below 5; Fisher's exact test is used."
    elif table.shape == (2, 2):
        test_used = "chi2_yates"
        chi2 = chi2_yates if chi2_yates is not None else chi2_pearson
        p_value = p_yates if p_yates is not None else p_chi2
        note = "2x2 table; Yates' continuity correction is used."
    else:
        test_used = "chi2"
        chi2 = chi2_pearson
        p_value = p_chi2
        note = ""

    cramers_v = math.sqrt(max(0.0, chi2_pearson / (n * (min(table.shape) - 1))))

    row_tot = table.sum(axis=1)[:, None]
    col_tot = table.sum(axis=0)[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = np.sqrt(expected * (1.0 - row_tot / n) * (1.0 - col_tot / n))
        residuals = np.where(denom > 0, (table - expected) / denom, 0.0)

    if row_labels is None:
        row_labels = [str(i) for i in range(table.shape[0])]
    if col_labels is None:
        col_labels = [str(i) for i in range(table.shape[1])]

    return ChiSquareResult(
        n=n, chi2=float(chi2), chi2_pearson=float(chi2_pearson),
        chi2_yates=chi2_yates, df=df, p=float(p_value), p_chi2=float(p_chi2),
        p_fisher=p_fisher, test_used=test_used, cramers_v=float(cramers_v),
        table=table, row_labels=list(row_labels), col_labels=list(col_labels),
        expected=expected, min_expected=min_expected, pct_expected_lt5=pct_lt5,
        fisher_odds_ratio=odds_ratio, residuals=residuals, note=note,
    )


def fisher_exact_2x2(table: Sequence[Sequence[int]]) -> tuple[float, float]:
    """Two-sided Fisher exact p-value (probability-ordering) and odds ratio."""
    t = np.asarray(table, dtype=int)
    if t.shape != (2, 2):
        raise ValueError("Fisher exact test here supports only 2x2 tables")
    if (t < 0).any():
        raise ValueError("counts cannot be negative")
    a, b = int(t[0, 0]), int(t[0, 1])
    c, d = int(t[1, 0]), int(t[1, 1])
    n = a + b + c + d
    row1 = a + b
    col1 = a + c
    if n == 0 or row1 == 0 or col1 == 0:
        raise ValueError("empty margin in 2x2 table")

    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)

    def log_prob(x: int) -> float:
        return (
            math.lgamma(row1 + 1) - math.lgamma(x + 1) - math.lgamma(row1 - x + 1)
            + math.lgamma(n - row1 + 1) - math.lgamma(col1 - x + 1)
            - math.lgamma(n - row1 - col1 + x + 1)
            - (math.lgamma(n + 1) - math.lgamma(col1 + 1) - math.lgamma(n - col1 + 1))
        )

    logs = {x: log_prob(x) for x in range(lo, hi + 1)}
    max_log = max(logs.values())
    probs = {x: math.exp(v - max_log) for x, v in logs.items()}
    observed = probs[a]
    p_two = sum(p for p in probs.values() if p <= observed + 1e-12)
    p_two = min(1.0, p_two / sum(probs.values()))

    if b * c == 0:
        odds = math.inf if a * d > 0 else 1.0
    else:
        odds = (a * d) / (b * c)
    return float(p_two), float(odds)


# ---------------------------------------------------------------------------
# Group comparisons
# ---------------------------------------------------------------------------

@dataclass
class AnovaResult:
    n: int
    k: int
    f: float
    df_between: int
    df_within: int
    p: float
    eta_squared: float
    omega_squared: float
    group_means: list[float]
    group_sds: list[float]
    group_sizes: list[int]


def one_way_anova(groups: Sequence[Sequence[float]]) -> AnovaResult:
    arrays = [np.asarray(g, dtype=float) for g in groups if len(g) >= 2]
    if len(arrays) < 2:
        raise ValueError("ANOVA needs at least two groups with 2+ observations each")
    n = int(sum(a.size for a in arrays))
    k = len(arrays)
    grand = float(np.concatenate(arrays).mean())
    ssb = float(sum(a.size * (a.mean() - grand) ** 2 for a in arrays))
    ssw = float(sum(((a - a.mean()) ** 2).sum() for a in arrays))
    df_b = k - 1
    df_w = n - k
    if ssw == 0.0:
        f = math.inf if ssb > 0 else 0.0
        p = 0.0 if ssb > 0 else 1.0
    else:
        f = (ssb / df_b) / (ssw / df_w)
        p = f_sf(f, df_b, df_w)
    ss_total = ssb + ssw
    eta2 = ssb / ss_total if ss_total > 0 else 0.0
    omega2 = (ssb - df_b * (ssw / df_w)) / (ss_total + ssw / df_w) if ss_total > 0 else 0.0
    # A negative omega-squared is conventionally reported as zero.
    omega2 = max(0.0, min(1.0, omega2))
    return AnovaResult(
        n=n, k=k, f=float(f), df_between=df_b, df_within=df_w, p=float(p),
        eta_squared=float(eta2), omega_squared=float(omega2),
        group_means=[float(a.mean()) for a in arrays],
        group_sds=[float(a.std(ddof=1)) for a in arrays],
        group_sizes=[int(a.size) for a in arrays],
    )


@dataclass
class KruskalResult:
    n: int
    k: int
    h: float
    df: int
    p: float
    epsilon_squared: float
    group_medians: list[float]
    group_sizes: list[int]


def kruskal_wallis(groups: Sequence[Sequence[float]]) -> KruskalResult:
    arrays = [np.asarray(g, dtype=float) for g in groups if len(g) >= 1]
    if len(arrays) < 2:
        raise ValueError("Kruskal-Wallis needs at least two non-empty groups")
    n = int(sum(a.size for a in arrays))
    if n < 3:
        raise ValueError("Kruskal-Wallis needs at least 3 observations")
    all_values = np.concatenate(arrays)
    ranks = rankdata(all_values)
    offset = 0
    rank_sums = []
    for a in arrays:
        rank_sums.append(float(ranks[offset:offset + a.size].sum()))
        offset += a.size
    h = 12.0 / (n * (n + 1.0)) * sum(
        (rs * rs) / a.size for rs, a in zip(rank_sums, arrays)
    ) - 3.0 * (n + 1.0)
    _, tie_counts = np.unique(all_values, return_counts=True)
    tie_term = float(sum(t ** 3 - t for t in tie_counts if t > 1))
    correction = 1.0 - tie_term / (n ** 3 - n) if n > 1 else 1.0
    if correction <= 0:
        raise ValueError("Kruskal-Wallis is undefined when all values are tied")
    h = max(0.0, h / correction)
    df = len(arrays) - 1
    p = chi2_sf(max(0.0, h), df)
    epsilon2 = h / (n - 1) if n > 1 else 0.0
    return KruskalResult(
        n=n, k=len(arrays), h=float(h), df=df, p=float(p),
        epsilon_squared=float(epsilon2),
        group_medians=[float(np.median(a)) for a in arrays],
        group_sizes=[int(a.size) for a in arrays],
    )


@dataclass
class WelchResult:
    n1: int
    n2: int
    mean1: float
    mean2: float
    sd1: float
    sd2: float
    t: float
    df: float
    p: float
    cohen_d: float


def welch_t_test(a: Sequence[float], b: Sequence[float]) -> WelchResult:
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size < 2 or y.size < 2:
        raise ValueError("Welch t-test needs at least 2 observations per group")
    n1, n2 = int(x.size), int(y.size)
    m1, m2 = float(x.mean()), float(y.mean())
    v1, v2 = float(x.var(ddof=1)), float(y.var(ddof=1))
    se2 = v1 / n1 + v2 / n2
    if se2 <= 0:
        raise ValueError("Welch t and Cohen d are undefined with zero within-group variance")
    t = (m1 - m2) / math.sqrt(se2)
    df = se2 ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    p = t_two_sided_p(t, df)
    pooled_sd = math.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    d = (m1 - m2) / pooled_sd
    return WelchResult(n1, n2, m1, m2, math.sqrt(v1), math.sqrt(v2), float(t), float(df), float(p), float(d))


@dataclass
class MannWhitneyResult:
    n1: int
    n2: int
    u: float
    p: float
    z: float
    rank_biserial: float
    median1: float
    median2: float


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> MannWhitneyResult:
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size < 1 or y.size < 1:
        raise ValueError("Mann-Whitney needs at least one observation per group")
    n1, n2 = int(x.size), int(y.size)
    n = n1 + n2
    combined = np.concatenate([x, y])
    ranks = rankdata(combined)
    r1 = float(ranks[:n1].sum())
    u1 = r1 - n1 * (n1 + 1) / 2.0
    u2 = n1 * n2 - u1
    u = min(u1, u2)
    mu = n1 * n2 / 2.0
    _, tie_counts = np.unique(combined, return_counts=True)
    tie_term = float(sum(t ** 3 - t for t in tie_counts if t > 1))
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0:
        z = 0.0
        p = 1.0
    else:
        # Move the absolute distance toward the null mean, without crossing
        # it. At U=mu the two-sided p must remain exactly one.
        z = -max(0.0, mu - u - 0.5) / math.sqrt(var)
        p = min(1.0, 2.0 * norm_sf(abs(z)))
    rank_biserial = 2.0 * u1 / (n1 * n2) - 1.0
    return MannWhitneyResult(n1, n2, float(u), float(p), float(z), float(rank_biserial),
                             float(np.median(x)), float(np.median(y)))


# ---------------------------------------------------------------------------
# Permutation calibration
# ---------------------------------------------------------------------------

@dataclass
class PermutationResult:
    p: float
    requested: int
    used: int
    seed: int
    alternative: str
    extreme: int
    resolution: float
    mc_standard_error: float

    @classmethod
    def from_extreme(cls, extreme: int, requested: int, seed: int,
                     alternative: str) -> PermutationResult:
        p = (extreme + 1) / (requested + 1)
        return cls(p, requested, requested, seed, alternative, int(extreme),
                   1 / (requested + 1), math.sqrt(p * (1 - p) / requested))


def permutation_rank_test(method: str, x: Sequence[float], y: Sequence[float], *,
                          n_permutations: int, seed: int) -> PermutationResult:
    """Randomly re-pair ranks/labels under an exchangeable-observation null.

    x,y are paired values for correlation, or values and group labels for U/KW.
    Ties and group sizes remain fixed. Small-sample Kendall uses concordance
    scores: its tau-b denominator is invariant under this permutation.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2
            or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))):
        raise ValueError("permutation test needs equally sized finite 1D arrays")
    if n_permutations < 1 or seed < 0:
        raise ValueError("permutation test needs a positive budget and nonnegative seed")
    n = len(x)
    if np.unique(x).size < 2 or np.unique(y).size < 2:
        raise ValueError("permutation test needs variation in values and labels")
    if method == "spearman":
        if n < 3:
            raise ValueError("Spearman needs at least 3 pairs")
        rx, ry = rankdata(x), rankdata(y)
        rx, ry = rx - rx.mean(), ry - ry.mean()
        denominator = float(np.linalg.norm(rx) * np.linalg.norm(ry))

        def statistic(indices: np.ndarray) -> float:
            return abs(float(np.dot(rx, ry[indices]) / denominator))

    elif method == "kendall_tau_b":
        if n < 3:
            raise ValueError("Kendall tau-b needs at least 3 pairs")
        i, j = np.triu_indices(n, 1)
        signs = np.sign(x[j] - x[i])

        def statistic(indices: np.ndarray) -> float:
            perm = y[indices]
            return abs(float(np.dot(signs, np.sign(perm[j] - perm[i]))))

    elif method in {"mann_whitney", "kruskal_wallis"}:
        _, codes, sizes = np.unique(y, return_inverse=True, return_counts=True)
        ranks = rankdata(x)
        if method == "mann_whitney":
            if len(sizes) != 2:
                raise ValueError("Mann-Whitney needs exactly two groups")

            def statistic(indices: np.ndarray) -> float:
                u = float(ranks[codes[indices] == 0].sum()) - sizes[0] * (sizes[0] + 1) / 2
                return abs(u - sizes[0] * sizes[1] / 2)

        else:
            if n < 3:
                raise ValueError("Kruskal-Wallis needs at least 3 observations")
            _, counts = np.unique(x, return_counts=True)
            correction = 1 - float(np.sum(counts.astype(float)**3 - counts)) / (n**3 - n)

            def statistic(indices: np.ndarray) -> float:
                sums = np.bincount(codes[indices], weights=ranks, minlength=len(sizes))
                h = (12 / (n * (n + 1)) * np.sum(sums**2 / sizes) - 3 * (n + 1)) / correction
                return max(0.0, float(h))

    else:
        raise ValueError(f"unsupported rank permutation method: {method}")
    observed = statistic(np.arange(n))
    rng, extreme = np.random.default_rng(seed), 0
    for _ in range(n_permutations):
        extreme += statistic(rng.permutation(n)) >= observed - 1e-12
    alternative = "greater" if method == "kruskal_wallis" else "two_sided"
    return PermutationResult.from_extreme(extreme, n_permutations, seed, alternative)


@dataclass
class KendallResult:
    n: int
    tau_b: float
    score: int
    variance: float
    p: float


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> KendallResult:
    """Tie-corrected Kendall tau-b, O(n log n), with asymptotic two-sided p."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.size != y.size or x.size < 3:
        raise ValueError("Kendall tau-b needs at least 3 complete pairs")
    n = int(x.size)
    _, tx = np.unique(x, return_counts=True)
    _, ranks, ty = np.unique(y, return_inverse=True, return_counts=True)
    pairs = n * (n - 1) / 2
    ties_x = float(np.sum(tx * (tx - 1)) / 2)
    ties_y = float(np.sum(ty * (ty - 1)) / 2)
    denominator = math.sqrt((pairs - ties_x) * (pairs - ties_y))
    if denominator == 0:
        raise ValueError("a constant column has no Kendall tau-b")
    tree = [0] * (len(ty) + 1)

    def prefix(end: int) -> int:
        total = 0
        while end:
            total += tree[end]
            end -= end & -end
        return total

    order = np.argsort(x, kind="mergesort")
    score = 0
    i = 0
    while i < n:
        j = i + 1
        while j < n and x[order[j]] == x[order[i]]:
            j += 1
        # Query the x-tie block before inserting it: same-x pairs do not
        # contribute to concordance or discordance.
        for index in order[i:j]:
            rank = int(ranks[index])
            score += prefix(rank) - (i - prefix(rank + 1))
        for index in order[i:j]:
            pos = int(ranks[index]) + 1
            while pos < len(tree):
                tree[pos] += 1
                pos += pos & -pos
        i = j
    tx, ty = tx.astype(float), ty.astype(float)
    variance = (n * (n - 1) * (2 * n + 5)
                - np.sum(tx * (tx - 1) * (2 * tx + 5))
                - np.sum(ty * (ty - 1) * (2 * ty + 5))) / 18
    variance += np.sum(tx * (tx - 1)) * np.sum(ty * (ty - 1)) / (2 * n * (n - 1))
    variance += (np.sum(tx * (tx - 1) * (tx - 2)) * np.sum(ty * (ty - 1) * (ty - 2))
                 / (9 * n * (n - 1) * (n - 2)))
    p = min(1.0, 2 * norm_sf(abs(score) / math.sqrt(variance)))
    return KendallResult(n, score / denominator, score, float(variance), p)


@dataclass
class WelchAnovaResult:
    f: float
    df_between: int
    df_within: float
    p: float


def welch_anova(groups: Sequence[Sequence[float]]) -> WelchAnovaResult:
    """Welch's heteroscedastic one-way ANOVA, retaining every input group."""
    arrays = [np.asarray(group, dtype=float) for group in groups]
    if len(arrays) < 2 or any(len(group) < 2 for group in arrays):
        raise ValueError("Welch ANOVA needs at least two groups with 2+ observations")
    sizes = np.array([len(group) for group in arrays], dtype=float)
    variances = np.array([group.var(ddof=1) for group in arrays])
    if np.any(variances <= 0):
        raise ValueError("Welch ANOVA needs positive variance in every group")
    means = np.array([group.mean() for group in arrays])
    k = len(arrays)
    weights = sizes / variances
    relative = weights / weights.sum()
    mean = float(np.sum(relative * means))
    term = float(np.sum((1 - relative) ** 2 / (sizes - 1)))
    f = float(np.sum(weights * (means - mean) ** 2) / (k - 1)
              / (1 + 2 * (k - 2) * term / (k * k - 1)))
    df2 = (k * k - 1) / (3 * term)
    return WelchAnovaResult(f, k - 1, df2, f_sf(f, k - 1, df2))


@dataclass
class LikelihoodRatioResult:
    g: float
    df: int
    p: float
    mutual_information: float
    expected: np.ndarray


def likelihood_ratio(table: Sequence[Sequence[int]]) -> LikelihoodRatioResult:
    """Likelihood-ratio G statistic and descriptive mutual information (nat)."""
    observed = np.asarray(table, dtype=float)
    if (observed.ndim != 2 or min(observed.shape) < 2 or np.any(observed < 0)
            or np.any(observed.sum(axis=0) == 0) or np.any(observed.sum(axis=1) == 0)):
        raise ValueError("G test needs a nonnegative table with 2+ nonempty rows and columns")
    n = float(observed.sum())
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / n
    positive = observed > 0
    g = max(0.0, float(2 * np.sum(observed[positive] * np.log(observed[positive] / expected[positive]))))
    df = (observed.shape[0] - 1) * (observed.shape[1] - 1)
    return LikelihoodRatioResult(g, df, chi2_sf(g, df), g / (2 * n), expected)
