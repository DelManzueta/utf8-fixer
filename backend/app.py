from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional, Dict
from pathlib import Path
import shutil, uuid, json, os
import pandas as pd

from services.fixers import scan_and_propose_fixes_df, apply_fixes_df, write_reports
from services.compare import compare_tabular_to_json
from utils.encoding import within_size_or_400

# Root & temp workspace
ROOT = Path(os.getenv("UTF8_FIXER_ROOT", Path(__file__).resolve().parent.parent)).resolve()
TMP = (ROOT / "tmp")
TMP.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = 2 * 1024 * 1024  # 2MB

app = FastAPI(title="UTF-8 Fixer")

# Static frontend
frontend_dir = ROOT / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)
app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="ui")


@app.get("/", response_class=HTMLResponse)
def home():
    """Serve UI."""
    index = frontend_dir / "index.html"
    if not index.exists():
        raise HTTPException(404, "frontend/index.html not found")
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.post("/api/upload")
async def upload(
    files: List[UploadFile] = File(...),
    reference_json: Optional[UploadFile] = File(None)
):
    """Accept CSV/XLSX (<=2MB each) and optional reference JSON."""
    session_id = str(uuid.uuid4())
    sess_dir = (TMP / session_id)
    sess_dir.mkdir(parents=True, exist_ok=True)

    saved: List[Dict[str, str]] = []
    for uf in files:
        within_size_or_400(uf, max_bytes=MAX_UPLOAD_SIZE)
        ext = Path(uf.filename).suffix.lower()
        if ext not in (".csv", ".xlsx"):
            raise HTTPException(400, f"Unsupported file type: {ext}. Use .csv or .xlsx")
        dst = sess_dir / uf.filename
        with dst.open("wb") as w:
            shutil.copyfileobj(uf.file, w)
        saved.append({"filename": uf.filename, "path": str(dst)})

    ref_path = None
    if reference_json:
        within_size_or_400(reference_json, max_bytes=MAX_UPLOAD_SIZE)
        if not reference_json.filename.lower().endswith(".json"):
            raise HTTPException(400, "Reference must be .json")
        ref_path = sess_dir / reference_json.filename
        with ref_path.open("wb") as w:
            shutil.copyfileobj(reference_json.file, w)

    return {
        "session": session_id,
        "files": saved,
        "reference": str(ref_path) if ref_path else None
    }


@app.post("/api/scan")
def scan(session: str = Form(...), filename: str = Form(...)):
    """Scan one uploaded file and propose fixes."""
    sess_dir = (TMP / session)
    fpath = (sess_dir / filename)
    if not fpath.exists():
        raise HTTPException(404, "File not found")

    if fpath.suffix.lower() == ".xlsx":
        df = pd.read_excel(fpath)
    else:
        df = pd.read_csv(fpath, dtype=str, keep_default_na=False)

    issues = scan_and_propose_fixes_df(df)
    return {"issues": issues, "rows": int(len(df)), "cols": int(len(df.columns))}


@app.post("/api/apply")
def apply(
    session: str = Form(...),
    filename: str = Form(...),
    change_all: bool = Form(False),
    apply_ids: Optional[str] = Form(None),
    export: str = Form("csv")
):
    """
    Apply fixes to selected issues (or all), and write corrected + issues report.
    export: 'csv' or 'xlsx' (controls output formats for both files)
    """
    sess_dir = (TMP / session)
    fpath = (sess_dir / filename)
    if not fpath.exists():
        raise HTTPException(404, "File not found")

    if fpath.suffix.lower() == ".xlsx":
        df = pd.read_excel(fpath)
    else:
        df = pd.read_csv(fpath, dtype=str, keep_default_na=False)

    issues = scan_and_propose_fixes_df(df)

    def get_selected_ids(_issues, _change_all, _apply_ids):
        if not _change_all and _apply_ids:
            return set(json.loads(_apply_ids))
        return {i["id"] for i in _issues}

    selected = get_selected_ids(issues, change_all, apply_ids)
    fixed_df = apply_fixes_df(df, issues, selected)

    corrected_name = f"{fpath.stem}.utf8.fixed{(fpath.suffix if export=='xlsx' else '.csv')}"
    issues_name = f"{fpath.stem}.issues{('.xlsx' if export=='xlsx' else '.csv')}"

    corrected_path = (sess_dir / corrected_name)
    issues_path = (sess_dir / issues_name)
    write_reports(fixed_df, issues, corrected_path, issues_path, export=export)

    return {
        "corrected": corrected_name,
        "issues_report": issues_name,
        "rows": int(len(fixed_df)),
        "cols": int(len(fixed_df.columns))
    }


@app.get("/api/download/{session}/{name}")
def download(session: str, name: str):
    """Download a generated artifact from the session folder."""
    sess_dir = (TMP / session).resolve()
    path = (sess_dir / name).resolve()
    if not path.exists() or sess_dir not in path.parents:
        raise HTTPException(404, "Not found")
    return FileResponse(path)


@app.post("/api/compare")
def compare(
    session: str = Form(...),
    filename: str = Form(...),
    reference: str = Form(...),
    export: str = Form("csv")
):
    """
    Compare a tabular file to a reference JSON and emit a comparison report.
    """
    sess_dir = (TMP / session).resolve()
    fpath = (sess_dir / filename).resolve()
    jpath = Path(reference).resolve()

    # Ensure both files exist and belong to the same session directory
    if not fpath.exists() or not jpath.exists() or (sess_dir not in fpath.parents) or (sess_dir not in jpath.parents):
        raise HTTPException(404, "File or reference not found")

    if fpath.suffix.lower() == ".xlsx":
        df = pd.read_excel(fpath)
    else:
        df = pd.read_csv(fpath, dtype=str, keep_default_na=False)

    ref_obj = json.loads(jpath.read_text(encoding="utf-8"))

    report_df, meta = compare_tabular_to_json(df, ref_obj)

    out_name = f"{Path(filename).stem}.compare{('.xlsx' if export=='xlsx' else '.csv')}"
    out_path = (sess_dir / out_name)

    if export == "xlsx":
        with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
            report_df.to_excel(xw, index=False, sheet_name="comparison")
    else:
        report_df.to_csv(out_path, index=False, encoding="utf-8")

    return {"report": out_name, "meta": meta}
