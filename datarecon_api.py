"""Local Equaliser workspace API and production frontend entry point."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ValidationError

import datarecon as core


app = FastAPI(title="Equaliser")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
lock = Lock()
sessions = OrderedDict()
COOKIE = "equaliser_workspace"


class Input(BaseModel):
    connection: str = ""
    password: str = ""
    sql: str = ""
    delimiter: str = Field(default=",", min_length=1, max_length=3)
    max_rows: int = Field(default=0, ge=0)


class Connection(BaseModel):
    database_type: str
    host: str = ""
    port: int = Field(default=0, ge=0, le=65535)
    database: str = Field(min_length=1)
    username: str = ""
    password: str = ""
    remember: bool = False


class Rules(BaseModel):
    r_keys: list[str] = Field(default_factory=list)
    r_ignore: list[str] = Field(default_factory=list)
    r_agg: list[str] = Field(default_factory=list)
    r_group: list[str] = Field(default_factory=list)
    r_trim: bool = True
    r_empty: bool = True
    r_case: bool = False
    r_tol: float = Field(default=0, ge=0)
    r_fast: bool = False
    r_matched: bool = False
    r_nulltok: str = core.DEFAULT_NULL_TOKENS
    r_markers: str = core.DEFAULT_MARKERS
    r_cnt_abs: int = Field(default=0, ge=0)
    r_cnt_pct: float = Field(default=0, ge=0)


@app.get("/api/profiles")
def profiles():
    with lock:
        config = core.load_config()
    config["connections"] = {
        name: {**{k: v for k, v in saved.items() if k != "password_enc"},
               "remember": bool(saved.get("password_enc"))}
        for name, saved in config["connections"].items()
    }
    return config


@app.post("/api/connections/{name:path}")
def connection(name: str, spec: Connection, test: bool = False):
    if spec.database_type not in core.DB_DEFAULTS or not name.strip():
        raise HTTPException(422, "Choose a name and a supported database type.")
    with lock:
        config = core.load_config()
        saved = config["connections"].get(name, {})
        values = spec.model_dump(exclude={"password", "remember"})
        if not test:
            if spec.remember:
                encrypted = core.encrypt_password(spec.password) if spec.password else saved.get("password_enc")
                if encrypted:
                    values["password_enc"] = encrypted
            config["connections"][name] = values
            core.save_config(config)
            return {"saved": True}
    try:
        engine = core.make_engine(values, spec.password or core.decrypt_password(saved.get("password_enc")))
        try:
            with engine.connect() as db:
                db.exec_driver_sql("SELECT 1")
        finally:
            engine.dispose()
    except Exception as exc:
        raise HTTPException(400, f"Connection test failed: {exc}") from exc
    return {"connected": True}


@app.delete("/api/connections/{name:path}")
def delete_connection(name: str):
    with lock:
        config = core.load_config()
        config["connections"].pop(name, None)
        core.save_config(config)
    return {"deleted": True}


@app.put("/api/queries/{name:path}")
def save_query(name: str, sql: str = Form(...)):
    with lock:
        config = core.load_config()
        config["queries"][name] = sql
        core.save_config(config)
    return {"saved": True}


@app.put("/api/rules/{name:path}")
def save_rules(name: str, rules: Rules):
    with lock:
        config = core.load_config()
        config["rules"][name] = rules.model_dump()
        core.save_config(config)
    return {"saved": True}


def table(frame, limit=core.DISPLAY_ROWS):
    return {"columns": list(frame.columns), "total": len(frame),
            "rows": json.loads(frame.head(limit).to_json(orient="values", date_format="iso", default_handler=str))}


def load_side(spec, upload, config):
    if upload is not None:
        digest = hashlib.file_digest(upload.file, "sha256").hexdigest()
        upload.file.seek(0)
        frame = core.read_file(upload.file, spec.delimiter, filename=upload.filename or "")
        info = {"input_type": "File", "name": upload.filename, "file_size_bytes": upload.size,
                "sha256": digest, "delimiter": spec.delimiter}
    else:
        saved = config["connections"].get(spec.connection)
        if saved is None:
            raise ValueError("Select a saved connection or choose a file.")
        frame = core.run_query(saved, spec.password or core.decrypt_password(saved.get("password_enc")),
                               spec.sql, spec.max_rows)
        sql = spec.sql.strip().rstrip(";").strip()
        info = {"input_type": "Database query", "name": f"{spec.connection} query",
                "connection": spec.connection, "sql": sql,
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(), "max_rows": spec.max_rows}
        info.update({key: saved.get(key) for key in ("database_type", "host", "port", "database", "username")})
    info.update(rows=len(frame), columns=len(frame.columns),
                loaded_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    return frame, info


@app.post("/api/inputs")
def inputs(response: Response, request: Request, source: str = Form(...), target: str = Form(...),
           source_file: UploadFile | None = File(None), target_file: UploadFile | None = File(None)):
    try:
        with lock:
            config = core.load_config()
        src, src_info = load_side(Input.model_validate_json(source), source_file, config)
        tgt, tgt_info = load_side(Input.model_validate_json(target), target_file, config)
    except ValidationError as exc:
        raise HTTPException(422, "Check your input settings.") from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    session_id = uuid4().hex
    with lock:
        sessions.pop(request.cookies.get(COOKIE), None)
        sessions[session_id] = {"source": src, "target": tgt, "info": (src_info, tgt_info)}
        while len(sessions) > 4:
            sessions.popitem(last=False)
    response.set_cookie(COOKIE, session_id, httponly=True, samesite="strict")
    return {"source": table(src, 10), "target": table(tgt, 10)}


def workspace(request):
    with lock:
        session = sessions.get(request.cookies.get(COOKIE))
    if session is None:
        raise HTTPException(409, "Load source and target data first.")
    return session


TABLES = {
    "checks": "Checks", "insights": "Why do rows differ?", "columns": "Column profile",
    "nulls": "Null / NA details", "dtypes": "Data types", "aggregations": "Aggregations",
    "schema": "Schema", "groups": "Row counts by group", "distribution": "Value distribution differences",
    "full": "Full data comparison", "dup_source": "Duplicate records in source",
    "dup_target": "Duplicate records in target", "mismatches": "Value mismatches",
    "only_in_source": "Rows only in source", "only_in_target": "Rows only in target",
}


@app.post("/api/compare")
def compare(request: Request, rules: Rules):
    session = workspace(request)
    src_info, tgt_info = session["info"]
    hashes = tuple(i.get("sha256") for i in (src_info, tgt_info))
    try:
        result = core.compare(
            session["source"], session["target"], rules.r_keys, rules.r_ignore, rules.r_trim,
            rules.r_empty, rules.r_case, rules.r_tol, agg_cols=rules.r_agg,
            markers=rules.r_markers.split(","), count_tol_abs=rules.r_cnt_abs,
            count_tol_pct=rules.r_cnt_pct, group_by=rules.r_group, file_hashes=hashes if all(hashes) else None,
            fast=rules.r_fast, include_matched=rules.r_matched, null_tokens=rules.r_nulltok.split(","),
            evidence=core.new_evidence(src_info, tgt_info, rules.model_dump()),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session["result"] = result
    return {
        "passed": result["passed"], "mode": result["mode"], "seconds": result["seconds"],
        "counts": {key: result[key] for key in ("source_rows", "target_rows", "total_mismatch_cells", "full_counts")},
        "tables": [{"key": key, "name": name, "total": len(result[key])} for key, name in TABLES.items()]
        + [{"key": "evidence", "name": "Run information", "total": None}],
    }


@app.get("/api/results/{key}")
def result_table(request: Request, key: str, status: str = ""):
    result = workspace(request).get("result")
    if result is None:
        raise HTTPException(409, "Run a comparison first.")
    if key == "evidence":
        return table(core.evidence_frame(result))
    if key not in TABLES:
        raise HTTPException(404, "Unknown result table.")
    frame = result[key]
    if key == "full" and status:
        frame = frame[frame["status"] == status]
    return table(frame)


REPORTS = {
    "xlsx": (core.build_xlsx, "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "csv": (core.build_csv_zip, "zip", "application/zip"),
    "json": (core.build_json, "json", "application/json"),
    "html": (core.build_html, "html", "text/html"),
}


@app.get("/api/reports/{kind}")
def report(kind: str, request: Request):
    result = workspace(request).get("result")
    if result is None:
        raise HTTPException(409, "Run a comparison first.")
    if kind not in REPORTS:
        raise HTTPException(404, "Unknown report type.")
    build, extension, media = REPORTS[kind]
    name = f"equaliser_{result['evidence']['run_id']}.{extension}"
    return Response(build(result), media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


dist = Path(__file__).parent / "frontend" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
