from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
import shutil, io, uuid, json, os
import pandas as pd

from services.fixers import scan_and_propose_fixes_df, apply_fixes_df, write_reports
from services.compare import compare_tabular_to_json
from utils.encoding import within_size_or_400

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / "tmp"
TMP.mkdir(exist_ok=True)

app = FastAPI(title="UTF-8 Fixer")
app.mount("/ui", StaticFiles(directory=ROOT / "frontend", html=True), name="ui")

@app.get("/", response_class=HTMLResponse)
def home():
    # Redirect to UI index
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), reference_json: Optional[UploadFile] = File(None)):
    session_id = str(uuid.uuid4())
    sess_dir = TMP / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Dict[str, str]] = []
    for uf in files:
        within_size_or_400(uf, max_bytes=2 * 1024 * 1024)  # 2MB
        ext = Path(uf.filename).suffix.lower()
        if ext not in [".csv", ".xlsx"]:
            raise HTTPException(400, f"Unsupported file type: {ext}. Use .csv or .xlsx")
        dst = sess_dir / uf.filename
        with dst.open("wb") as w:
            shutil.copyfileobj(uf.file, w)
        saved.append({"filename": uf.filename, "path": str(dst)})

    ref_path = None
    if reference_json:
        within_size_or_400(reference_json, max_bytes=2 * 1024 * 1024)
        if not reference_json.filename.lower().endswith(".json"):
            raise HTTPException(400, "Reference must be .json")
        ref_path = sess_dir / reference_json.filename
        with ref_path.open("wb") as w:
            shutil.copyfileobj(reference_json.file, w)

    return {"session": session_id, "files": saved, "reference": str(ref_path) if ref_path else None}

@app.post("/api/scan")
def scan(session: str = Form(...), filename: str = Form(...)):
    sess_dir = TMP / session
    fpath = sess_dir / filename
    if not fpath.exists():
        raise HTTPException(404, "File not found")
    # Load CSV/XLSX into DataFrame
    df = pd.read_excel(fpath) if fpath.suffix.lower() == ".xlsx" else pd.read_csv(fpath, dtype=str, keep_default_na=False)
    issues = scan_and_propose_fixes_df(df)
    return {"issues": issues, "rows": len(df), "cols": len(df.columns)}

@app.post("/api/apply")
def apply(session: str = Form(...), filename: str = Form(...), change_all: bool = Form(True), apply_ids: str = Form(""), export: str = Form("csv")):
    sess_dir = TMP / session
    fpath = sess_dir / filename
    if not fpath.exists():
        raise HTTPException(404, "File not found")

    df = pd.read_excel(fpath) if fpath.suffix.lower() == ".xlsx" else pd.read_csv(fpath, dtype=str, keep_default_na=False)
    issues = scan_and_propose_fixes_df(df)

    selected = set(json.loads(apply_ids)) if (not change_all and apply_ids) else {i["id"] for i in issues}
    fixed_df = apply_fixes_df(df, issues, selected)

    corrected_name = f"{fpath.stem}.utf8.fixed{fpath.suffix if export=='xlsx' else '.csv'}"
    issues_name = f"{fpath.stem}.issues{'.xlsx' if export=='xlsx' else '.csv'}"

    corrected_path = sess_dir / corrected_name
    issues_path = sess_dir / issues_name
    write_reports(fixed_df, issues, corrected_path, issues_path, export=export)

    return {"corrected": corrected_name, "issues": issues_name}

@app.get("/api/download/{session}/{name}")
def download(session: str, name: str):
    path = TMP / session / name
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path)

@app.post("/api/compare")
def compare(session: str = Form(...), filename: str = Form(...), reference: str = Form(...), export: str = Form("csv")):
    sess_dir = TMP / session
    fpath = sess_dir / filename
    jpath = Path(reference)
    if not fpath.exists() or not jpath.exists():
        raise HTTPException(404, "File or reference not found")

    df = pd.read_excel(fpath) if fpath.suffix.lower() == ".xlsx" else pd.read_csv(fpath, dtype=str, keep_default_na=False)
    ref_obj = json.loads(jpath.read_text(encoding="utf-8"))

    report_df, meta = compare_tabular_to_json(df, ref_obj)

    out_name = f"{Path(filename).stem}.compare{'.xlsx' if export=='xlsx' else '.csv'}"
    out_path = sess_dir / out_name
    if export == "xlsx":
        with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
            report_df.to_excel(xw, index=False, sheet_name="comparison")
    else:
        report_df.to_csv(out_path, index=False, encoding="utf-8")

    return {"report": out_name, "meta": meta}
