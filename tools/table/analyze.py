"""analyze_table — fixed pandas ops for CSV/TSV/XLSX (AUTO_ALLOW).

No eval, no query strings as code, no spreadsheet formulas executed.
Outside files are wrapped as untrusted data (same markers as read_file).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from security.gate import Tier, check_permission
from tools.filesystem.fs_tools import resolve_fs_path
from tools.filesystem.untrusted_file import is_trusted_local_path, wrap_untrusted_file_text

MAX_FILES = 20
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_LIMIT = 200
ALLOWED_EXTS = {".csv", ".tsv", ".xlsx"}
FILTER_OPS = {"==", "!=", ">", ">=", "<", "<=", "contains"}
AGG_FUNCS = {"sum", "mean", "min", "max", "count", "median"}


class AnalyzeTableError(ValueError):
    """User-facing validation / IO error for analyze_table."""


def _enabled() -> bool:
    from config import settings

    return bool(getattr(settings, "FEATURE_ANALYZE_TABLE", True))


def _load_one(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise AnalyzeTableError(f"Not a file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AnalyzeTableError(f"Cannot stat {path}: {exc}") from exc
    if size > MAX_FILE_BYTES:
        raise AnalyzeTableError(
            f"{path.name} is {size} bytes; max is {MAX_FILE_BYTES} (50 MB)."
        )
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise AnalyzeTableError(
            f"Unsupported type {ext!r} for {path.name}; "
            f"allowed: {sorted(ALLOWED_EXTS)}"
        )
    try:
        if ext == ".csv":
            # Keep formula-looking strings as plain text (dtype=str for objects).
            return pd.read_csv(path, dtype=None)
        if ext == ".tsv":
            return pd.read_csv(path, sep="\t", dtype=None)
        # xlsx: first sheet only; do not evaluate formulas (data_only default).
        return pd.read_excel(path, engine="openpyxl")
    except AnalyzeTableError:
        raise
    except Exception as exc:
        raise AnalyzeTableError(f"Failed to read {path.name}: {exc}") from exc


def _validate_columns(df: pd.DataFrame, names: list[str], *, where: str) -> None:
    cols = list(df.columns.astype(str))
    missing = [c for c in names if c not in cols]
    if missing:
        raise AnalyzeTableError(
            f"Unknown column(s) in {where}: {missing}. "
            f"Available columns: {cols}"
        )


def _apply_filter(df: pd.DataFrame, filt: dict[str, Any]) -> pd.DataFrame:
    if not filt:
        return df
    col = filt.get("column")
    op = filt.get("op")
    if col is None or op is None:
        raise AnalyzeTableError(
            "filter requires keys: column, op, value "
            f"(ops: {sorted(FILTER_OPS)})"
        )
    col = str(col)
    op = str(op)
    if op not in FILTER_OPS:
        raise AnalyzeTableError(
            f"Unsupported filter op {op!r}; allowed: {sorted(FILTER_OPS)}"
        )
    _validate_columns(df, [col], where="filter")
    value = filt.get("value")
    series = df[col]
    try:
        if op == "contains":
            mask = series.astype(str).str.contains(str(value), na=False, regex=False)
        elif op == "==":
            mask = series == value
            # Also try numeric equality when both convert.
            try:
                mask = mask | (pd.to_numeric(series, errors="coerce") == float(value))
            except (TypeError, ValueError):
                pass
        elif op == "!=":
            mask = series != value
        else:
            num = pd.to_numeric(series, errors="coerce")
            try:
                rhs = float(value)
            except (TypeError, ValueError) as exc:
                raise AnalyzeTableError(
                    f"filter value for {op} must be numeric; got {value!r}"
                ) from exc
            if op == ">":
                mask = num > rhs
            elif op == ">=":
                mask = num >= rhs
            elif op == "<":
                mask = num < rhs
            else:
                mask = num <= rhs
    except AnalyzeTableError:
        raise
    except Exception as exc:
        raise AnalyzeTableError(f"filter failed: {exc}") from exc
    return df.loc[mask].copy()


def _apply_aggregate(
    df: pd.DataFrame,
    group_by: list[str],
    aggregate: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not aggregate:
        return df, {}
    for col, fn in aggregate.items():
        if fn not in AGG_FUNCS:
            raise AnalyzeTableError(
                f"Unsupported aggregate {fn!r} for {col}; "
                f"allowed: {sorted(AGG_FUNCS)}"
            )
    _validate_columns(df, list(aggregate.keys()), where="aggregate")
    if group_by:
        _validate_columns(df, group_by, where="group_by")
        # pandas named aggregation
        named = {f"{c}_{fn}": (c, fn) for c, fn in aggregate.items()}
        out = df.groupby(group_by, dropna=False).agg(**named).reset_index()
    else:
        # Single-row totals
        row: dict[str, Any] = {}
        for c, fn in aggregate.items():
            series = df[c]
            if fn == "count":
                row[f"{c}_{fn}"] = int(series.count())
            elif fn == "sum":
                row[f"{c}_{fn}"] = float(pd.to_numeric(series, errors="coerce").sum())
            elif fn == "mean":
                row[f"{c}_{fn}"] = float(pd.to_numeric(series, errors="coerce").mean())
            elif fn == "min":
                row[f"{c}_{fn}"] = pd.to_numeric(series, errors="coerce").min()
            elif fn == "max":
                row[f"{c}_{fn}"] = pd.to_numeric(series, errors="coerce").max()
            elif fn == "median":
                row[f"{c}_{fn}"] = float(
                    pd.to_numeric(series, errors="coerce").median()
                )
        out = pd.DataFrame([row])
    totals: dict[str, Any] = {}
    for c, fn in aggregate.items():
        key = f"{c}_{fn}"
        if key in out.columns and len(out) == 1 and not group_by:
            val = out.iloc[0][key]
            totals[key] = _json_number(val)
        elif not group_by:
            pass
        else:
            # Also provide ungrouped total for convenience
            series = df[c]
            if fn == "count":
                totals[f"all_{c}_{fn}"] = int(series.count())
            elif fn in ("sum", "mean", "median"):
                num = pd.to_numeric(series, errors="coerce")
                totals[f"all_{c}_{fn}"] = _json_number(getattr(num, fn)())
            elif fn == "min":
                totals[f"all_{c}_{fn}"] = _json_number(
                    pd.to_numeric(series, errors="coerce").min()
                )
            elif fn == "max":
                totals[f"all_{c}_{fn}"] = _json_number(
                    pd.to_numeric(series, errors="coerce").max()
                )
    return out, totals


def _json_number(val: Any) -> Any:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int,)):
        return int(val)
    try:
        f = float(val)
        if f == int(f) and abs(f) < 1e15:
            return int(f)
        return f
    except (TypeError, ValueError):
        return str(val)


def _format_cell(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, (int,)):
        return str(int(val))
    if isinstance(val, float):
        # Full precision in text; also show rounded for readability.
        full = repr(val) if abs(val) < 1e-4 or abs(val) >= 1e12 else f"{val:.12g}"
        rounded = f"{val:.4g}"
        if full != rounded and "." in full:
            return f"{full} (~{rounded})"
        return full
    return str(val)


def _to_markdown(df: pd.DataFrame, limit: int) -> str:
    view = df.head(limit)
    cols = [str(c) for c in view.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in view.iterrows():
        cells = [_format_cell(row[c]).replace("|", "\\|") for c in view.columns]
        lines.append("| " + " | ".join(cells) + " |")
    if len(df) > limit:
        lines.append(f"\n_… {len(df) - limit} more rows omitted (limit={limit})._")
    return "\n".join(lines)


def _analyze_table_impl(
    paths: list[str],
    combine: bool = False,
    filter: Optional[dict[str, Any]] = None,  # noqa: A002 — tool schema name
    group_by: Optional[list[str]] = None,
    aggregate: Optional[dict[str, str]] = None,
    sort_by: Optional[str] = None,
    descending: bool = False,
    limit: int = 50,
) -> str:
    if not paths or not isinstance(paths, list):
        raise AnalyzeTableError("paths must be a non-empty list of file paths.")
    if len(paths) > MAX_FILES:
        raise AnalyzeTableError(f"Too many files ({len(paths)}); max is {MAX_FILES}.")
    limit = int(limit or 50)
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    resolved: list[Path] = []
    frames: list[pd.DataFrame] = []
    any_untrusted = False
    for raw in paths:
        p = resolve_fs_path(str(raw))
        resolved.append(p)
        if not is_trusted_local_path(p):
            any_untrusted = True
        frames.append(_load_one(p))

    if combine or len(frames) > 1:
        # Align columns by name; missing → NaN
        df = pd.concat(frames, ignore_index=True, sort=False)
    else:
        df = frames[0]

    # Formula-looking cells stay plain text (never executed).
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(
                lambda v: (
                    v
                    if v is None or (isinstance(v, float) and pd.isna(v))
                    else (str(v) if str(v).startswith("=") else v)
                )
            )

    df = _apply_filter(df, filter or {})
    group_by = list(group_by or [])
    aggregate = dict(aggregate or {})
    df, totals = _apply_aggregate(df, group_by, aggregate)

    if sort_by:
        sort_by = str(sort_by)
        _validate_columns(df, [sort_by], where="sort_by")
        df = df.sort_values(by=sort_by, ascending=not descending, kind="mergesort")

    columns = [str(c) for c in df.columns]
    records = []
    for _, row in df.head(limit).iterrows():
        rec = {}
        for c in df.columns:
            rec[str(c)] = _json_number(row[c])
        records.append(rec)

    payload = {
        "files": [str(p) for p in resolved],
        "row_count": int(len(df)),
        "columns": columns,
        "totals": totals,
        "rows": records,
    }
    md = _to_markdown(df, limit)
    body = (
        "## Table result\n\n"
        f"{md}\n\n"
        "## Exact numbers (JSON)\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False, default=str)}\n```\n"
    )
    if any_untrusted:
        return wrap_untrusted_file_text(body)
    return body


def analyze_table(
    paths: list[str],
    combine: bool = False,
    filter: Optional[dict[str, Any]] = None,  # noqa: A002 — tool schema name
    group_by: Optional[list[str]] = None,
    aggregate: Optional[dict[str, str]] = None,
    sort_by: Optional[str] = None,
    descending: bool = False,
    limit: int = 50,
) -> str:
    """Analyze CSV/TSV/XLSX with a fixed set of pandas operations.

    Example call:
      analyze_table(
        paths=["C:/data/jan.csv", "C:/data/feb.csv"],
        combine=True,
        group_by=["month"],
        aggregate={"revenue": "sum"},
        sort_by="revenue_sum",
        descending=True,
        limit=12,
      )
    Use this for sums, averages, best/worst, combining spreadsheets.
    Never do arithmetic over raw file text.
    """
    if not _enabled():
        return (
            "analyze_table is disabled "
            "(FEATURE_ANALYZE_TABLE=off after Round 6 measurement)."
        )
    check_permission(
        action="analyze_table",
        tier=Tier.AUTO_ALLOW,
        description=f"Analyze table(s): {len(paths or [])} file(s)",
    )
    try:
        return _analyze_table_impl(
            paths=paths,
            combine=combine,
            filter=filter,
            group_by=group_by,
            aggregate=aggregate,
            sort_by=sort_by,
            descending=descending,
            limit=limit,
        )
    except AnalyzeTableError as exc:
        return f"Error: {exc}"
