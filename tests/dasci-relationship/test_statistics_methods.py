"""T2 matrix and numerical references (no SciPy dependency).

Reference constants were checked with SciPy 1.16.3 on 2026-11-02:
kendalltau(method='asymptotic'), f_oneway(equal_var=False), and
chi2_contingency(correction=False, lambda_='log-likelihood').
"""

import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'))
import data_relationship as dr
import methods as engine
import stats as st


KINDS = ["numeric", "boolean", "categorical", "ordinal", "datetime"]
MATRIX = [
    ("pearson", "spearman", "kendall_tau_b"),
    ("point_biserial", "welch_t", "mann_whitney"),
    ("anova", "welch_anova", "kruskal_wallis"),
    ("spearman", "kendall_tau_b"),
    ("pearson", "spearman", "kendall_tau_b"),
    ("chi_square", "fisher_exact", "g_test"),
    ("chi_square", "g_test"),
    ("mann_whitney", "spearman", "kendall_tau_b"),
    ("mann_whitney", "datetime_features"),
    ("chi_square", "g_test"),
    ("kruskal_wallis", "chi_square"),
    ("kruskal_wallis", "datetime_features"),
    ("spearman", "kendall_tau_b"),
    ("spearman", "kendall_tau_b"),
    ("pearson", "spearman", "kendall_tau_b"),
]


def make_pair(kind1, kind2, n=120):
    rng = np.random.default_rng(713)
    def values(kind, offset):
        if kind == "numeric":
            return rng.normal(size=n) + np.arange(n) / n
        if kind == "boolean":
            return ["否" if (i + offset) % 2 else "是" for i in range(n)]
        if kind == "categorical":
            return ["abc"[(i + offset) % 3] for i in range(n)]
        if kind == "ordinal":
            return [["低", "中", "高"][(i + offset) % 3] for i in range(n)]
        return pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    frame, _ = dr.normalize_frame(pd.DataFrame({"x": values(kind1, 0), "y": values(kind2, 1)}))
    columns = [dr.prepare_column(name, i, frame[name], kind=kind,
                                order=["低", "中", "高", "未观察"] if kind == "ordinal" else None)
               for i, (name, kind) in enumerate(zip(frame.columns, (kind1, kind2)))]
    dr.prepare_pair(frame, *columns)
    return frame, columns


def analyze(columns, **kwargs):
    return engine.analyze_pair(*columns, **{"permutations": 19, **kwargs})[0]


