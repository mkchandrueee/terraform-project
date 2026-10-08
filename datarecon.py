"""DataRecon: one-page data migration reconciliation (file / SQL on either side).

Run:  streamlit run datarecon.py

Compares Source vs Target by KEY (not by row position), so row order after a
migration does not matter. Reports missing rows, extra rows, cell-level
mismatches, duplicate keys, and per-column null / distinct / sum profiles.
"""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import json
import re

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

PROFILE_FILE = Path.home() / ".datarecon_profiles.json"
NEW = "-- New --"
EXPORT_ROW_CAP = 100_000  # Excel/CSV rows per sheet
SAFE_INT = 2**53
DB_DEFAULTS = {"PostgreSQL": 5432, "SQL Server": 1433, "MySQL": 3306, "SQLite": 0}


# --------------------------------------------------------------------------
# Saved profiles (connections + named queries; passwords never written)
# --------------------------------------------------------------------------
def load_config():
    try:
        config = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        config = {}
    config.setdefault("connections", {})
    config.setdefault("queries", {})
    return config


def save_config(config):
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Loading data
# --------------------------------------------------------------------------
def read_file(uploaded, sep=","):
    ext = Path(uploaded.name).suffix.lower()
    if ext in (".csv", ".txt", ".tsv"):
        sep = "\t" if ext == ".tsv" and sep == "," else sep
        return pd.read_csv(uploaded, sep=sep, dtype=str, low_memory=False)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(uploaded, dtype=str)
    if ext == ".parquet":
        return pd.read_parquet(uploaded)
    raise ValueError("Supported files: CSV, TXT, TSV, XLSX, XLS, Parquet.")


def make_engine(conn, password):
    kind = conn["database_type"]
    if kind == "SQLite":
        return create_engine(f"sqlite:///{conn['database']}")
    if not password:
        raise ValueError("Enter the password for this connection and press Save.")
    drivers = {
        "PostgreSQL": ("postgresql+psycopg2", {}),
        "MySQL": ("mysql+pymysql", {}),
        "SQL Server": (
            "mssql+pyodbc",
            {
                "driver": "ODBC Driver 18 for SQL Server",
                "TrustServerCertificate": "yes",
            },
        ),
    }
    drivername, query = drivers[kind]
    url = URL.create(
        drivername,
        username=conn["username"],
        password=password,
        host=conn["host"],
        port=int(conn["port"]),
        database=conn["database"],
        query=query,
    )
    return create_engine(url, pool_pre_ping=True)


def run_query(conn, password, sql, max_rows=0):
    sql = sql.strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise ValueError("Query must start with SELECT or WITH.")
    if ";" in sql:
        raise ValueError("Enter one SQL statement only.")
    engine = make_engine(conn, password)
    try:
        with engine.connect() as db:
            chunks, total = [], 0
            for chunk in pd.read_sql_query(text(sql), db, chunksize=50_000):
                chunks.append(chunk)
                total += len(chunk)
                if max_rows and total >= max_rows:
                    break
        frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        return frame.head(max_rows) if max_rows else frame
    finally:
        engine.dispose()


# --------------------------------------------------------------------------
# Comparison engine (vectorised, key based)
# --------------------------------------------------------------------------
def prep(df, trim=True, empty_is_null=True, ignore_case=False):
    """Normalise names (trim + lowercase) and every value to nullable text."""
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if df.columns.duplicated().any():
        dup = sorted(set(df.columns[df.columns.duplicated()]))
        raise ValueError(f"Duplicate column names (case-insensitive): {dup}")
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            fmt = "%Y-%m-%d" if (s.dropna().dt.normalize() == s.dropna()).all() \
                else "%Y-%m-%d %H:%M:%S"
            s = s.dt.strftime(fmt)
        s = s.astype("string")
        if trim:
            s = s.str.strip()
        if empty_is_null:
            s = s.mask(s == "")
        if ignore_case:
            s = s.str.lower()
        # 12.0 -> 12 so file/DB integer keys line up
        s = s.str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True)
        df[col] = s
    return df


