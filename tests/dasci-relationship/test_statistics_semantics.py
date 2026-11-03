"""T1 semantic contracts and regressions of the existing analysis branches."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[2] / 'skills' / 'dasci-relationship' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import data_relationship as dr


def prepare(values, name="value", **kwargs):
    frame, _ = dr.normalize_frame(pd.DataFrame({name: values}))
    return dr.prepare_column(name, 0, frame[name], **kwargs)


def validate_pair(p1, p2):
    frame, _ = dr.normalize_frame(pd.DataFrame({"a": p1.source_series, "b": p2.source_series}))
    return dr.prepare_pair(frame, p1, p2)


class ColumnSemanticsTests(unittest.TestCase):
    def test_negative_values_are_observations(self):
        for values in (["有", "无"], ["是", "否"], ["true", "false"], [1, 0]):
            with self.subTest(values=values):
                col = prepare(values)
                self.assertEqual(col.profile()["non_null"], 2)
                self.assertEqual(col.profile()["conversion_failures"], 0)

    def test_binary_labels_and_direction(self):
        col = prepare(["有", "无", "有"])
        self.assertEqual(col.value_labels, ["无", "有"])
        self.assertEqual(col.series.astype(int).tolist(), [1, 0, 1])
        self.assertEqual(col.profile()["levels"], [
            {"value": "无", "code": 0}, {"value": "有", "code": 1},
        ])
        _, chart, _ = dr.multi.analyze_pair(col, prepare([1, 2, 3], name="amount"), permutations=0)
        self.assertEqual(chart["labels"], ["无", "有"])
        self.assertEqual(chart["groups"], [[2.0], [1.0, 3.0]])

    def test_low_cardinality_numeric_only_suggests(self):
        for values in ([0, 1, 0, 1], ["0", "1", "0", "1"], [1, 2, 3, 1]):
            with self.subTest(values=values):
                col = prepare(values)
                self.assertEqual(col.kind, "numeric")
                self.assertTrue(col.warnings)

    def test_numeric_category_override_and_provenance(self):
        col = prepare([10, 20, 30, 10], name="department", kind="categorical")
        profile = col.profile()
        self.assertEqual(profile["inferred_kind"], "numeric")
        self.assertEqual(profile["effective_kind"], "categorical")
        self.assertEqual(profile["type_source"], "user")
        self.assertEqual(profile["index"], 1)
        self.assertEqual(col.series.tolist(), [10, 20, 30, 10])

    def test_two_level_categorical_becomes_boolean(self):
        col = prepare([20, 10, 20, 10], kind="categorical")
        self.assertEqual(col.kind, "boolean")
        self.assertEqual(col.series.astype(int).tolist(), [0, 1, 0, 1])
        self.assertEqual(col.profile()["levels"], [
            {"value": 20, "code": 0}, {"value": 10, "code": 1},
        ])

    def test_explicit_boolean_keeps_zero_one_direction(self):
        col = prepare([1, 0, 1, 0], kind="boolean")
        self.assertEqual(col.series.astype(int).tolist(), [1, 0, 1, 0])
        self.assertEqual(col.value_labels, ["0", "1"])

    def test_boolean_rejects_multiple_categories(self):
        with self.assertRaises(dr.UserError):
            prepare(["a", "b", "c"], kind="boolean")

    def test_constant_and_nullable_native_booleans_can_be_profiled(self):
        constant = prepare(pd.Series([True, True, pd.NA], dtype="boolean"))
        self.assertEqual(constant.kind, "boolean")
        self.assertEqual(constant.profile()["unique"], 1)
        with self.assertRaises(dr.UserError):
            validate_pair(constant, prepare([1, 2, 3]))
        nullable = prepare(pd.Series([True, False, pd.NA], dtype="boolean"))
        self.assertEqual(nullable.series.astype(int).tolist(), [1, 0])
        self.assertEqual(nullable.profile()["conversion_failures"], 0)

    def test_ordinal_preserves_order_and_unobserved_level(self):
        col = prepare(["高", "低", "高"], kind="ordinal", order=["低", "中", "高"])
        self.assertEqual(col.kind, "ordinal")
        self.assertTrue(col.series.cat.ordered)
        self.assertEqual(col.series.cat.codes.tolist(), [2, 0, 2])
        self.assertEqual(col.profile()["sample"], ["高", "低", "高"])
        self.assertEqual([v["value"] for v in col.profile()["levels"]], ["低", "中", "高"])

    def test_binary_ordinal_stays_ordinal(self):
        self.assertEqual(prepare([1, 2, 1], kind="ordinal", order=[1, 2]).kind, "ordinal")

    def test_numeric_json_order_matches_file_labels(self):
        col = prepare(["3", "1", "2"], kind="ordinal", order=[1, 2, 3])
        self.assertEqual(col.series.cat.codes.tolist(), [2, 0, 1])

    def test_invalid_ordinal_order_is_rejected(self):
        for order in (None, [], ["低", "低", "高"], ["低"], [None, "低", "高"], [["低"], "高"]):
            with self.subTest(order=order), self.assertRaises(dr.UserError):
                prepare(["低", "高"], kind="ordinal", order=order)
        with self.assertRaises(dr.UserError):
            prepare(["1", "2"], kind="ordinal", order=[1, "1", 2])
        with self.assertRaises(dr.UserError):
            prepare([1, 2], kind="numeric", order=[1, 2])

    def test_suspected_native_numeric_id_requires_override(self):
        for values in (list(range(100, 125)), [str(i) for i in range(100, 125)]):
            with self.subTest(values=values):
                col = prepare(values, name="customer_id")
                self.assertEqual(col.kind, "id")
                with self.assertRaises(dr.UserError):
                    validate_pair(col, prepare(list(range(25)), name="amount"))
                confirmed = prepare(values, name="customer_id", kind="numeric")
                self.assertEqual(confirmed.kind, "numeric")
                self.assertEqual(confirmed.profile()["inferred_kind"], "id")
                self.assertEqual(confirmed.profile()["type_source"], "user")

    def test_empty_constant_and_high_cardinality_text_are_rejected(self):
        other = prepare(range(60), name="amount")
        for values in ([None] * 60, ["same"] * 60, [f"free text {i}" for i in range(60)]):
            with self.subTest(values=values[:2]), self.assertRaises(dr.UserError):
                validate_pair(prepare(values), other)

    def test_conversion_failures_and_original_missing_are_distinct(self):
        col = prepare(["12", "bad", None, "inf", "-inf", "0"], kind="numeric")
        self.assertEqual(col.profile()["conversion_failures"], 3)
        # A wholly empty row is removed by normalization, not a failed conversion.
        self.assertEqual(col.profile()["source_missing"], 0)
        self.assertTrue(np.isfinite(col.series.dropna()).all())

    def test_inferred_numeric_failure_is_also_tracked(self):
        col = prepare([str(i) for i in range(20)] + ["bad"])
        self.assertEqual(col.kind, "numeric")
        self.assertEqual(col.profile()["conversion_failures"], 1)

    def test_datetime_conversion_tracks_failure_and_unit(self):
        col = prepare(["2024-01-01", "bad", "2024-01-03"], kind="datetime")
        self.assertEqual(col.profile()["conversion_failures"], 1)
        self.assertEqual(col.profile()["unit"], "day")
        other = prepare([1, 2, 3], name="amount")
        validate_pair(col, other)
        _, chart, _ = dr.multi.analyze_pair(col, other, permutations=0)
        values = chart["x"]
        self.assertEqual(values[1] - values[0], 2)

    def test_ordinal_does_not_silently_use_nominal_statistics(self):
        col = prepare(["低", "高", "低"], kind="ordinal", order=["低", "高"])
        self.assertEqual(dr.multi.build_method_plan(col, prepare([10, 20, 30]))["candidate_ids"], ["spearman", "kendall_tau_b"])


class PairCleaningTests(unittest.TestCase):
    def test_row_accounting_is_mutually_exclusive(self):
        raw = pd.DataFrame({
            "x": [None, "bad", "bad", None, "1", "2", "3", "4"],
            "y": [None, "bad", None, "4", "2", "4", "6", "8"],
        })
        frame, _ = dr.normalize_frame(raw)
        p1 = dr.prepare_column("x", 0, frame.x, kind="numeric")
        p2 = dr.prepare_column("y", 1, frame.y, kind="numeric")
        cleaning = dr.prepare_pair(frame, p1, p2)
        self.assertEqual(cleaning["original_rows"], 8)
        self.assertEqual(cleaning["empty_rows"], 1)
        self.assertEqual(cleaning["conversion_failure_rows"], 2)
        self.assertEqual(cleaning["missing_pair_rows"], 1)
        self.assertEqual(cleaning["n"], 4)
        self.assertEqual([c["failed_cells"] for c in cleaning["columns"]], [2, 1])
        self.assertEqual(cleaning["original_rows"] - sum(cleaning[k] for k in (
            "empty_rows", "conversion_failure_rows", "missing_pair_rows")), cleaning["n"])
        self.assertEqual(p2.profile()["source_missing"], 1)

    def test_pair_filter_rechecks_category_variation(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({"x": [1, 2, None], "g": ["a", "a", "b"]}))
        cols = dr.prepare_columns(frame)
        with self.assertRaises(dr.UserError):
            dr.prepare_pair(frame, *cols)

    def test_two_remaining_groups_use_only_common_pairs(self):
        frame, _ = dr.normalize_frame(pd.DataFrame({
            "x": [1, 2, 3, 4, 5, 6, None], "g": ["a", "b", "a", "b", "a", "b", "c"],
        }))
        p1, p2 = dr.prepare_columns(frame)
        dr.prepare_pair(frame, p1, p2)
        self.assertEqual(p2.profile()["unique"], 3)
        self.assertEqual(p2.profile()["paired_unique"], 2)
        result, _, _ = dr.multi.analyze_pair(p1, p2, permutations=0)
        self.assertEqual(result["method_plan"]["candidate_ids"], ["point_biserial", "welch_t", "mann_whitney"])
        self.assertTrue(all(method["n"] == 6 for method in result["methods"]))
        expected = np.corrcoef([1, 2, 3, 4, 5, 6], [0, 1, 0, 1, 0, 1])[0, 1]
        self.assertAlmostEqual(next(t["statistic_value"] for t in result["tests"] if t["method_id"] == "point_biserial"), expected, places=4)


class CliRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, *args, ok=True):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "data_relationship.py"), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
        )
        payload = json.loads(proc.stdout, parse_constant=lambda x: self.fail(f"invalid JSON: {x}"))
        self.assertEqual(proc.returncode, 0 if ok else 1, payload)
        self.assertEqual(payload["ok"], ok)
        return payload

    def analyze(self, frame, *extra, suffix=".csv", chart=False):
        path = self.root / f"input{suffix}"
        if suffix == ".xlsx":
            frame.to_excel(path, index=False, sheet_name="数据")
            sheet = ["--sheet", "数据"]
        else:
            frame.to_csv(path, index=False)
            sheet = []
        out = self.root / "output"
        result = self.cli("analyze", "--input", path, *sheet, "--col1-index", 1,
                          "--col2-index", 2, "--out", out,
                          *([] if chart else ["--no-chart"]), *extra)
        saved = json.loads(Path(result["result_path"]).read_text(),
                           parse_constant=lambda x: self.fail(f"invalid saved JSON: {x}"))
        self.assertEqual(saved, result)
        self.assertTrue({"method", "method_label", "reason", "metrics", "interpretation", "schema_version"}.isdisjoint(result))
        self.assertNotIn("legacy_primary", result["method_plan"])
        self.assertTrue(all("role" not in test for test in result["tests"]))
        self.assertIn("# 数据关系分析报告", Path(result["report_md_path"]).read_text())
        self.assertEqual(result["cleaning"]["n"], result["n"])
        return result

    def test_csv_and_excel_keep_negative_labels_and_missing_policy(self):
        for suffix in (".csv", ".xlsx"):
            with self.subTest(suffix=suffix):
                result = self.analyze(pd.DataFrame({
                    "flag": ["有", "无"] * 6, "amount": [3, 1, 4, 2, 5, 3, 6, 4, 7, 5, 8, 6],
                }), suffix=suffix)
                self.assertEqual(result["n"], 12)
                self.assertEqual(result["col1"]["value_labels"], ["无", "有"])
                self.assertEqual([m["id"] for m in result["methods"]], ["point_biserial", "welch_t", "mann_whitney"])
                metric = next(t["statistic_value"] for t in result["tests"] if t["method_id"] == "point_biserial")
                self.assertAlmostEqual(metric, np.corrcoef([1, 0] * 6, [3, 1, 4, 2, 5, 3, 6, 4, 7, 5, 8, 6])[0, 1], places=4)

    def test_cli_numeric_override_and_counting(self):
        result = self.analyze(pd.DataFrame({
            "x": [None, "bad", "bad", None, 1, 2, 3, 4],
            "y": [None, "bad", None, 4, 2, 4, 6, 8],
        }), "--col1-type", "numeric", "--col2-type", "numeric")
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["total_rows"], 7)
        self.assertEqual(result["missing_pairs"], 3)
        self.assertEqual(result["cleaning"]["original_rows"], 8)
        self.assertEqual(result["col1"]["type_source"], "user")

    def test_existing_pearson_names_and_chart(self):
        frame = pd.DataFrame({"x": range(1, 13), "y": [3 * i + 2 for i in range(1, 13)]})
        result = self.analyze(frame, "--col1", "x", "--col2", "y", chart=True)
        self.assertEqual([m["id"] for m in result["methods"]], ["pearson", "spearman", "kendall_tau_b"])
        self.assertEqual(next(t["statistic_value"] for t in result["tests"] if t["method_id"] == "pearson"), 1)
        self.assertTrue(Path(result["chart_paths"][0]).is_file())

    def test_existing_chi_square_counts(self):
        result = self.analyze(pd.DataFrame({
            "a": ["red"] * 20 + ["blue"] * 20,
            "b": ["left"] * 15 + ["right"] * 5 + ["left"] * 5 + ["right"] * 15,
        }))
        self.assertEqual([m["id"] for m in result["methods"]], ["chi_square", "fisher_exact", "g_test"])
        table = pd.read_csv(Path(result["out_dir"]) / "contingency.csv", index_col=0)
        self.assertEqual(sorted(table.to_numpy().ravel().tolist()), [5, 5, 15, 15])
        self.assertEqual(result["n"], 40)

    def test_existing_anova_groups_with_numeric_category_override(self):
        result = self.analyze(pd.DataFrame({
            "amount": [1, 2, 3, 5, 6, 7, 9, 10, 11], "department": [10] * 3 + [20] * 3 + [30] * 3,
        }), "--col2-type", "categorical")
        self.assertEqual([m["id"] for m in result["methods"]], ["anova", "welch_anova", "kruskal_wallis"])
        self.assertEqual(next(t["statistic_value"] for t in result["tests"] if t["method_id"] == "anova"), 48)
        groups = pd.read_csv(Path(result["out_dir"]) / "group_summary.csv")
        self.assertEqual(groups["n"].tolist(), [3, 3, 3])
        self.assertEqual(groups["mean"].tolist(), [2, 6, 10])

    def test_existing_datetime_feature_screen(self):
        result = self.analyze(pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=42).strftime("%Y-%m-%d"),
            "group": ["a", "b", "c"] * 14,
        }), "--permutations", 0)
        self.assertEqual(result["method_plan"]["candidate_ids"], ["kruskal_wallis", "datetime_features"])
        self.assertEqual(result["n"], 42)
        self.assertEqual(result["col1"]["unit"], "day")
        self.assertTrue((Path(result["out_dir"]) / "datetime_features.csv").is_file())

    def test_ordinal_input_errors_are_structured(self):
        path = self.root / "ordinal.csv"
        pd.DataFrame({"level": ["低", "高", "低"], "x": [1, 2, 3]}).to_csv(path, index=False)
        for order in ('["低"]', '["低","低","高"]', 'not json'):
            with self.subTest(order=order):
                payload = self.cli("analyze", "--input", path, "--col1", "level", "--col2", "x",
                                   "--col1-type", "ordinal", "--col1-order", order,
                                   "--out", self.root / "output", ok=False)
                self.assertIn("error", payload)
        payload = self.cli("analyze", "--input", path, "--col1", "level", "--col2", "x",
                           "--col1-type", "ordinal", "--col1-order", '["低","中","高"]',
                           "--out", self.root / "output", "--no-chart")
        self.assertEqual(payload["col1"]["effective_kind"], "ordinal")
        self.assertEqual([level["value"] for level in payload["col1"]["levels"]], ["低", "中", "高"])
        self.assertEqual(payload["method_plan"]["candidate_ids"], ["spearman", "kendall_tau_b"])
        self.assertTrue(Path(payload["result_path"]).is_file())
        self.assertEqual(Path(payload["out_dir"]).parent,self.root / "output")

    def test_inspect_exposes_provenance_and_preserves_empty_csv_rows(self):
        path = self.root / "inspect.csv"
        path.write_text("flag,value\n有,1\n\n无,0\n", encoding="utf-8")
        payload = self.cli("inspect", "--input", path)
        self.assertEqual(payload["cleaning"]["original_rows"], 3)
        self.assertEqual(payload["cleaning"]["empty_rows"], 1)
        self.assertEqual(payload["columns"][0]["type_source"], "inferred")


if __name__ == "__main__":
    unittest.main()