class PrimitiveTests(unittest.TestCase):
    def test_kendall_ties_reference_and_reverse_direction(self):
        result = st.kendall_tau_b([1, 2, 2, 3, 4], [1, 3, 2, 4, 4])
        self.assertAlmostEqual(result.tau_b, 0.8888888888888888, places=12)
        self.assertAlmostEqual(result.p, 0.03735647244558174, places=10)
        reverse = st.kendall_tau_b([1, 2, 2, 3, 4], [-1, -3, -2, -4, -4])
        self.assertAlmostEqual(reverse.tau_b, -result.tau_b, places=12)
        self.assertAlmostEqual(reverse.p, result.p, places=12)

    def test_kendall_large_sorted_sample(self):
        result = st.kendall_tau_b(np.arange(10000), np.arange(10000))
        self.assertEqual(result.tau_b, 1)

    def test_welch_anova_reference(self):
        result = st.welch_anova([[1, 2, 4, 8], [2, 3, 4, 5, 6], [10, 11, 14, 18, 20, 21]])
        self.assertAlmostEqual(result.f, 15.313557976894726, places=10)
        self.assertAlmostEqual(result.p, 0.003612374270108274, places=10)
        self.assertEqual(result.df_between, 2)
        self.assertGreater(result.df_within, 0)

    def test_g_statistic_p_and_mutual_information(self):
        result = st.likelihood_ratio([[10, 20, 30], [20, 10, 10]])
        self.assertAlmostEqual(result.g, 13.233821636969084, places=10)
        self.assertAlmostEqual(result.p, 0.0013375565248934327, places=10)
        self.assertAlmostEqual(result.mutual_information, result.g / 200, places=12)
        np.testing.assert_allclose(result.expected, [[18, 18, 24], [12, 12, 16]])
        zero = st.likelihood_ratio([[10, 0], [0, 10]])
        self.assertAlmostEqual(zero.g, 40 * np.log(2), places=10)

    def test_undefined_primitives_reject_instead_of_dropping_groups(self):
        with self.assertRaises(ValueError):
            st.kendall_tau_b([1, 1, 1], [1, 2, 3])
        for groups in ([[1], [2, 3]], [[1, 1], [2, 3]]):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                st.welch_anova(groups)
        with self.assertRaises(ValueError):
            st.likelihood_ratio([[0, 0], [1, 2]])

    def test_existing_numeric_statistics_reference_constants(self):
        groups = [[1, 2, 4, 8], [2, 3, 4, 5, 6], [10, 11, 14, 18, 20, 21]]
        welch = st.welch_t_test(*groups[:2])
        self.assertAlmostEqual(welch.t, -0.14691063206231753, places=10)
        self.assertAlmostEqual(welch.df, 4.244197115032584, places=10)
        self.assertAlmostEqual(welch.p, 0.8899194251710687, places=10)
        kw = st.kruskal_wallis(groups)
        self.assertAlmostEqual(kw.h, 10.25161290322581, places=10)
        self.assertAlmostEqual(kw.p, 0.005941423952978059, places=10)
        mw = st.mann_whitney(*groups[:2])
        self.assertEqual(mw.u, 8)
        self.assertAlmostEqual(mw.p, 0.7109919960746027, places=10)
        self.assertAlmostEqual(mw.rank_biserial, -0.2, places=10)
        chi = st.chi_square([[10, 20, 30], [20, 10, 10]])
        self.assertAlmostEqual(chi.chi2_pearson, 13.194444444444445, places=10)
        self.assertAlmostEqual(chi.p, 0.001364152090848616, places=10)
        fisher, odds = st.fisher_exact_2x2([[1, 9], [11, 3]])
        self.assertAlmostEqual(fisher, 0.0027594561852200836, places=10)
        self.assertAlmostEqual(odds, 1 / 33, places=10)
        pearson = st.pearson([1, 2, 4, 8], [4, 1, 3, 7])
        self.assertAlmostEqual(pearson.r, 0.764502300922595, places=10)
        self.assertAlmostEqual(pearson.p, 0.23549769907740492, places=10)
        self.assertAlmostEqual(st.spearman([1, 2, 4, 8], [4, 1, 3, 7]).r, .4, places=10)

    def test_u_at_its_null_mean_has_p_one(self):
        result = st.mann_whitney(np.arange(10), np.arange(10))
        self.assertEqual(result.u, 50)
        self.assertEqual(result.p, 1)
        self.assertEqual(result.rank_biserial, 0)