def values_equal(a, b, tol):
    """Element-wise equality of two aligned string Series (NULL == NULL)."""
    both_null = a.isna() & b.isna()
    same = (a == b).fillna(False).astype(bool) | both_null
    todo = ~same & a.notna() & b.notna()
    if todo.any():
        na = pd.to_numeric(a[todo].astype(object), errors="coerce")
        nb = pd.to_numeric(b[todo].astype(object), errors="coerce")
        ok = (na.abs() < SAFE_INT) & (nb.abs() < SAFE_INT) & ((na - nb).abs() <= tol)
        same.loc[ok[ok].index] = True
    return same


def numeric_sum(s):
    nn = s.dropna()
    if nn.empty:
        return None
    num = pd.to_numeric(nn.astype(object), errors="coerce")
    return float(num.sum()) if num.notna().all() else None


def status(ok, warn=False):
    return "PASS" if ok else ("WARN" if warn else "FAIL")


def compare(src, tgt, keys=(), ignore=(), trim=True, empty_is_null=True,
            ignore_case=False, tol=0.0, detail_cap=10_000):
    s = prep(src, trim, empty_is_null, ignore_case)
    t = prep(tgt, trim, empty_is_null, ignore_case)
    ignore = {c.strip().lower() for c in ignore}
    keys = [k.strip().lower() for k in keys]

    s_cols = [c for c in s.columns if c not in ignore]
    t_cols = [c for c in t.columns if c not in ignore]
    common = [c for c in s_cols if c in t_cols]
    only_s = [c for c in s_cols if c not in t_cols]
    only_t = [c for c in t_cols if c not in s_cols]
    if not common:
        raise ValueError("Source and target share no columns.")
    bad = [k for k in keys if k not in common]
    if bad:
        raise ValueError(f"Key column(s) not on both sides: {bad}")

    row_mode = not keys  # no key: compare whole rows as a multiset
    keys = keys or common
    values = [c for c in common if c not in keys]
    join = keys + ["__occ"]

    def shape(df):
        df = df[common].copy()
        for k in keys:
            df[k] = df[k].fillna("<NULL>")
        df["__occ"] = df.groupby(keys, dropna=False).cumcount()
        dups = int(df.duplicated(keys, keep=False).sum())
        return df, dups

    s2, s_dups = shape(s)
    t2, t_dups = shape(t)
    merged = s2.merge(t2, on=join, how="outer", suffixes=("__s", "__t"),
                      indicator=True)

    def side_rows(flag, suffix):
        part = merged[merged["_merge"] == flag]
        out = part[keys + [c + suffix for c in values]]
        return out.rename(columns={c + suffix: c for c in values}).reset_index(drop=True)

    only_in_src = side_rows("left_only", "__s")
    only_in_tgt = side_rows("right_only", "__t")
    both = merged[merged["_merge"] == "both"]

    diff_cells, diff_frames = {}, []
    row_diff = pd.Series(False, index=both.index)
    for col in values:
        a, b = both[col + "__s"], both[col + "__t"]
        bad_mask = ~values_equal(a, b, tol)
        diff_cells[col] = int(bad_mask.sum())
        if bad_mask.any():
            row_diff |= bad_mask
            if sum(len(f) for f in diff_frames) < detail_cap:
                f = both.loc[bad_mask, keys].copy()
                f["column"], f["source"], f["target"] = col, a[bad_mask], b[bad_mask]
                diff_frames.append(f.head(detail_cap))
    mismatches = (pd.concat(diff_frames, ignore_index=True) if diff_frames
                  else pd.DataFrame(columns=keys + ["column", "source", "target"]))

    matched = len(both)
    rows_ok = matched - int(row_diff.sum())
    n_cells = sum(diff_cells.values())

    profile = []
    for col in common:
        ss, tt = s[col], t[col]
        sum_s, sum_t = numeric_sum(ss), numeric_sum(tt)
        mism = diff_cells.get(col, 0)
        sums_ok = sum_s is None or sum_t is None or abs(sum_s - sum_t) <= tol * max(len(s), 1) + 1e-9
        profile.append({
            "column": col,
            "role": "key" if col in keys and not row_mode else "compared",
            "source_nulls": int(ss.isna().sum()), "target_nulls": int(tt.isna().sum()),
            "source_distinct": int(ss.nunique()), "target_distinct": int(tt.nunique()),
            "source_sum": sum_s, "target_sum": sum_t,
            "mismatched_cells": mism,
            "status": status(mism == 0 and sums_ok
                             and ss.isna().sum() == tt.isna().sum()),
        })
    profile = pd.DataFrame(profile)

    schema = pd.DataFrame(
        [{"column": c, "status": "On both sides"} for c in common]
        + [{"column": c, "status": "Only in source"} for c in only_s]
        + [{"column": c, "status": "Only in target"} for c in only_t]
    )

    checks = pd.DataFrame([
        ("Schema: same columns", len(only_s), len(only_t), status(not only_s and not only_t)),
        ("Row count", len(s), len(t), status(len(s) == len(t))),
        ("Rows only in source (missing in target)", len(only_in_src), "", status(len(only_in_src) == 0)),
        ("Rows only in target (unexpected)", "", len(only_in_tgt), status(len(only_in_tgt) == 0)),
        ("Matched rows fully equal", rows_ok, matched, status(rows_ok == matched)),
        ("Mismatched cells", n_cells, "", status(n_cells == 0)),
        ("Duplicate key rows", s_dups, t_dups, status(s_dups == 0 and t_dups == 0, warn=True)),
        ("Null-count differences (columns)", int((profile["source_nulls"] != profile["target_nulls"]).sum()), "", status((profile["source_nulls"] == profile["target_nulls"]).all())),
    ], columns=["check", "source", "target", "status"])

    return {
        "passed": bool((checks["status"] != "FAIL").all()),
        "mode": "whole-row (no key)" if row_mode else f"key: {', '.join(keys)}",
        "checks": checks, "columns": profile, "schema": schema,
        "only_in_source": only_in_src, "only_in_target": only_in_tgt,
        "mismatches": mismatches, "total_mismatch_cells": n_cells,
        "matched": matched, "source_rows": len(s), "target_rows": len(t),
    }


