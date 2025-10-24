from typing import Tuple, Dict, Any
import pandas as pd
import unicodedata as ud
import re, json

def _norm(s: str) -> str:
    if s is None:
        return ""
    x = ud.normalize("NFKD", str(s))
    x = "".join(ch for ch in x if not ud.combining(ch))
    return re.sub(r"\s+", " ", x).strip().lower()

def _collect_json_fields(obj, base=""):
    fields = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            fields.add(base + k)
            fields |= _collect_json_fields(v, base + k + ".")
    elif isinstance(obj, list):
        if obj:
            fields |= _collect_json_fields(obj[0], base)
    return fields

def compare_tabular_to_json(df: pd.DataFrame, ref_json: Any) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    cols = list(df.columns)
    norm_cols = {_norm(c): c for c in cols}
    json_fields = _collect_json_fields(ref_json)
    norm_json = {_norm(f): f for f in json_fields}

    missing = [norm_json[k] for k in norm_json.keys() if k not in norm_cols]
    extra = [norm_cols[k] for k in norm_cols.keys() if k not in norm_json]

    # sample mismatches: show first 5 rows of any column containing apparent mojibake
    samples = []
    for c in cols:
        series = df[c].astype(str)
        bad = series[series.str.contains(r"(Ã.|�)", regex=True, na=False)].head(5)
        for i, v in bad.items():
            samples.append({"column": c, "row": int(i), "value": v})

    report_rows = []
    for m in missing:
        report_rows.append({"type": "missing_field_in_table", "name": m})
    for e in extra:
        report_rows.append({"type": "extra_column_in_table", "name": e})
    for s in samples:
        report_rows.append({"type": "sample_mojibake", **s})

    return pd.DataFrame(report_rows), {
        "missing_count": len(missing),
        "extra_count": len(extra),
        "sample_count": len(samples)
    }