class MethodMatrixTests(unittest.TestCase):
    def test_all_15_pairs_and_reverse_share_candidates_and_n(self):
        for (kind1, kind2), expected in zip(itertools.combinations_with_replacement(KINDS, 2), MATRIX):
            _, cols = make_pair(kind1, kind2)
            for pair in (cols, cols[::-1]):
                with self.subTest(kinds=(kind1, kind2), reverse=pair is not cols):
                    result = analyze(pair)
                    self.assertEqual(tuple(result["method_plan"]["candidate_ids"]), expected)
                    self.assertEqual([m["id"] for m in result["methods"]], list(expected))
                    self.assertTrue(all(m["n"] == 120 for m in result["methods"]))
                    self.assertTrue(all(t["n"] == 120 for t in result["tests"]))
                    for method in result["methods"]:
                        self.assertEqual(method["status"], "ok")
                    json.dumps(result, ensure_ascii=False, allow_nan=False, default=dr.json_default)

    def test_plan_is_frozen_before_statistics_and_validates_subset(self):
        _, cols = make_pair("numeric", "numeric")
        with patch.object(st, "pearson", side_effect=AssertionError("plan computed p")):
            plan = engine.build_method_plan(*cols, methods="kendall_tau_b,spearman,kendall_tau_b")
        self.assertEqual(plan["candidate_ids"], ["kendall_tau_b", "spearman"])
        for request in ("unknown", "chi_square", "", "auto,pearson"):
            with self.subTest(request=request), self.assertRaises(engine.MethodRequestError):
                engine.build_method_plan(*cols, methods=request)

    def test_explicit_subset_does_not_execute_other_methods(self):
        _, cols = make_pair("numeric", "numeric")
        with patch.object(st, "pearson", side_effect=AssertionError("unrequested Pearson")):
            result = analyze(cols, methods="spearman,spearman")
        self.assertEqual([t["method_id"] for t in result["tests"]], ["spearman"])
        self.assertNotIn("legacy_primary", result["method_plan"])
        self.assertEqual([e["name"] for e in result["effects"]], ["spearman_rho"])

    def test_common_pairs_and_ordinal_mapping(self):
        frame, cols = make_pair("numeric", "ordinal")
        frame.loc[0, "x"] = np.nan
        frame.loc[1, "x"] = np.nan
        cols = [dr.prepare_column("x", 0, frame.x, kind="numeric"),
                dr.prepare_column("y", 1, frame.y, kind="ordinal", order=["低", "中", "高", "未观察"])]
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        self.assertTrue(all(method["n"] == 118 for method in result["methods"]))
        self.assertEqual(len(result["transformations"][0]["levels"]), 4)

    def test_binary_direction_effects_reverse(self):
        frame, cols = make_pair("numeric", "boolean")
        forward = analyze(cols)
        frame.y = frame.y.map({"是": "否", "否": "是"})
        flipped = [cols[0], dr.prepare_column("y", 1, frame.y, kind="boolean")]
        dr.prepare_pair(frame, *flipped)
        backward = analyze(flipped)
        for name in ("point_biserial_r", "cohen_d", "rank_biserial"):
            a = next(e["value"] for e in forward["effects"] if e["name"] == name)
            b = next(e["value"] for e in backward["effects"] if e["name"] == name)
            self.assertAlmostEqual(a, -b, places=10)

    def test_invalid_anova_keeps_other_methods_and_reasons(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({"x": [1, 2, 4, 10, 20, 40], "g": ["a", "a", "b", "b", "c", "c"]}))
        cols = [dr.prepare_column("x", 0, frame.x), dr.prepare_column("g", 1, frame.g)]
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        states = {m["id"]: m["status"] for m in result["methods"]}
        self.assertEqual(states["anova"], "not_applicable")
        self.assertEqual(states["welch_anova"], "ok")
        self.assertEqual(states["kruskal_wallis"], "ok")

    def test_only_descriptive_subset_preserves_requested_plan(self):
        _, cols = make_pair("numeric", "numeric", n=8)
        result = analyze(cols, methods="spearman", permutations=0)
        self.assertNotIn("legacy_primary", result["method_plan"])
        self.assertEqual(result["methods"][0]["status"], "descriptive_only")
        self.assertIsNone(result["tests"][0]["p_value"])

    def test_correlations_n2_are_preserved_as_unavailable_candidates(self):
        _, cols = make_pair("numeric", "numeric", n=2)
        result = analyze(cols)
        self.assertEqual(len(result["methods"]), 3)
        self.assertTrue(all(m["status"] == "not_applicable" and m["reason"] for m in result["methods"]))
        self.assertNotIn("legacy_primary", result["method_plan"])
        self.assertFalse(result["tests"])

    def test_correlation_intervals_and_small_rank_status(self):
        _, cols = make_pair("numeric", "numeric", n=8)
        result = analyze(cols)
        pearson = next(effect for effect in result["effects"] if effect["name"] == "pearson_r")
        self.assertEqual(pearson["interval"]["scope"], "individual")
        self.assertTrue(all(effect["interval"] is None for effect in result["effects"] if effect is not pearson))
        self.assertEqual([test["status"] for test in result["tests"]], ["ok", "ok", "ok"])

    def test_small_groups_keep_u_kw_effects_and_reject_undefined_means(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({"x": [1, 2, 3], "g": ["a", "b", "b"]}))
        cols = [dr.prepare_column("x", 0, frame.x), dr.prepare_column("g", 1, frame.g, kind="categorical")]
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        states = {method["id"]: method["status"] for method in result["methods"]}
        self.assertEqual(states, {"point_biserial": "ok", "welch_t": "not_applicable", "mann_whitney": "ok"})
        self.assertTrue(any(effect["name"] == "rank_biserial" for effect in result["effects"]))
        self.assertEqual(sum(group["n"] for group in result["descriptives"]["group_summary"]), 3)

    def test_phi_and_odds_follow_binary_code_direction(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({"a": ["是"] * 20 + ["否"] * 20,
                                                   "b": ["是"] * 15 + ["否"] * 5 + ["是"] * 5 + ["否"] * 15}))
        cols = dr.prepare_columns(frame)
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        phi = [effect["value"] for effect in result["effects"] if effect["name"] == "phi"]
        self.assertTrue(all(value == .5 for value in phi))
        odds = next(effect["value"] for effect in result["effects"] if effect["name"] == "odds_ratio")
        self.assertEqual(odds, 9)

    def test_empty_calendar_preserves_timestamp_method(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({
            "time": ["2024-01-01 00:00:01", "2024-01-01 00:00:02", "2024-01-01 00:00:03", "2024-01-01 00:00:04"],
            "flag": ["是", "否", "是", "否"],
        }))
        cols = dr.prepare_columns(frame)
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        states = {method["id"]: method["status"] for method in result["methods"]}
        self.assertEqual(states, {"mann_whitney": "ok", "datetime_features": "not_applicable"})
        self.assertEqual(len(result["methods"][1]["details"]["excluded_features"]), 4)

    def test_timezone_conversion_is_explicit(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({
            "time": pd.date_range("2024-01-01", periods=40, tz="Asia/Shanghai"), "x": np.arange(40),
        }))
        cols = dr.prepare_columns(frame)
        dr.prepare_pair(frame, *cols)
        result = analyze(cols)
        self.assertEqual(result["transformations"][0]["timezone"], "Asia/Shanghai")
        self.assertEqual(result["transformations"][0]["timezone_handling"], "converted_to_UTC")

    def test_date_leaves_and_units_have_no_container_p(self):
        _, cols = make_pair("datetime", "categorical")
        result = analyze(cols)
        calendar = next(m for m in result["methods"] if m["id"] == "datetime_features")
        self.assertTrue(calendar["test_ids"])
        self.assertTrue(all(t.get("feature") for t in result["tests"] if t["method_id"] == "datetime_features"))
        self.assertNotIn("p_value", calendar)
        self.assertEqual(result["transformations"][0]["unit"], "day")
        self.assertIn("timezone", result["transformations"][0])

    def test_sparse_chi_and_g_use_their_own_statistic(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({"a": ["a"] * 8 + ["b"] * 2, "b": ["c"] * 7 + ["d"] * 3}))
        cols = [dr.prepare_column("a", 0, frame.a, kind="categorical"),
                dr.prepare_column("b", 1, frame.b, kind="categorical")]
        dr.prepare_pair(frame, *cols)
        result = analyze(cols, seed=17)
        for method in ("chi_square", "g_test"):
            test = next(t for t in result["tests"] if t["method_id"] == method)
            self.assertEqual(test["p_method"], "permutation")
            self.assertEqual(test["permutations_used"], 19)
            self.assertGreater(test["p_value"], 0)
        self.assertEqual(result, analyze(cols, seed=17))
        disabled = engine.analyze_pair(*cols, permutations=0)[0]
        states = {method["id"]: method["status"] for method in disabled["methods"]}
        self.assertEqual(states, {"chi_square": "descriptive_only", "fisher_exact": "ok", "g_test": "descriptive_only"})

    def test_unexpected_internal_failure_propagates(self):
        _, cols = make_pair("numeric", "numeric")
        with patch.object(st, "kendall_tau_b", side_effect=RuntimeError("internal defect")):
            with self.assertRaisesRegex(RuntimeError, "internal defect"):
                analyze(cols)