def build_exports(result):
    sheets = {
        "Checks": result["checks"], "Columns": result["columns"],
        "Schema": result["schema"], "Only in Source": result["only_in_source"],
        "Only in Target": result["only_in_target"], "Mismatches": result["mismatches"],
    }
    sheets = {k: v.head(EXPORT_ROW_CAP).astype(object) for k, v in sheets.items()}
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    zbuf = BytesIO()
    with ZipFile(zbuf, "w", ZIP_DEFLATED) as zf:
        for name, frame in sheets.items():
            zf.writestr(f"{name.lower().replace(' ', '_')}.csv",
                        frame.to_csv(index=False).encode("utf-8-sig"))
    return xlsx.getvalue(), zbuf.getvalue()


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
def pwd_key(name):
    return f"pwd::{name}"


def connections_panel(config):
    with st.expander("Database connections (saved locally, passwords kept in memory only)"):
        conns = config["connections"]
        pick = st.selectbox("Load connection", [NEW] + sorted(conns), key="cx_pick")
        if st.session_state.get("cx_loaded") != pick:
            saved = conns.get(pick, {})
            for field, default in dict(name="" if pick == NEW else pick,
                                       type="PostgreSQL", host="", port=5432,
                                       database="", username="").items():
                key_map = {"type": "database_type"}
                st.session_state[f"cx_{field}"] = saved.get(key_map.get(field, field), default)
            st.session_state["cx_password"] = st.session_state.get(pwd_key(pick), "")
            st.session_state["cx_loaded"] = pick
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name", key="cx_name")
        kind = c2.selectbox("Type", list(DB_DEFAULTS), key="cx_type")
        host = c3.text_input("Host", key="cx_host")
        c4, c5, c6, c7 = st.columns(4)
        port = c4.number_input("Port", 0, 65535, key="cx_port")
        database = c5.text_input("Database (SQLite: file path)", key="cx_database")
        user = c6.text_input("Username", key="cx_username")
        password = c7.text_input("Password", type="password", key="cx_password")
        conn = dict(database_type=kind, host=host.strip(), port=int(port),
                    database=database.strip(), username=user.strip())
        b1, b2, b3 = st.columns(3)
        if b1.button("Save connection") :
            if not name.strip() or not database.strip():
                st.error("Name and database are required.")
            else:
                conns[name.strip()] = conn
                save_config(config)
                st.session_state[pwd_key(name.strip())] = password
                st.success(f"Saved '{name.strip()}'.")
        if b2.button("Test connection"):
            try:
                engine = make_engine(conn, password)
                with engine.connect() as db:
                    db.execute(text("SELECT 1"))
                engine.dispose()
                st.success("Connection succeeded.")
            except Exception as err:
                st.error(f"Connection failed: {err}")
        if b3.button("Delete saved connection") and pick in conns:
            del conns[pick]
            save_config(config)
            st.session_state["cx_loaded"] = None
            st.rerun()


