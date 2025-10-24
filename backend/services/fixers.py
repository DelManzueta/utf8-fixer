from typing import List, Dict, Any, Set
import pandas as pd
from ftfy import fix_text
from charset_normalizer import from_bytes

MOJI_REPLACEMENTS = ("Ã¡","Ã©","Ã­","Ã³","Ãº","Ã±","MÃ©","BogotÃ¡","�")

def _fix_cell(s: str) -> str:
    if s is None or s == "":
        return s
    t = str(s)
    a = fix_text(t)
    if any(m in t for m in MOJI_REPLACEMENTS) and a == t:
        # heuristic cp1252/latin-1 re-interpretation
        b = t.encode("latin-1", errors="ignore")
        best = from_bytes(b).best()
        if best:
            a = best.stripped()
    return a

def scan_and_propose_fixes_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    issues = []
    _id = 0
    for r in range(len(df)):
        for c, col in enumerate(df.columns):
            v = df.iloc[r, c]
            if isinstance(v, str):
                fixed = _fix_cell(v)
                if fixed != v:
                    issues.append({
                        "id": _id,
                        "row": r,
                        "col": int(c),
                        "column": str(col),
                        "before": v,
                        "after": fixed
                    })
                    _id += 1
    return issues

def apply_fixes_df(df: pd.DataFrame, issues: List[Dict[str, Any]], selected_ids: Set[int]) -> pd.DataFrame:
    out = df.copy()
    for it in issues:
        if it["id"] in selected_ids:
            out.iat[it["row"], it["col"]] = it["after"]
    return out

def write_reports(fixed_df: pd.DataFrame, issues: List[Dict[str, Any]], corrected_path, issues_path, export="csv"):
    if export == "xlsx":
        with pd.ExcelWriter(corrected_path, engine="openpyxl") as xw:
            fixed_df.to_excel(xw, index=False, sheet_name="fixed")
        issues_df = pd.DataFrame(issues)
        with pd.ExcelWriter(issues_path, engine="openpyxl") as xw:
            issues_df.to_excel(xw, index=False, sheet_name="issues")
    else:
        fixed_df.to_csv(corrected_path, index=False, encoding="utf-8")
        pd.DataFrame(issues).to_csv(issues_path, index=False, encoding="utf-8")