class CliMethodsTests(unittest.TestCase):
    def test_cli_subset_and_all_method_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data.csv"
            pd.DataFrame({"a": np.arange(40), "b": np.arange(40) ** 2}).to_csv(path, index=False)
            args = dr.build_parser().parse_args(["analyze", "--input", str(path), "--col1", "a", "--col2", "b",
                                                 "--methods", "spearman,kendall_tau_b", "--seed", "41",
                                                 "--out", str(root / "out"), "--no-chart"])
            with patch.object(st, "pearson", side_effect=AssertionError("unrequested Pearson")):
                result = dr.cmd_analyze(args)
            self.assertEqual(result["method_plan"]["candidate_ids"], ["spearman", "kendall_tau_b"])
            text = Path(result["report_md_path"]).read_text()
            self.assertIn("spearman", text)
            self.assertIn("kendall_tau_b", text)
            self.assertIn("原始 p", text)
            self.assertIn("Holm", text)
            self.assertEqual(result["multiplicity"]["m"], 2)
            json.loads(Path(result["result_path"]).read_text(), parse_constant=lambda x: self.fail(x))

    def test_all_15_cli_reports_serialize_and_show_every_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i, (kind1, kind2) in enumerate(itertools.combinations_with_replacement(KINDS, 2)):
                with self.subTest(kinds=(kind1, kind2)):
                    frame, _ = make_pair(kind1, kind2)
                    path = root / f"input{i}.csv"
                    frame.to_csv(path, index=False)
                    argv = ["analyze", "--input", str(path), "--col1-index", "1", "--col2-index", "2",
                            "--col1-type", kind1, "--col2-type", kind2, "--permutations", "3",
                            "--out", str(root / f"out{i}"), "--no-chart"]
                    for number, kind in enumerate((kind1, kind2), start=1):
                        if kind == "ordinal":
                            argv += [f"--col{number}-order", '["低","中","高","未观察"]']
                    result = dr.cmd_analyze(dr.build_parser().parse_args(argv))
                    saved = json.loads(Path(result["result_path"]).read_text(), parse_constant=lambda x: self.fail(x))
                    report = Path(result["report_md_path"]).read_text()
                    self.assertEqual(saved, result)
                    self.assertTrue({"method", "method_label", "reason", "metrics", "interpretation"}.isdisjoint(result))
                    self.assertNotIn("legacy_primary", result["method_plan"])
                    self.assertTrue(all("role" not in test for test in result["tests"]))
                    for method in result["methods"]:
                        self.assertIn(f"### {dr.reports.METHOD_NAMES[method['id']]} · {method['id']}", report)
                        self.assertEqual(method["test_ids"], [t["id"] for t in result["tests"] if t["method_id"] == method["id"]])
                        self.assertEqual(method["effect_ids"], [e["id"] for e in result["effects"] if e["method_id"] == method["id"]])
                    for test in result["tests"]:
                        line = next(line for line in report.splitlines() if line.startswith(f"| {test['id']} |") and line.count("|") >= 11)
                        cells = [cell.strip() for cell in line.strip("|").split("|")]
                        for field, index in (("statistic_value", 3), ("p_value", 5), ("p_adjusted", 6)):
                            if test[field] is None:
                                self.assertEqual(cells[index], "—")
                            else:
                                self.assertEqual(cells[index], dr.reports.format_value(test[field]))
                    self.assertTrue(all(mid in report for mid in result["method_plan"]["candidate_ids"]))
                    self.assertEqual(result["n"], 120)
                    if {kind1, kind2} == {"boolean", "ordinal"}:
                        self.assertIn("等级频数", report)

    def test_cli_charts_decode_for_each_relationship_shape(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shapes = [("numeric", "numeric"), ("numeric", "categorical"),
                      ("categorical", "categorical"), ("datetime", "categorical")]
            for i, (kind1, kind2) in enumerate(shapes):
                with self.subTest(kinds=(kind1, kind2)):
                    frame, _ = make_pair(kind1, kind2, n=12)
                    path = root / f"data{i}.csv"
                    frame.to_csv(path, index=False)
                    args = dr.build_parser().parse_args([
                        "analyze", "--input", str(path), "--col1-index", "1", "--col2-index", "2",
                        "--col1-type", kind1, "--col2-type", kind2, "--permutations", "0",
                        "--out", str(root / f"out{i}"),
                    ])
                    result = dr.cmd_analyze(args)
                    with Image.open(result["chart_paths"][0]) as chart:
                        self.assertEqual(chart.format, "PNG")
                        self.assertGreater(min(chart.size), 0)
                        chart.verify()
                    report = Path(result["report_md_path"]).read_text()
                    self.assertIn(f"]({Path(result['chart_paths'][0]).relative_to(result['out_dir'])})", report)
                    self.assertTrue(all(m["id"] in report for m in result["methods"]))

    def test_cli_descriptive_and_unavailable_methods_still_save_complete_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n, request, expected_status in [(8, "spearman", "descriptive_only"),
                                                 (2, "auto", "not_applicable")]:
                with self.subTest(n=n):
                    path = root / f"data{n}.csv"
                    pd.DataFrame({"x": range(n), "y": np.arange(n)**2}).to_csv(path, index=False)
                    result = dr.cmd_analyze(dr.build_parser().parse_args([
                        "analyze", "--input", str(path), "--col1", "x", "--col2", "y",
                        "--methods", request, "--permutations", "0", "--no-chart",
                        "--out", str(root / f"out{n}"),
                    ]))
                    self.assertEqual(json.loads(Path(result["result_path"]).read_text()), result)
                    self.assertEqual(result["inference_status"], "descriptive_only")
                    self.assertEqual(result["multiplicity"]["m"], 0)
                    self.assertEqual(result["chart_paths"], [])
                    self.assertTrue(all(t["p_value"] is None for t in result["tests"]))
                    report = Path(result["report_md_path"]).read_text()
                    self.assertNotIn("](chart.png)", report)
                    self.assertTrue({"method", "metrics", "interpretation"}.isdisjoint(result))
                    for method in result["methods"]:
                        self.assertEqual(method["status"], expected_status)
                        self.assertIn(dr.reports.md_text(method["reason"]), report)
                    for conclusion in result['conclusions']:
                        self.assertIn(dr.reports.FINDING_STATUS[conclusion['status']],report)
                        for reference in conclusion['test_ids']+conclusion['effect_ids']:
                            self.assertIn(reference,report)


if __name__ == "__main__":
    unittest.main()