def side_input(label, prefix, config):
    """Render one side (file or SQL); return a zero-arg loader and its label."""
    st.markdown(f"**{label}**")
    mode = st.radio("Input", ["File", "Database query"], horizontal=True,
                    key=f"{prefix}_mode", label_visibility="collapsed")
    if mode == "File":
        up = st.file_uploader("File", type=["csv", "txt", "tsv", "xlsx", "xls", "parquet"],
                              key=f"{prefix}_file", label_visibility="collapsed")
        sep = st.text_input("CSV delimiter", ",", key=f"{prefix}_sep", max_chars=3)

        def load():
            if not up:
                raise ValueError(f"{label}: choose a file.")
            return read_file(up, sep or ","), up.name
        return load

    conns, queries = config["connections"], config["queries"]
    cname = st.selectbox("Connection", [""] + sorted(conns), key=f"{prefix}_conn",
                         format_func=lambda n: n or "-- select --")
    qname = st.selectbox("Saved query", [""] + sorted(queries), key=f"{prefix}_saved",
                         format_func=lambda n: n or "-- none --")
    if st.session_state.get(f"{prefix}_qloaded") != qname:
        st.session_state[f"{prefix}_sql"] = queries.get(qname, "")
        st.session_state[f"{prefix}_qloaded"] = qname
    sql = st.text_area("SQL (SELECT / WITH)", height=140, key=f"{prefix}_sql",
                       placeholder="SELECT * FROM schema.table")
    s1, s2 = st.columns([3, 1])
    save_as = s1.text_input("Save query as", key=f"{prefix}_saveas", label_visibility="collapsed",
                            placeholder="Save query as…")
    if s2.button("Save", key=f"{prefix}_savebtn") and save_as.strip():
        queries[save_as.strip()] = sql
        save_config(config)
        st.toast(f"Saved query '{save_as.strip()}'")
    max_rows = st.number_input("Max rows (0 = all)", 0, step=10_000, key=f"{prefix}_max")

    def load():
        if not cname:
            raise ValueError(f"{label}: select a connection.")
        frame = run_query(conns[cname], st.session_state.get(pwd_key(cname), ""),
                          sql, int(max_rows))
        return frame, f"{cname} query"
    return load


