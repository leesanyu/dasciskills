#!/usr/bin/env python3
"""Inspect and analyze the relationship between two columns.

Usage:
    python data_relationship.py inspect --input data.xlsx
    python data_relationship.py inspect --input data.xlsx --sheet "Sheet1"
    python data_relationship.py analyze --input data.csv --col1 age --col2 income
    python data_relationship.py analyze --input data.xlsx --sheet "Sheet1" \
        --col1 age --col2 city

The script writes machine-readable JSON to stdout.  It uses only pandas, numpy
and Pillow (all present in the bundled DSH Python); SciPy is deliberately not
required.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
import traceback
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import uuid4

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

# The script is normally launched by absolute path; make sibling imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import reporting as reports  # noqa: E402
import methods as multi  # noqa: E402
import selection as nav  # noqa: E402
import plotting  # noqa: E402


# ---------------------------------------------------------------------------
# Constants and errors
# ---------------------------------------------------------------------------

CSV_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"}
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES

NULL_TOKENS = {
    "", "na", "n/a", "n.a.", "null", "none", "nan", "nil", "-", "--", "—",
    "暂无", "缺失", "空",
}
TRUE_TOKENS = {"true", "yes", "y", "t", "1", "是", "对", "有", "阳性"}
FALSE_TOKENS = {"false", "no", "n", "f", "0", "否", "错", "无", "阴性"}

TYPE_LABELS = {
    "numeric": "数值",
    "categorical": "分类",
    "boolean": "布尔/二分类",
    "ordinal": "有序分类",
    "datetime": "日期时间",
    "text": "文本/高基数",
    "id": "标识符",
    "empty": "空列",
}

DATE_NAME_RE = re.compile(
    r"(date|time|datetime|timestamp|created|updated|日期|时间|年月|日期时间)", re.I
)
ID_NAME_RE = re.compile(
    r"(^id$|_id$|id$|uuid|guid|code|编号|工号|学号|序号|电话|手机|邮编|身份证)", re.I
)


UserError = nav.SelectionError

class NeedsSheet(UserError):
    def __init__(self, sheets: list[dict[str, Any]]):
        super().__init__(
            "这是一个 Excel 文件，但还没有指定工作表。请先列出所有工作表并让用户选择。",
            needs_sheet=True, step="needs_sheet",
            sheets=nav.page_options(sheets)["items"],
            sheet_catalog=nav.page_options(sheets),
        )


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def emit(payload: dict[str, Any], exit_code: int = 0) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default))
    return exit_code


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def resolve_input(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.exists():
        raise UserError(f"找不到文件：{path}", cwd=str(Path.cwd()))
    if not path.is_file():
        raise UserError(f"这不是一个文件：{path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UserError(
            f"不支持的文件类型：{path.suffix}。支持 CSV、TSV、XLSX、XLSM、XLS。",
            supported=sorted(SUPPORTED_SUFFIXES),
        )
    return path


def open_excel(path: Path) -> pd.ExcelFile:
    try:
        engine = None if path.suffix.lower() == ".xls" else "openpyxl"
        return pd.ExcelFile(path, engine=engine)
    except ImportError as exc:
        raise UserError(
            "读取旧版 .xls 需要 xlrd，但当前 Python 环境没有安装。"
            "请用 Excel/LibreOffice 将文件另存为 .xlsx 后重试。",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise UserError(f"无法打开 Excel 文件：{path}", detail=str(exc)) from exc


def list_sheets(path: Path) -> list[dict[str, Any]]:
    with open_excel(path) as xl:
        sheets = []
        for index, name in enumerate(xl.sheet_names, start=1):
            if xl.engine == "openpyxl":
                ws = xl.book[name]
                rows, cols, state = ws.max_row, ws.max_column, ws.sheet_state
                values = ws.iter_rows(min_row=2, values_only=True)
            else:  # The .xls reader exposes rows directly through xlrd.
                ws = xl.book.sheet_by_name(name)
                rows, cols = ws.nrows, ws.ncols
                state = {0: "visible", 1: "hidden", 2: "veryHidden"}[ws.visibility]
                values = (ws.row_values(row) for row in range(1, rows))
            has_data = any(any(not _is_null_token(value) for value in row) for row in values)
            sheets.append({"index": index, "name": name, "rows": rows, "columns": cols,
                           "state": state, "selectable": has_data,
                           "reason": None if has_data else "首行为表头，未发现非空数据行。",
                           "content_status": "available" if has_data else "empty",
                           "dimension_note": "已用区域估计，可能包含表头和格式，不是有效样本量；未知尺寸显示未知。"})
    return sheets


def match_sheet(sheet: str | None, sheets: list[dict[str, Any]], index: int | None = None) -> str:
    return nav.resolve_option(sheets, name=sheet, index=index, label="工作表", step="needs_sheet")["name"]


def _detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:262144]
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _score_delimiter(path: Path, encoding: str, delimiter: str) -> int:
    try:
        sample = pd.read_csv(
            path, sep=delimiter, encoding=encoding, dtype=str, nrows=20,
            keep_default_na=False, na_filter=False, engine="c",
        )
        return int(sample.shape[1])
    except Exception:
        return -1


def read_csv_table(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    encoding = _detect_encoding(path)
    candidates = ["\t", ",", ";", "|"] if path.suffix.lower() == ".tsv" else [",", ";", "\t", "|"]
    scored = [(d, _score_delimiter(path, encoding, d)) for d in candidates]
    scored.sort(key=lambda item: item[1], reverse=True)
    delimiter = scored[0][0] if scored and scored[0][1] > 0 else ","
    last_error: Exception | None = None
    for enc in [encoding, "utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"]:
        try:
            df = pd.read_csv(
                path, sep=delimiter, encoding=enc, dtype=str, header=None,
                keep_default_na=False, na_filter=False,
                skip_blank_lines=False, engine="c",
            )
            df = _split_header(df)
            return df, {"format": "csv", "encoding": enc, "delimiter": delimiter}
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.ParserError as exc:
            last_error = exc
            continue
    raise UserError(f"无法解析 CSV 文件：{path}", detail=str(last_error) if last_error else "")


def read_excel_table(path: Path, sheet: str | None, sheet_index: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    sheets = list_sheets(path)
    if sheet is None and sheet_index is None:
        raise NeedsSheet(sheets)
    actual = match_sheet(sheet, sheets, sheet_index)
    xl = open_excel(path)
    try:
        # Read everything as text so CSV and Excel go through the same type
        # inference, and identifiers with leading zeros are preserved.
        df = pd.read_excel(xl, sheet_name=actual, header=None, dtype=str,
                           keep_default_na=False, na_filter=False)
    except Exception as exc:
        raise UserError(f"无法读取工作表 “{actual}”：{exc}") from exc
    finally:
        xl.close()
    df = _split_header(df, excel=True)
    return df, {"format": "excel", "sheet": actual, "sheets": sheets,
                "sheet_index": next(option["index"] for option in sheets if option["name"] == actual)}


def _split_header(raw: pd.DataFrame, *, excel: bool = False) -> pd.DataFrame:
    if raw.empty:
        raise UserError("表格没有表头或数据。", step="needs_columns")
    headers = [None if pd.isna(value) or (excel and value == "") else str(value) for value in raw.iloc[0]]
    frame = raw.iloc[1:].reset_index(drop=True).copy()
    frame.columns = headers
    frame.attrs["original_headers"] = headers
    return frame


def load_table(path: Path, sheet: str | None = None, sheet_index: int | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        return read_excel_table(path, sheet, sheet_index)
    if sheet is not None or sheet_index is not None:
        raise UserError("CSV/TSV 文件没有工作表；请移除工作表选择。", step="needs_sheet")
    return read_csv_table(path)


# ---------------------------------------------------------------------------
# Cleaning and column typing
# ---------------------------------------------------------------------------

def make_unique_names(columns: Iterable[Any]) -> list[str]:
    names: list[str] = []
    used: set[str] = set()
    for i, raw in enumerate(columns):
        base = "" if raw is None else str(raw).strip()
        if not base:
            base = f"Unnamed_{i + 1}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}__{suffix}"
            suffix += 1
        used.add(candidate)
        names.append(candidate)
    return names


def _is_null_token(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and value.strip().lower() in NULL_TOKENS


def normalize_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    warnings_list: list[str] = []
    df = df.copy()
    original = df.attrs.get("original_headers", list(df.columns))
    df.attrs["original_headers"] = original
    df.columns = make_unique_names(original)
    if len(set(original)) != len(original):
        warnings_list.append("原表存在重复列名；重复列已自动加上 __2、__3 等后缀。")

    for column in df.columns:
        series = df[column]
        if ptypes.is_object_dtype(series) or ptypes.is_string_dtype(series):
            df[column] = series.map(
                lambda v: np.nan if _is_null_token(v) else (v.strip() if isinstance(v, str) else v)
            )

    before = len(df)
    df = df.dropna(how="all").reset_index(drop=True)
    df.attrs["cleaning"] = {"original_rows": before, "empty_rows": before - len(df)}
    if len(df) < before:
        warnings_list.append(f"已删除 {before - len(df)} 个完全空白的行。")
    if df.empty:
        warnings_list.append("表头以下没有数据行。")
    return df, warnings_list


def _clean_numeric(value: Any) -> float:
    if value is None:
        return math.nan
    try:
        if pd.isna(value):
            return math.nan
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in NULL_TOKENS:
        return math.nan
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    multiplier = 1.0
    if text.endswith("万"):
        multiplier, text = 1e4, text[:-1]
    elif text.endswith("亿"):
        multiplier, text = 1e8, text[:-1]
    percent = text.endswith("%")
    if percent:
        text = text[:-1]
    text = (
        text.replace(",", "").replace("，", "").replace(" ", "")
        .replace("$", "").replace("¥", "").replace("€", "").replace("£", "")
        .replace("+", "")
    )
    try:
        number = float(text)
    except ValueError:
        return math.nan
    if percent:
        number /= 100.0
    if negative:
        number = -number
    return number * multiplier


def _coerce_datetime(values: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = pd.to_datetime(values, errors="coerce")
        if not ptypes.is_datetime64_any_dtype(result):
            result = pd.to_datetime(values, errors="coerce", utc=True)
        # Chinese-style dates ("2024年1月2日") are not parsed by pandas' default
        # inference; normalise the separators and retry when it helps.
        if float(result.notna().mean()) < 0.95:
            normalized = values.map(
                lambda v: re.sub(r"[年月]", "-", str(v)).replace("日", "")
                if isinstance(v, str) and ("年" in v or "月" in v or "日" in v) else v
            )
            alt = pd.to_datetime(normalized, errors="coerce")
            if not ptypes.is_datetime64_any_dtype(alt):
                alt = pd.to_datetime(normalized, errors="coerce", utc=True)
            if int(alt.notna().sum()) > int(result.notna().sum()):
                result = alt
    return result


def _has_date_signal(values: pd.Series) -> bool:
    sample = " ".join(str(v) for v in values.head(100))
    return bool(
        re.search(r"\d{4}[-/年.]\d{1,2}", sample)
        or re.search(r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", sample)
        or re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", sample, re.I)
        or re.search(r"(星期一|星期二|星期三|星期四|星期五|星期六|星期日)", sample)
    )


def _looks_like_identifier(name: str, values: pd.Series) -> bool:
    texts = [str(v).strip() for v in values.head(200)]
    if not texts:
        return False
    if all(re.fullmatch(r"0\d+", t) for t in texts):
        return True
    if all(re.fullmatch(r"[0-9a-fA-F-]{16,}", t) for t in texts):
        return True
    unique_ratio = values.nunique(dropna=True) / max(1, len(values))
    if ID_NAME_RE.search(name) and unique_ratio > 0.8:
        return True
    return False


class PreparedColumn:
    def __init__(self, name: str, index: int, kind: str, series: pd.Series,
                 original_dtype: str, warnings_list: list[str] | None = None,
                 value_labels: list[str] | None = None):
        self.name = name
        self.index = index
        self.original_name = name
        self.kind = kind
        self.series = series
        self.original_dtype = original_dtype
        self.warnings = warnings_list or []
        # For boolean columns this keeps the original labels in [false, true]
        # order, so a text column containing 是/否 is not reported as True/False.
        self.value_labels = value_labels
        self.inferred_kind = kind
        self.type_source = "inferred"
        self.levels: list[dict[str, Any]] = []
        self.unit = "day" if kind == "datetime" else None
        self.source_series = series
        self.conversion_failed = pd.Series(False, index=series.index)
        self.pair_mask: pd.Series | None = None

    @property
    def analysis_series(self) -> pd.Series:
        return self.series if self.pair_mask is None else self.series[self.pair_mask]

    def profile(self) -> dict[str, Any]:
        non_null = int(self.series.notna().sum())
        total = len(self.series)
        unique = int(self.series.nunique(dropna=True))
        samples = []
        sample_series = self.source_series if self.kind in {"ordinal", "boolean"} else self.series
        for value in sample_series.dropna().head(3):
            if isinstance(value, (pd.Timestamp, datetime)):
                samples.append(value.isoformat())
            else:
                samples.append(nav.display_sample(value))
        return {
            "index": self.index + 1,
            "name": self.name,
            "original_name": self.original_name,
            "display_name": self.name,
            "kind": self.kind,
            "inferred_kind": self.inferred_kind,
            "effective_kind": self.kind,
            "type_source": self.type_source,
            "levels": self.levels,
            "unit": self.unit,
            "conversion_failures": int(self.conversion_failed.sum()),
            "source_missing": int(self.source_series.isna().sum()),
            "paired_unique": int(self.analysis_series.nunique(dropna=True)) if self.pair_mask is not None else None,
            "type": TYPE_LABELS.get(self.kind, self.kind),
            "pandas_dtype": self.original_dtype,
            "non_null": non_null,
            "missing": total - non_null,
            "missing_pct": round(100.0 * (total - non_null) / total, 2) if total else 0.0,
            "unique": unique,
            "unique_pct": round(100.0 * unique / non_null, 2) if non_null else 0.0,
            "sample": samples,
            "value_labels": self.value_labels,
            "warnings": list(self.warnings),
        }


def _infer_column(name: str, index: int, series: pd.Series) -> PreparedColumn:
    original_dtype = str(series.dtype)
    warnings_list: list[str] = []
    non_null = int(series.notna().sum())
    if non_null == 0:
        return PreparedColumn(name, index, "empty", series, original_dtype, ["整列都是空值。"])

    if ptypes.is_datetime64_any_dtype(series):
        return PreparedColumn(name, index, "datetime", series, original_dtype, warnings_list)

    if ptypes.is_bool_dtype(series):
        # Nullable boolean keeps missing values instead of raising on NA.
        return PreparedColumn(name, index, "boolean", series.astype("boolean"), original_dtype,
                              warnings_list, ["False", "True"])

    if ptypes.is_numeric_dtype(series):
        if _looks_like_identifier(name, series.dropna()):
            return PreparedColumn(name, index, "id", series, original_dtype)
        numeric = pd.to_numeric(series, errors="coerce")
        unique = int(numeric.nunique(dropna=True))
        if unique == 1:
            warnings_list.append("该列只有一个非空取值（常量）。")
        return PreparedColumn(name, index, "numeric", numeric.astype(float), original_dtype, warnings_list)

    values = series.dropna()
    text_values = values.map(lambda v: str(v).strip())
    if len(text_values) and bool(text_values.str.startswith("=").any()):
        warnings_list.append(
            "检测到以 = 开头的公式文本；如果公式没有缓存结果，请先在 Excel/LibreOffice 中重算并保存。"
        )

    if _looks_like_identifier(name, text_values):
        return PreparedColumn(name, index, "id", text_values.reindex(series.index), original_dtype)

    # Boolean-like text columns (true/false, yes/no, 是/否, ...).
    lower = text_values.map(lambda v: v.lower())
    unique_lower = set(lower.unique())
    if (unique_lower and unique_lower <= (TRUE_TOKENS | FALSE_TOKENS)
            and not unique_lower <= {"0", "1"}):
        mapped = text_values.map(lambda v: v.lower() in TRUE_TOKENS)
        if mapped.nunique(dropna=True) == 2:
            true_value = next(v for v in text_values if v.lower() in TRUE_TOKENS)
            false_value = next(v for v in text_values if v.lower() in FALSE_TOKENS)
            return PreparedColumn(name, index, "boolean", mapped.reindex(series.index), original_dtype,
                                  warnings_list, [false_value, true_value])

    # Numeric-looking strings, unless they look like identifiers or dates.
    numeric = text_values.map(_clean_numeric)
    numeric_ratio = float(numeric.notna().mean()) if len(numeric) else 0.0
    if numeric_ratio >= 0.95:
        if DATE_NAME_RE.search(name):
            parsed = _coerce_datetime(text_values)
            if float(parsed.notna().mean()) >= 0.95:
                return PreparedColumn(name, index, "datetime", parsed.reindex(series.index),
                                      original_dtype, warnings_list)
        converted = numeric.reindex(series.index).astype(float)
        if numeric_ratio < 1.0:
            warnings_list.append(
                f"有 {len(text_values) - int(numeric.notna().sum())} 个值无法解析为数值，已按缺失处理。"
            )
        unique = int(converted.nunique(dropna=True))
        if unique == 1:
            warnings_list.append("该列只有一个非空取值（常量）。")
        return PreparedColumn(name, index, "numeric", converted, original_dtype, warnings_list)

    # Date-like strings.
    if _has_date_signal(text_values) or DATE_NAME_RE.search(name):
        parsed = _coerce_datetime(text_values)
        if float(parsed.notna().mean()) >= 0.95:
            return PreparedColumn(name, index, "datetime", parsed.reindex(series.index),
                                  original_dtype, warnings_list)

    unique = int(text_values.nunique())
    unique_ratio = unique / max(1, len(text_values))
    if unique == 1:
        warnings_list.append("该列只有一个非空取值（常量）。")
        kind = "categorical"
    elif unique > 50 and unique_ratio > 0.5:
        kind = "text"
        warnings_list.append(
            f"高基数文本列（{unique} 个不同值）；直接做列联表会非常稀疏，建议先分组或编码。"
        )
    else:
        kind = "categorical"
        if unique > 30:
            warnings_list.append(f"分类较多（{unique} 类）；卡方检验可能因稀疏而不可靠。")
    return PreparedColumn(name, index, kind, text_values.reindex(series.index), original_dtype, warnings_list)


def _level_key(value: Any) -> str:
    # File readers return text. Numeric JSON levels can match the same text
    # without collapsing distinct codes such as "01" and "1".
    return str(value).lower() if isinstance(value, (bool, np.bool_)) else str(value)


def _prepare_binary(series: pd.Series) -> tuple[pd.Series, list[str], list[dict[str, Any]]]:
    values = list(pd.unique(series.dropna()))
    keys = [_level_key(v) for v in values]
    lowered = [key.lower() for key in keys]
    if set(lowered) <= TRUE_TOKENS | FALSE_TOKENS:
        codes = [int(key in TRUE_TOKENS) for key in lowered]
        if len(set(codes)) != 2:
            raise UserError("二分类必须同时包含两个有效水平；当前标签只表示同一个真假值。")
        labels = [str(values[codes.index(code)]) for code in (0, 1)]
    else:
        if len(values) != 2:
            raise UserError(f"二分类必须有两个有效水平，当前有 {len(values)} 个；请核对类型。")
        codes = [0, 1]
        labels = [str(v) for v in values]
    mapping = dict(zip(keys, codes))
    encoded = series.map(lambda v: pd.NA if pd.isna(v) else bool(mapping[_level_key(v)]))
    levels = [{"value": value, "code": code} for value, code in zip(values, codes)]
    levels.sort(key=lambda level: level["code"])
    return encoded.astype("boolean"), labels, levels


def prepare_column(name: str, index: int, series: pd.Series, *, kind: str = "auto",
                   order: list[Any] | None = None) -> PreparedColumn:
    """Prepare one normalized column; explicit semantics override inference."""
    if kind not in {"auto", "numeric", "boolean", "categorical", "ordinal", "datetime"}:
        raise UserError(f"未知字段类型：{kind}")
    if order is not None and kind != "ordinal":
        raise UserError("水平顺序只用于显式 ordinal 类型；请同时指定 --col1-type/--col2-type ordinal。")
    inferred = _infer_column(name, index, series)
    column = inferred
    if kind != "auto":
        converted = series.copy()
        levels: list[dict[str, Any]] = []
        labels = None
        effective = kind
        if kind == "numeric":
            converted = series.map(_clean_numeric).astype(float)
        elif kind == "datetime":
            # Numeric epoch units must not be guessed from a user type flag.
            converted = _coerce_datetime(series.astype("string"))
        elif kind == "ordinal":
            if not isinstance(order, list) or not order:
                raise UserError("ordinal 必须提供非空的 JSON 水平顺序数组，例如 [\"低\",\"中\",\"高\"]。")
            if any(not isinstance(v, (str, int, float, bool)) or _is_null_token(v)
                   or (isinstance(v, float) and not math.isfinite(v)) for v in order):
                raise UserError("有序水平必须是非缺失的 JSON 标量，不能使用 null、嵌套数组或对象。")
            keys = [_level_key(v) for v in order]
            if len(keys) != len(set(keys)):
                raise UserError("有序水平顺序存在重复值；每个水平只能出现一次。")
            observed = series.map(lambda v: np.nan if pd.isna(v) else _level_key(v))
            omitted = [v for v in pd.unique(observed.dropna()) if v not in keys]
            if omitted:
                raise UserError(f"有序水平顺序未覆盖观察值：{', '.join(omitted)}。请补全顺序。")
            converted = pd.Series(pd.Categorical(observed, categories=keys, ordered=True),
                                  index=series.index, name=series.name)
            levels = [{"value": v, "code": i} for i, v in enumerate(order)]
        elif kind == "boolean" or (kind == "categorical" and series.nunique(dropna=True) == 2):
            effective = "boolean"
            converted, labels, levels = _prepare_binary(series)
        elif kind == "categorical" and inferred.kind == "text":
            raise UserError(f"列 “{name}” 是高基数文本，请先按业务规则分组，再按分类分析。")
        column = PreparedColumn(name, index, effective, converted, str(series.dtype),
                                value_labels=labels)
        column.inferred_kind = inferred.kind
        column.type_source = "user"
        column.levels = levels

    if column.kind == "numeric":
        column.series = column.series.replace([np.inf, -np.inf], np.nan)
        unique = column.series.nunique(dropna=True)
        if 1 < unique <= 10:
            column.warnings.append("数值取值较少；若这些数字是类别编码，请确认后用 categorical 或 ordinal 覆盖类型。")
    if column.kind == "boolean" and not column.levels:
        # Inferred booleans already have a known encoding. A constant native
        # boolean must remain inspectable even though analysis will reject it.
        column.levels = [
            {"value": v, "code": int(_level_key(v).lower() in TRUE_TOKENS)}
            for v in pd.unique(series.dropna())
        ]
        column.levels.sort(key=lambda level: level["code"])
    if column.kind == "categorical":
        column.levels = [{"value": v} for v in pd.unique(series.dropna())]
    column.source_series = series.copy()
    column.conversion_failed = series.notna() & column.series.isna()
    failures = int(column.conversion_failed.sum())
    if column.series.nunique(dropna=True) == 1 and not any("常量" in w for w in column.warnings):
        column.warnings.append("该列只有一个非空取值（常量）。")
    if failures and not any("无法解析" in warning for warning in column.warnings):
        column.warnings.append(f"有 {failures} 个非缺失值无法转换为 {TYPE_LABELS[column.kind]}，分析时排除对应配对行。")
    return column


def prepare_frame_column(df: pd.DataFrame, index: int, *, kind: str = "auto",
                         order: list[Any] | None = None) -> PreparedColumn:
    name = str(df.columns[index])
    column = prepare_column(name, index, df.iloc[:, index], kind=kind, order=order)
    column.original_name = df.attrs["original_headers"][index]
    return column


def prepare_columns(df: pd.DataFrame) -> list[PreparedColumn]:
    return [prepare_frame_column(df, i) for i in range(len(df.columns))]


def prepare_pair(df: pd.DataFrame, p1: PreparedColumn, p2: PreparedColumn) -> dict[str, Any]:
    """Account for one common paired sample before choosing any method."""
    failed = p1.conversion_failed | p2.conversion_failed
    missing = p1.series.isna() | p2.series.isna()
    paired = ~failed & ~missing
    cleaning = {
        **df.attrs["cleaning"],
        "conversion_failure_rows": int(failed.sum()),
        "missing_pair_rows": int((~failed & missing).sum()),
        "n": int(paired.sum()),
        "columns": [{"index": col.index + 1, "name": col.name,
                     "failed_cells": int(col.conversion_failed.sum())} for col in (p1, p2)],
    }
    assert (cleaning["original_rows"] - cleaning["empty_rows"]
            - cleaning["conversion_failure_rows"] - cleaning["missing_pair_rows"] == cleaning["n"])
    for column in (p1, p2):
        if column.kind in {"id", "text", "empty"}:
            raise UserError(f"列 “{column.name}” 是{TYPE_LABELS[column.kind]}，请先核对业务语义或改选列。",
                            cleaning=cleaning)
        if column.series[paired].nunique(dropna=True) < 2:
            raise UserError(f"列 “{column.name}” 在完整配对后不足两个有效取值，无法分析关系。",
                            cleaning=cleaning)
    p1.pair_mask = p2.pair_mask = paired
    return cleaning


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def column_view(df: pd.DataFrame, columns: list[PreparedColumn], *, page: int = 1,
                search: str | None = None, all_columns: bool = False,
                exclude_index: int | None = None) -> tuple[dict, dict]:
    options = [nav.column_option(column.profile()) for column in columns if column.index + 1 != exclude_index]
    if exclude_index is not None and not 1 <= exclude_index <= len(columns):
        raise UserError("排除的字段编号超出范围。", step="needs_columns")
    catalog = nav.page_options(options, page=page, search=search, all_items=all_columns)
    visible = catalog["items"]
    preview = {"columns": [{key: option[key] for key in ("index", "original_name", "display_name")} for option in visible],
               "rows": [[None if pd.isna(value) else nav.display_sample(value) for value in row]
                        for row in df.iloc[:5, [option["index"] - 1 for option in visible]].itertuples(index=False, name=None)],
               "total_rows": len(df), "row_limit": 5, "scope": "当前页字段；前 5 行，示例最多 60 字"}
    return catalog, preview


def cmd_inspect(args: argparse.Namespace) -> dict[str, Any]:
    path = resolve_input(args.input)
    sheets = list_sheets(path) if path.suffix.lower() in EXCEL_SUFFIXES else []
    if sheets and args.sheet is None and args.sheet_index is None:
        catalog = nav.page_options(sheets, page=args.page, search=args.search)
        return {"ok": True, "needs_sheet": True, "step": "needs_sheet", "input_path": str(path),
                "format": "excel", "sheets": catalog["items"], "sheet_catalog": catalog}
    df, meta = load_table(path, args.sheet, args.sheet_index)

    df, warnings_list = normalize_frame(df)
    columns = prepare_columns(df)
    if sheets and next(option for option in sheets if option["name"] == meta["sheet"])["state"] != "visible":
        warnings_list.append("当前明确选择了隐藏工作表。")
    catalog, preview = column_view(df, columns, page=args.page, search=args.search,
                                   all_columns=args.all_columns, exclude_index=args.exclude_index)
    visible = catalog["items"]
    return {
        "ok": True,
        "needs_sheet": False,
        "input_path": str(path),
        "format": meta.get("format"),
        "sheet": meta.get("sheet"),
        "sheets": nav.page_options(sheets)["items"],
        "sheet_index": meta.get("sheet_index"),
        "encoding": meta.get("encoding"),
        "delimiter": meta.get("delimiter"),
        "n_rows": int(len(df)),
        "cleaning": df.attrs["cleaning"],
        "n_columns": int(len(df.columns)),
        "columns": visible,
        "column_catalog": catalog,
        "preview": preview,
        "step": "needs_columns",
        "warnings": warnings_list,
    }


def _resolve_column(columns: list[PreparedColumn], name: str | None, index: int | None,
                    label: str) -> PreparedColumn:
    chosen = nav.resolve_column([nav.column_option(column.profile()) for column in columns],
                                name=name, index=index, label=label)
    return columns[chosen["index"] - 1]


def _make_out_dir(df: pd.DataFrame, p1: PreparedColumn, p2: PreparedColumn, explicit: str | None) -> Path:
    if explicit:
        out = Path(explicit).expanduser()
        if not out.is_absolute():
            out = Path.cwd() / out
        return out
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", f"{p1.name}_x_{p2.name}")[:80].strip("_") or "analysis"
    return Path.cwd() / "data-relationship-output" / stem


def _verify_publication(stage: Path, model: dict, result_text: str) -> None:
    required = {'report.html', 'report.md', 'result.json'}
    required.update(item['path'] for item in model['attachments'])
    required.update(figure['asset_path'] for figure in model['figures'] if figure['status'] == 'available')
    for relative in sorted(required):
        path = stage / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise reports.ReportError(f'发布核验失败：{relative} 缺失或为空。')
    if (stage / 'result.json').read_text(encoding='utf-8') != result_text:
        raise reports.ReportError('发布核验失败：result.json 与本次结果不一致。')
    saved = json.loads(result_text)
    if saved['publication'] != {'status': 'complete', 'run_id': model['report_id']}:
        raise reports.ReportError('发布核验失败：运行标识不一致。')
    marker = 'data-report-id="' + model['report_id'] + '"'
    if marker not in (stage / 'report.html').read_text(encoding='utf-8'):
        raise reports.ReportError('发布核验失败：HTML 不属于本次运行。')


def _publish_analysis(result: dict, chart: dict, extra: dict, base: Path, *, no_chart: bool) -> dict:
    run_id = uuid4().hex
    final = base / ('run-' + run_id)
    model = reports.build_model(result, chart, extra, report_id=run_id)
    try:
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.pending-', dir=base) as pending:
            stage = Path(pending)
            reports.render_figures(model, stage, disabled=no_chart)
            paths = reports.write_reports(model, extra, stage)
            for key in ('report_html_path', 'report_md_path', 'result_path', 'out_dir'):
                result[key] = str(final / Path(paths[key]).relative_to(stage))
            result['chart_paths'] = [str(final / Path(path).relative_to(stage)) for path in paths['chart_paths']]
            result['report_template'] = model['html_template']
            result['figures'] = [{key: value for key, value in figure.items() if key != 'spec'}
                                for figure in model['figures']]
            result['publication'] = {'status': 'complete', 'run_id': run_id}
            result['ok'] = True
            result_text = json.dumps(result, ensure_ascii=False, indent=2, default=json_default, allow_nan=False)
            (stage / 'result.json').write_text(result_text, encoding='utf-8')
            _verify_publication(stage, model, result_text)
            stage.rename(final)
    except (OSError, reports.ReportError) as exc:
        raise UserError(f'本次报告未发布：{exc}') from exc
    return result


def _analyze_columns(df: pd.DataFrame, p1: PreparedColumn, p2: PreparedColumn,
                     args: argparse.Namespace) -> tuple[dict, dict, dict]:
    try:
        analysis, chart, extra = multi.analyze_pair(p1, p2, methods=args.methods, alpha=args.alpha,
                                                   permutations=args.permutations, seed=args.seed)
    except multi.MethodRequestError as exc:
        raise UserError(str(exc)) from exc
    n = len(p1.analysis_series)
    result = {
        "ok": True,
        "col1": p1.profile(), "col2": p2.profile(),
        "n": n, "total_rows": len(df), "missing_pairs": len(df) - n,
        "alpha": args.alpha,
        **analysis,
        "warnings": p1.warnings + p2.warnings + ["Holm 不修复单项检验的假设或时间依赖；不能按最小原始 p 或多数显著决策。"],
        "assumptions": ["观测相互独立；观察性关联不证明因果。",
                        "秩方法使用顺序，不假定有序等级等距；U/KW 仅在附加分布条件下可解释为位置差异。",
                        "各方法的原假设不同，多个一致的相关检验不代表独立重复验证。",
                        "效应量区间为单项区间，未随 Holm 校正，不提供全部方法的同时覆盖保证。"],
    }
    return result, chart, extra


def cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    path = resolve_input(args.input)
    df, meta = load_table(path, args.sheet, args.sheet_index)

    df, warnings_list = normalize_frame(df)
    if meta.get("sheet") and next(option for option in meta["sheets"] if option["name"] == meta["sheet"])["state"] != "visible":
        warnings_list.append("当前明确选择了隐藏工作表。")
    columns = prepare_columns(df)
    p1 = _resolve_column(columns, args.col1, args.col1_index, "第一列")
    p2 = _resolve_column(columns, args.col2, args.col2_index, "第二列")
    if p1.name == p2.name:
        raise UserError("两列不能是同一列，请重新选择。", step="needs_columns")
    selected = []
    for number, column in enumerate((p1, p2), start=1):
        raw_order = getattr(args, f"col{number}_order")
        order = None
        if raw_order is not None:
            try:
                order = json.loads(raw_order)
            except json.JSONDecodeError as exc:
                raise UserError(f"--col{number}-order 必须是合法 JSON 数组：{exc.msg}") from exc
            if not isinstance(order, list):
                raise UserError(f"--col{number}-order 必须是 JSON 数组。")
        try:
            column = prepare_frame_column(df, column.index, kind=getattr(args, f"col{number}_type"), order=order)
        except UserError as exc:
            raise UserError(str(exc), step="needs_semantics", column_index=column.index + 1) from exc
        columns[column.index] = column
        selected.append(column)
    p1, p2 = selected
    if not 0.0 < args.alpha < 1.0:
        raise UserError("--alpha 必须在 0 和 1 之间，例如 0.05。")
    if args.permutations < 0:
        raise UserError("--permutations 不能为负数。")
    if args.seed < 0:
        raise UserError("--seed 必须为非负整数。")

    cleaning = prepare_pair(df, p1, p2)
    result, chart, extra = _analyze_columns(df, p1, p2, args)

    assert result["n"] == cleaning["n"], "analysis changed the common paired sample"
    result["cleaning"] = cleaning
    result["plot"] = plotting.resolve_plan([result["col1"], result["col2"]], args.plot_x)
    result["input_path"] = str(path)
    result["sheet"] = meta.get("sheet")
    result["sheet_index"] = meta.get("sheet_index")
    result["format"] = meta.get("format")
    result["warnings"] = warnings_list + result.get("warnings", [])

    base = _make_out_dir(df, p1, p2, args.out)
    return _publish_analysis(result, chart, extra, base, no_chart=args.no_chart)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_select(args: argparse.Namespace) -> dict[str, Any]:
    import interaction

    try:
        request = json.loads(Path(args.request).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserError(f"无法读取选择请求：{exc}") from exc
    return interaction.advance(request)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="列出表格的工作表/列类型，并分析两列之间的关系。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    select = sub.add_parser("select", help="推进一次文件/sheet/字段选择，ready 后返回分析参数")
    select.add_argument("--request", required=True, help="包含 state/action/view/host 的 JSON 请求文件")
    select.add_argument("--debug", action="store_true", help="出错时输出 traceback")
    select.set_defaults(func=cmd_select)

    inspect = sub.add_parser("inspect", help="列出工作表（Excel）或列名与类型")
    inspect.add_argument("--input", required=True, help="CSV/TSV/XLSX/XLSM 文件路径")
    inspect.add_argument("--sheet", help="Excel 工作表名称；不指定则返回 needs_sheet")
    inspect.add_argument("--sheet-index", type=int, help="工作簿中的 1-based 编号")
    inspect.add_argument("--page", type=int, default=1, help="目录页码，每页 20 项")
    inspect.add_argument("--search", help="按名称查找，保留原始编号")
    inspect.add_argument("--all-columns", action="store_true", help="显示完整字段目录")
    inspect.add_argument("--exclude-index", type=int, help="第二次单选时排除第一列编号")
    inspect.add_argument("--debug", action="store_true", help="出错时输出 traceback")
    inspect.set_defaults(func=cmd_inspect)

    analyze = sub.add_parser("analyze", help="分析两列的关系并生成报告")
    analyze.add_argument("--input", required=True, help="CSV/TSV/XLSX/XLSM 文件路径")
    analyze.add_argument("--sheet", help="Excel 工作表名称")
    analyze.add_argument("--sheet-index", type=int, help="工作簿中的 1-based 编号")
    analyze.add_argument("--col1", help="第一列的列名")
    analyze.add_argument("--col2", help="第二列的列名")
    analyze.add_argument("--col1-index", type=int, help="第一列的 1-based 序号（列名重复时使用）")
    analyze.add_argument("--col2-index", type=int, help="第二列的 1-based 序号（列名重复时使用）")
    for number in (1, 2):
        analyze.add_argument(f"--col{number}-type", default="auto",
                             choices=["auto", "numeric", "boolean", "categorical", "ordinal", "datetime"],
                             help=f"第 {number} 列的业务类型，默认 auto；显式类型覆盖推断")
        analyze.add_argument(f"--col{number}-order",
                             help=f"第 {number} 列 ordinal 的完整 JSON 水平顺序数组")
    analyze.add_argument("--out", help="输出父目录；每次成功结果发布到其中独立的 run-<运行标识>/ 目录")
    analyze.add_argument("--alpha", type=float, default=0.05, help="显著性水平，默认 0.05")
    analyze.add_argument("--methods", default="auto", help="auto 或逗号分隔的方法标识；默认执行类型矩阵的候选")
    analyze.add_argument("--seed", type=int, default=20241102, help="置换随机种子，默认 20241102")
    analyze.add_argument("--permutations", type=int, default=2000,
                         help="小样本秩检验及稀疏列联表的置换次数，默认 2000；0 表示禁用，需要校准者仅描述")
    analyze.add_argument("--plot-x", choices=plotting.PLOT_X_CHOICES, default="auto",
                         help="绘图横轴字段槽位；默认按类型分配，另一字段为纵轴，不改变统计输入顺序")
    analyze.add_argument("--no-chart", action="store_true", help="不生成图表")
    analyze.add_argument("--debug", action="store_true", help="出错时输出 traceback")
    analyze.set_defaults(func=cmd_analyze)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.func(args)
        return emit(payload, 0 if payload["ok"] else 1)
    except UserError as exc:
        payload = {"ok": False, "error": str(exc)}
        payload.update(exc.payload)
        return emit(payload, 1)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if getattr(args, "debug", False):
            payload["traceback"] = traceback.format_exc()
        return emit(payload, 1)


if __name__ == "__main__":
    raise SystemExit(main())