def show_result(result, names):
    verdict = st.success if result["passed"] else st.error
    verdict(f"{'PASS' if result['passed'] else 'FAIL'} - {result['mode']}")
    m = st.columns(5)
    m[0].metric(f"{names[0]} rows", f"{result['source_rows']:,}")
    m[1].metric(f"{names[1]} rows", f"{result['target_rows']:,}")
    m[2].metric("Missing in target", f"{len(result['only_in_source']):,}")
    m[3].metric("Extra in target", f"{len(result['only_in_target']):,}")
    m[4].metric("Mismatched cells", f"{result['total_mismatch_cells']:,}")

    xlsx, zipped = build_exports(result)
    d1, d2 = st.columns(2)
    d1.download_button("Download Excel report", xlsx, "datarecon_report.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("Download CSV reports (zip)", zipped, "datarecon_reports.zip",
                       "application/zip")

    def table(title, frame, note=""):
        st.subheader(f"{title} ({len(frame):,})")
        if note:
            st.caption(note)
        st.dataframe(frame.astype("string"), width="stretch", hide_index=True)

    table("Checks", result["checks"])
    table("Column profile", result["columns"],
          "Null / distinct / numeric-sum totals and mismatches per column.")
    if (result["schema"]["status"] != "On both sides").any():
        table("Schema differences",
              result["schema"][result["schema"]["status"] != "On both sides"])
    table("Value mismatches", result["mismatches"],
          f"{result['total_mismatch_cells']:,} mismatched cells in total; detail is capped.")
    table("Rows only in source", result["only_in_source"].head(5000))
    table("Rows only in target", result["only_in_target"].head(5000))


def main():
    st.set_page_config(page_title="DataRecon", layout="wide")
    st.title("DataRecon - migration reconciliation")
    st.caption("Compare file or SQL results on either side, matched by key.")
    config = load_config()
    connections_panel(config)

    st.header("1 - Source and target")
    left, right = st.columns(2)
    with left:
        load_src = side_input("Source (legacy)", "src", config)
    with right:
        load_tgt = side_input("Target (migrated)", "tgt", config)

    if st.button("Load data", type="primary"):
        st.session_state.pop("result", None)
        try:
            with st.spinner("Loading..."):
                src, sname = load_src()
                tgt, tname = load_tgt()
            st.session_state["data"] = (src, tgt, (sname, tname))
        except Exception as err:
            st.session_state.pop("data", None)
            st.error(f"Could not load data: {err}")

    data = st.session_state.get("data")
    if not data:
        st.info("Choose a source and a target, then press Load data.")
        return
    src, tgt, names = data
    p1, p2 = st.columns(2)
    for col, frame, name in ((p1, src, names[0]), (p2, tgt, names[1])):
        col.caption(f"{name}: {len(frame):,} rows x {len(frame.columns)} columns")
        col.dataframe(frame.head(10).astype("string"), width="stretch",
                      hide_index=True)

    st.header("2 - Rules")
    norm = lambda df: [str(c).strip().lower() for c in df.columns]
    common = [c for c in norm(src) if c in set(norm(tgt))]
    guess = [c for c in common if c in ("id", "pk")][:1]
    keys = st.multiselect("Key column(s) - blank compares whole rows as a set",
                          common, default=guess)
    ignore = st.multiselect("Ignore columns (audit timestamps, surrogate keys...)",
                            sorted(set(norm(src)) | set(norm(tgt))))
    o = st.columns(4)
    trim = o[0].checkbox("Trim whitespace", True)
    empty_null = o[1].checkbox("Treat empty text as NULL", True)
    nocase = o[2].checkbox("Ignore value case", False)
    tol = o[3].number_input("Numeric tolerance", 0.0, format="%g", step=0.01)

    if st.button("Run comparison", type="primary"):
        try:
            with st.spinner("Comparing..."):
                st.session_state["result"] = compare(
                    src, tgt, keys, ignore, trim, empty_null, nocase, tol)
        except Exception as err:
            st.session_state.pop("result", None)
            st.error(f"Comparison failed: {err}")

    if "result" in st.session_state:
        st.header("3 - Results")
        show_result(st.session_state["result"], names)


if __name__ == "__main__":
    main()
