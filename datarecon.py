"""DataRecon: one-page data migration reconciliation (file / SQL on either side).

Run:  streamlit run datarecon.py

Compares Source vs Target by KEY (not by row position), so row order after a
migration does not matter. Reports missing rows, extra rows, cell-level
mismatches, duplicate keys, and per-column null / distinct / sum profiles.
"""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import getpass
import hashlib
import html
import json
import os
import re
import time
import uuid

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# DATARECON_PROFILE / DATARECON_KEY relocate the saved profile and key (e.g. an isolated demo profile)
PROFILE_FILE = Path(os.environ.get("DATARECON_PROFILE") or Path.home() / ".datarecon_profiles.json")
KEY_FILE = Path(os.environ.get("DATARECON_KEY") or Path.home() / ".datarecon.key")
NEW = "-- New --"
EXPORT_ROW_CAP = 100_000  # rows per sheet/CSV part; larger frames split, never truncate
DISPLAY_ROWS = 1_000
DEFAULT_MARKERS = "N/A, NA, NULL, None, -, -999, 1900-01-01"
DEFAULT_NULL_TOKENS = "NULL, None, NaN, N/A, #N/A"
SAFE_INT = 2**53


def _st_version():
    try:
        return tuple(int(x) for x in re.findall(r"\d+", st.__version__)[:2])
    except Exception:
        return (0, 0)


# width="stretch" and deferred (callable) downloads need a recent Streamlit; older ones get a fallback.
MODERN_ST = _st_version() >= (1, 50)


def show_df(target, frame, **kwargs):
    """st.dataframe at full width on any Streamlit version."""
    kwargs.update({"width": "stretch"} if MODERN_ST else {"use_container_width": True})
    return target.dataframe(frame, hide_index=True, **kwargs)


def download(target, label, builder, file_name, mime, key):
    """Download button that builds its file only when needed.

    Modern Streamlit builds on click (callable data). Older versions get a two-step
    'Prepare' button so the file is still not rebuilt on every rerun.
    """
    if MODERN_ST:
        return target.download_button(label, builder, file_name, mime, key=key)
    cache = st.session_state.setdefault("_ready_downloads", {})
    if key in cache:
        target.download_button(f"{label} (ready)", cache[key], file_name, mime, key=key)
    elif target.button(f"Prepare: {label}", key=f"prep_{key}"):
        with st.spinner("Building report..."):
            cache[key] = builder()
        st.rerun()
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
    config.setdefault("rules", {})
    return config


def save_config(config):
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    try:  # may hold encrypted passwords: owner-only
        os.chmod(PROFILE_FILE, 0o600)
    except OSError:
        pass


def _fernet():
    """Fernet cipher keyed by a generated, owner-only key file (None if `cryptography` is missing)."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    if KEY_FILE.exists():
        key = KEY_FILE.read_bytes()
    else:
        key = Fernet.generate_key()
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
    return Fernet(key)


def encrypt_password(password):
    cipher = _fernet()
    return cipher.encrypt(password.encode()).decode() if cipher and password else None


def decrypt_password(token):
    cipher = _fernet()
    if not cipher or not token:
        return ""
    try:
        return cipher.decrypt(token.encode()).decode()
    except Exception:  # wrong/missing key file
        return ""


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
def prep(df, trim=True, empty_is_null=True, ignore_case=False, null_tokens=()):
    """Normalise names (trim + lowercase) and every value to nullable text.

    Blank text and `null_tokens` (e.g. 'NULL', 'N/A') become real NULLs so a file's
    literal "NULL" equals a database NULL. What was converted is recorded per column
    in df.attrs['null_stats'] = {column: (real_null, blank, token)}.
    """
    df = df.reset_index(drop=True)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if df.columns.duplicated().any():
        dup = sorted(set(df.columns[df.columns.duplicated()]))
        raise ValueError(f"Duplicate column names (case-insensitive): {dup}")
    tokens = {str(x).strip().lower() for x in null_tokens if str(x).strip()}
    stats = {}
    for col in df.columns:
        s = df[col]
        can_hold_tokens = not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s))
        if pd.api.types.is_datetime64_any_dtype(s):
            fmt = "%Y-%m-%d" if (s.dropna().dt.normalize() == s.dropna()).all() \
                else "%Y-%m-%d %H:%M:%S"
            s = s.dt.strftime(fmt)
        s = s.astype("string")
        real_null = int(s.isna().sum())
        if trim:
            s = s.str.strip()
        blanks = tokens_n = 0
        if empty_is_null:
            blank = (s == "").fillna(False).to_numpy(dtype=bool)
            blanks = int(blank.sum())
            if blanks:
                s = s.mask(blank)
        if tokens and can_hold_tokens:
            tok = s.str.lower().isin(tokens).fillna(False).to_numpy(dtype=bool)
            tokens_n = int(tok.sum())
            if tokens_n:
                s = s.mask(tok)
        if ignore_case:
            s = s.str.lower()
        # 12.0 -> 12 so file/DB integer keys line up
        if s.str.contains(".0", regex=False).any():
            s = s.str.replace(r"^(-?\d+)\.0+$", r"\1", regex=True)
        df[col] = s
        stats[col] = (real_null, blanks, tokens_n)
    df.attrs["null_stats"] = stats
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
        # '02134' vs '2134' is a lost leading zero (zip/account no.), not a formatting difference
        lead_a = a[todo].str.match(r"^-?0\d").fillna(False).to_numpy(dtype=bool)
        lead_b = b[todo].str.match(r"^-?0\d").fillna(False).to_numpy(dtype=bool)
        ok = ok & pd.Series(lead_a == lead_b, index=ok.index)
        same.loc[ok[ok].index] = True
    return same


INT_KEY_RE = r"^(0|-?[1-9]\d*)$"
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
TS_RE = r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$"


def analyse_column(s):
    """(kind, numeric Series or None), parsed once per column and reused everywhere."""
    nn = s.dropna()
    if nn.empty:
        return "empty", None
    try:  # strict cast fails fast on the first non-numeric value
        num = nn.astype("float64")
        if num.notna().all():
            return ("integer" if (num == num.round()).all() else "decimal"), num
    except (ValueError, TypeError):
        pass
    head = nn.head(200)
    for kind, rx in (("date", DATE_RE), ("timestamp", TS_RE)):
        if head.str.match(rx).all() and nn.str.match(rx).all():
            return kind, None
    if nn.str.lower().isin(["true", "false"]).all():
        return "boolean", None
    return "text", None


def type_status(a, b):
    if a == b or "empty" in (a, b):
        return "PASS"
    if {a, b} <= {"integer", "decimal"} or {a, b} <= {"date", "timestamp"}:
        return "WARN"  # compatible but not identical
    return "FAIL"


def aggregate(s, kind, num):
    """count / distinct / sum / avg / min / max for one column."""
    nn = s.dropna()
    out = {"count": len(nn), "distinct": int(nn.nunique())}
    if kind in ("integer", "decimal") and num is not None:
        out.update({"sum": num.sum(), "avg": num.mean(), "min": num.min(), "max": num.max()})
    elif not nn.empty:
        out.update({"min": nn.min(), "max": nn.max(), "max_length": int(nn.str.len().max())})
    return out


def agg_equal(a, b, tol):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if pd.isna(a) and pd.isna(b):
        return True
    return not pd.isna(a) and not pd.isna(b) and abs(float(a) - float(b)) <= tol


def _num_pair(a, b):
    na = pd.to_numeric(a.astype(object), errors="coerce")
    nb = pd.to_numeric(b.astype(object), errors="coerce")
    return (na, nb) if na.notna().all() and nb.notna().all() else None


def explain_column(col, a, b):
    """Return one exact, all-rows finding for why a column differs, or None.

    Every claim is checked against every differing row (no sampling); fewer than
    three rows makes no claim. First match wins, most specific first.
    """
    if len(a) < 3:
        return None
    if a.notna().all() and b.isna().all():
        return "Target arrived NULL for every differing row (column not loaded/mapped?)"
    if a.isna().all() and b.notna().all():
        return "Source is NULL where target has values (target default/derived?)"
    if a.notna().all() and b.notna().all():
        if (a.str.strip() == b.str.strip()).all():
            return "Differ only by whitespace - enable 'Trim whitespace'"
        if (a.str.lower() == b.str.lower()).all():
            return "Differ only by letter case - enable 'Ignore value case'"
        if (a.str.lstrip("0") == b).all():
            return f"Leading zeros lost in target (e.g. '{a.iloc[0]}' became '{b.iloc[0]}') - code/ID/zip stored as a number?"
        if (a.str.len() > b.str.len()).all() and all(x.startswith(y) for x, y in zip(a, b)):
            return f"Target truncated: values cut to at most {int(b.str.len().max())} character(s)"
        nums = _num_pair(a, b)
        if nums:
            na, nb = nums
            if (na == -nb).all() and (na != 0).all():
                return "Sign flipped on every differing row"
            nz = na != 0
            if nz.all():
                ratio = nb / na
                if np.isclose(ratio, ratio.iloc[0], rtol=1e-9).all() and not np.isclose(ratio.iloc[0], 1):
                    return f"Target is exactly {ratio.iloc[0]:g}x the source (units/scale change?)"
            diff = nb - na
            if np.isclose(diff, diff.iloc[0], rtol=1e-9, atol=1e-12).all() and abs(diff.iloc[0]) > 1e-12:
                return f"Target is offset by exactly {diff.iloc[0]:+g} from the source"
            for d in range(0, 7):
                if np.isclose(na.round(d), nb, rtol=0, atol=1e-9).all():
                    return f"Target is the source rounded to {d} decimal places"
            if diff.abs().max() < 1:
                return f"Small numeric differences (max {diff.abs().max():g}) - consider a numeric tolerance"
            return None
        da = pd.to_datetime(a, errors="coerce", format="mixed")
        db = pd.to_datetime(b, errors="coerce", format="mixed")
        if da.notna().all() and db.notna().all():
            delta = db - da
            if (delta == delta.iloc[0]).all() and delta.iloc[0] != pd.Timedelta(0):
                return f"Timestamps shifted by exactly {delta.iloc[0]} (timezone?)"
    return None


def key_block_finding(rows, keys, side):
    """Missing/extra rows whose single integer key forms contiguous blocks = partial load."""
    if len(rows) < 3 or len(keys) != 1:
        return None
    k = pd.to_numeric(rows[keys[0]], errors="coerce")
    if k.isna().any():
        return None
    k = k.astype(int).sort_values().drop_duplicates()
    blocks = (k.diff() != 1).cumsum()
    spans = k.groupby(blocks).agg(["min", "max"])
    if len(spans) > 5:
        return None
    desc = ", ".join(f"{lo}-{hi}" for lo, hi in spans.itertuples(index=False))
    return f"Rows {side} form {len(spans)} contiguous key block(s) [{desc}] - looks like a partial/skipped load"


def build_insights(mismatches, only_src, only_tgt, keys, row_mode):
    out = []
    for col, g in mismatches.groupby("column", sort=False):
        out.append({"finding": explain_column(col, g["source"], g["target"])
                    or "No single uniform cause found", "column": col, "rows": len(g)})
    if not row_mode:
        for rows, side in ((only_src, "missing in target"), (only_tgt, "extra in target")):
            f = key_block_finding(rows, keys, side)
            if f:
                out.append({"finding": f, "column": ", ".join(keys), "rows": len(rows)})
    return pd.DataFrame(out, columns=["finding", "column", "rows"]).sort_values(
        "rows", ascending=False, ignore_index=True)


def status(ok, warn=False):
    return "PASS" if ok else ("WARN" if warn else "FAIL")


def compare(src, tgt, keys=(), ignore=(), trim=True, empty_is_null=True,
            ignore_case=False, tol=0.0, detail_cap=100_000, agg_cols=(), markers=(),
            count_tol_abs=0, count_tol_pct=0.0, group_by=(), file_hashes=None,
            fast=False, include_matched=False, null_tokens=(), evidence=None):
    """Key-based comparison. fast=True runs only the full data validation
    (counts, missing/extra rows, cell mismatches, explanations) and skips
    profiling, data types, aggregations and distributions."""
    started = time.perf_counter()
    raw_s = {str(c).strip().lower(): str(d) for c, d in src.dtypes.items()}
    raw_t = {str(c).strip().lower(): str(d) for c, d in tgt.dtypes.items()}
    s = prep(src, trim, empty_is_null, ignore_case, null_tokens)
    t = prep(tgt, trim, empty_is_null, ignore_case, null_tokens)
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

    # ---- shape both sides: null-safe keys, integer keys (4x faster merge), duplicate handling
    s2, t2 = s[common].copy(), t[common].copy()
    int_keys = []
    for k in keys:
        s2[k], t2[k] = s2[k].fillna("<NULL>"), t2[k].fillna("<NULL>")
        if s2[k].str.match(INT_KEY_RE).all() and t2[k].str.match(INT_KEY_RE).all():
            try:
                s2[k], t2[k] = s2[k].astype("int64"), t2[k].astype("int64")
                int_keys.append(k)
            except (ValueError, OverflowError):
                pass
    s_mask, t_mask = s2.duplicated(keys, keep=False), t2.duplicated(keys, keep=False)
    s_dups, t_dups = int(s_mask.sum()), int(t_mask.sum())

    def dup_listing(prepped, shaped, mask):
        """Every row sharing a key with another row, with group size and occurrence #."""
        if not mask.any():
            return pd.DataFrame()
        sub = shaped.loc[mask]
        out = prepped.loc[mask, common].copy()
        out["duplicate_count"] = sub.assign(_n=1).groupby(keys, dropna=False)["_n"].transform("sum")
        out["occurrence"] = sub.groupby(keys, dropna=False).cumcount() + 1
        out = out.loc[sub.sort_values(keys, kind="stable").index]
        return out[["duplicate_count", "occurrence"] + common].head(detail_cap).reset_index(drop=True)

    dup_source, dup_target = dup_listing(s, s2, s_mask), dup_listing(t, t2, t_mask)
    join = list(keys)
    if s_dups or t_dups:  # pair duplicate keys by occurrence order
        join.append("__occ")
        s2["__occ"] = s2.groupby(keys, dropna=False).cumcount() if s_dups else 0
        t2["__occ"] = t2.groupby(keys, dropna=False).cumcount() if t_dups else 0
    merged = s2.merge(t2, on=join, how="outer", suffixes=("__s", "__t"), indicator=True)
    del s2, t2
    codes = merged["_merge"].cat.codes.to_numpy()  # 0 left_only, 1 right_only, 2 both
    both_mask = codes == 2

    def restore(df):  # integer keys back to text for display/export
        for k in int_keys:
            df[k] = df[k].astype("string")
        return df

    def side_rows(code, suffix):
        part = merged.iloc[np.flatnonzero(codes == code)][keys + [c + suffix for c in values]]
        return restore(part.rename(columns={c + suffix: c for c in values}).reset_index(drop=True))

    only_in_src, only_in_tgt = side_rows(0, "__s"), side_rows(1, "__t")

    # ---- cell comparison (in place, no copy of the merged frame)
    bad_by_col, diff_cells, diff_frames = {}, {}, []
    null_to_value, value_to_null = {}, {}
    row_diff = np.zeros(len(merged), dtype=bool)
    for col in values:
        a, b = merged[col + "__s"], merged[col + "__t"]
        na_a, na_b = a.isna().to_numpy(dtype=bool), b.isna().to_numpy(dtype=bool)
        null_to_value[col] = int((na_a & ~na_b & both_mask).sum())
        value_to_null[col] = int((~na_a & na_b & both_mask).sum())
        bad_arr = ~np.asarray(values_equal(a, b, tol), dtype=bool) & both_mask
        n_bad = int(bad_arr.sum())
        diff_cells[col] = n_bad
        if n_bad:
            bad_by_col[col] = bad_arr
            row_diff |= bad_arr
            room = detail_cap - sum(len(f) for f in diff_frames)
            if room > 0:
                rows = np.flatnonzero(bad_arr)[:room]
                f = merged.iloc[rows][keys].reset_index(drop=True)
                sv, tv = a.iloc[rows].to_numpy(), b.iloc[rows].to_numpy()
                f["column"], f["source"], f["target"] = col, sv, tv
                f["issue"] = np.where(pd.isna(sv), "NULL -> value",
                                      np.where(pd.isna(tv), "value -> NULL", "value differs"))
                diff_frames.append(restore(f))
    mismatches = (pd.concat(diff_frames, ignore_index=True) if diff_frames
                  else pd.DataFrame(columns=keys + ["column", "source", "target", "issue"]))

    # ---- full data result: status per row, side by side (matched rows optional)
    state = np.full(len(merged), "MATCHED", dtype=object)
    state[codes == 0], state[codes == 1], state[row_diff] = "MISSING_IN_TARGET", "EXTRA_IN_TARGET", "MISMATCH"
    sel = np.flatnonzero(np.ones(len(merged), bool) if include_matched else state != "MATCHED")
    sel = sel[np.argsort(state[sel] == "MATCHED", kind="stable")]  # differences first
    mrows = np.flatnonzero(row_diff)
    mc = np.full(len(merged), "", dtype=object)
    if len(mrows):
        text_ = np.full(len(mrows), "", dtype=object)
        for col, arr in bad_by_col.items():
            text_ = text_ + np.where(arr[mrows], col + ", ", "")
        mc[mrows] = [x[:-2] for x in text_]
    full = merged.iloc[sel][keys].reset_index(drop=True)
    full["status"], full["mismatched_columns"] = state[sel], mc[sel]
    if "__occ" in join:  # duplicate keys: say which occurrence each row is
        full.insert(len(keys), "occurrence", merged["__occ"].iloc[sel].to_numpy() + 1)
    for col in values:
        full[col + "_source"] = merged[col + "__s"].iloc[sel].to_numpy()
        full[col + "_target"] = merged[col + "__t"].iloc[sel].to_numpy()
    restore(full)
    n_mismatch_rows = int(row_diff.sum())
    full_counts = {"MATCHED": int(both_mask.sum()) - n_mismatch_rows, "MISMATCH": n_mismatch_rows,
                   "MISSING_IN_TARGET": int((codes == 0).sum()), "EXTRA_IN_TARGET": int((codes == 1).sum())}
    del merged

    matched = int(both_mask.sum())
    rows_ok = matched - n_mismatch_rows
    n_cells = sum(diff_cells.values())
    insights = build_insights(mismatches, only_in_src, only_in_tgt, keys, row_mode)

    def within_count_tol(a, b):
        d = abs(a - b)
        return d <= count_tol_abs or (max(a, b) > 0 and d / max(a, b) * 100 <= count_tol_pct)

    group_by = [g.strip().lower() for g in group_by if g.strip().lower() in common]
    groups = pd.DataFrame()
    if group_by:
        gs = s.groupby(group_by, dropna=False).size().rename("source_rows")
        gt = t.groupby(group_by, dropna=False).size().rename("target_rows")
        groups = pd.concat([gs, gt], axis=1).fillna(0).astype(int).reset_index()
        groups["difference"] = groups["target_rows"] - groups["source_rows"]
        groups["status"] = [status(within_count_tol(a, b)) for a, b in
                            zip(groups["source_rows"], groups["target_rows"])]
        groups = groups.sort_values("status", ascending=False, ignore_index=True)

    schema = pd.DataFrame(
        [{"column": c, "status": "On both sides"} for c in common]
        + [{"column": c, "status": "Only in source"} for c in only_s]
        + [{"column": c, "status": "Only in target"} for c in only_t]
    )
    rows = [
        ("Schema: same columns", len(only_s), len(only_t), status(not only_s and not only_t)),
        ("Column count", len(s_cols), len(t_cols), status(len(s_cols) == len(t_cols))),
        ("Row count", len(s), len(t), status(within_count_tol(len(s), len(t)))),
        ("Rows only in source (missing in target)", len(only_in_src), "", status(len(only_in_src) == 0)),
        ("Rows only in target (unexpected)", "", len(only_in_tgt), status(len(only_in_tgt) == 0)),
        ("Matched rows fully equal", rows_ok, matched, status(rows_ok == matched)),
        ("Mismatched cells", n_cells, "", status(n_cells == 0)),
        ("Duplicate key rows", s_dups, t_dups, status(s_dups == 0 and t_dups == 0, warn=True)),
        ("NULL vs value cells (source NULL -> target value | source value -> target NULL)",
         sum(null_to_value.values()), sum(value_to_null.values()),
         status(not sum(null_to_value.values()) and not sum(value_to_null.values()))),
    ]
    if group_by:
        rows.append(("Row count by group (groups failing)", int((groups["status"] == "FAIL").sum()),
                     "", status(not (groups["status"] == "FAIL").any())))
    if file_hashes:
        rows.append(("File checksum (SHA-256) identical", file_hashes[0][:12], file_hashes[1][:12],
                     "PASS" if file_hashes[0] == file_hashes[1] else "WARN"))

    profile = dtypes = aggs = distribution = nulls = pd.DataFrame()
    if not fast:
        # parse every column once; type inference, sums and aggregates all reuse it
        info_s = {c: analyse_column(s[c]) for c in common}
        info_t = {c: analyse_column(t[c]) for c in common}
        marks = {m.strip().lower() for m in markers if m.strip()}

        def sentinels(col):
            return int(col.dropna().str.lower().isin(marks).sum()) if marks else 0

        prof, null_rows = [], []
        ns, nt = s.attrs.get("null_stats", {}), t.attrs.get("null_stats", {})
        for col in common:
            ss, tt = s[col], t[col]
            n_s, n_t = int(ss.isna().sum()), int(tt.isna().sum())
            sent_s, sent_t = sentinels(ss), sentinels(tt)
            num_s, num_t = info_s[col][1], info_t[col][1]
            sum_s = float(num_s.sum()) if num_s is not None else None
            sum_t = float(num_t.sum()) if num_t is not None else None
            mism = diff_cells.get(col, 0)
            (rs, bs, ts_), (rt, bt, tt_) = ns.get(col, (n_s, 0, 0)), nt.get(col, (n_t, 0, 0))
            null_rows.append({
                "column": col, "source_nulls": n_s, "source_real_null": rs, "source_blank": bs,
                "source_null_token": ts_, "source_null_%": round(n_s / max(len(s), 1) * 100, 4),
                "target_nulls": n_t, "target_real_null": rt, "target_blank": bt,
                "target_null_token": tt_, "target_null_%": round(n_t / max(len(t), 1) * 100, 4),
                "source_NULL->target_value": null_to_value.get(col, 0),
                "source_value->target_NULL": value_to_null.get(col, 0),
                "status": status(n_s == n_t and not null_to_value.get(col, 0) and not value_to_null.get(col, 0)),
            })
            sums_ok = sum_s is None or sum_t is None or abs(sum_s - sum_t) <= tol * max(len(s), 1) + 1e-9
            prof.append({
                "column": col, "role": "key" if col in keys and not row_mode else "compared",
                "source_nulls": n_s, "target_nulls": n_t,
                "source_markers": sent_s, "target_markers": sent_t,
                "source_complete_%": round((len(s) - n_s - sent_s) / max(len(s), 1) * 100, 4),
                "target_complete_%": round((len(t) - n_t - sent_t) / max(len(t), 1) * 100, 4),
                "source_distinct": int(ss.nunique()), "target_distinct": int(tt.nunique()),
                "source_sum": sum_s, "target_sum": sum_t, "mismatched_cells": mism,
                "status": status(mism == 0 and sums_ok and n_s == n_t and sent_s == sent_t),
            })
        profile = pd.DataFrame(prof)
        nulls = pd.DataFrame(null_rows)

        dist = []
        for row in prof:
            col = row["column"]
            if col in keys or row["source_distinct"] > 50 or row["target_distinct"] > 50:
                continue
            vs, vt = s[col].fillna("<NULL>").value_counts(), t[col].fillna("<NULL>").value_counts()
            cnt = pd.concat([vs.rename("source"), vt.rename("target")], axis=1).fillna(0).astype(int)
            for val, r in cnt[cnt["source"] != cnt["target"]].iterrows():
                dist.append({"column": col, "value": val, "source": r["source"],
                             "target": r["target"], "difference": r["target"] - r["source"]})
        distribution = pd.DataFrame(dist, columns=["column", "value", "source", "target", "difference"])

        dt = []
        for col in common:
            a, b = info_s[col][0], info_t[col][0]
            dt.append({"column": col, "source_dtype": raw_s[col], "target_dtype": raw_t[col],
                       "source_type": a, "target_type": b,
                       "source_max_len": int(s[col].str.len().max()) if s[col].notna().any() else 0,
                       "target_max_len": int(t[col].str.len().max()) if t[col].notna().any() else 0,
                       "status": type_status(a, b)})
        dtypes = pd.DataFrame(dt)

        numeric_kinds = ("integer", "decimal")
        wanted = [c.strip().lower() for c in agg_cols] or [
            c for c in common if info_s[c][0] in numeric_kinds or info_t[c][0] in numeric_kinds]
        ag = []
        for col in wanted:
            if col not in common:
                continue
            (ka, na_), (kb, nb_) = info_s[col], info_t[col]
            kind = "decimal" if "decimal" in (ka, kb) else ka if ka != "empty" else kb
            sa, ta = aggregate(s[col], kind, na_), aggregate(t[col], kind, nb_)
            for metric in dict.fromkeys(list(sa) + list(ta)):
                va, vb = sa.get(metric), ta.get(metric)
                va = float("nan") if va is None else (int(va) if metric in ("count", "distinct", "max_length") else va)
                vb = float("nan") if vb is None else (int(vb) if metric in ("count", "distinct", "max_length") else vb)
                numeric = not isinstance(va, str) and not isinstance(vb, str)
                ag.append({"column": col, "metric": metric, "source": va, "target": vb,
                           "difference": (vb - va) if numeric and not pd.isna(va) and not pd.isna(vb) else None,
                           "status": status(agg_equal(va, vb, tol if metric in ("sum", "avg", "min", "max") else 0))})
        aggs = pd.DataFrame(ag, columns=["column", "metric", "source", "target", "difference", "status"],
                            dtype=object)  # object keeps counts whole (7, not 7.0)

        row_dups = (int(s[common].duplicated(keep=False).sum()), int(t[common].duplicated(keep=False).sum()))
        rows += [
            ("Duplicate full rows", row_dups[0], row_dups[1], status(row_dups[0] == row_dups[1])),
            ("Data type differences (columns)", int((dtypes["status"] == "FAIL").sum()),
             int((dtypes["status"] == "WARN").sum()),
             "FAIL" if (dtypes["status"] == "FAIL").any() else status(not (dtypes["status"] == "WARN").any(), warn=True)),
            ("Completeness score % (avg non-null, non-marker)", round(profile["source_complete_%"].mean(), 4),
             round(profile["target_complete_%"].mean(), 4),
             status(profile["source_complete_%"].mean() == profile["target_complete_%"].mean())),
            ("Value distribution differences (low-cardinality columns)", distribution["column"].nunique(), "",
             status(distribution.empty, warn=True)),
            ("Aggregation differences", int((aggs["status"] == "FAIL").sum()), "", status(not (aggs["status"] == "FAIL").any())),
            ("Null-count differences (columns)", int((profile["source_nulls"] != profile["target_nulls"]).sum()), "",
             status((profile["source_nulls"] == profile["target_nulls"]).all())),
        ]
    checks = pd.DataFrame(rows, columns=["check", "source", "target", "status"])

    return {
        "passed": bool((checks["status"] != "FAIL").all()),
        "mode": ("whole-row (no key)" if row_mode else f"key: {', '.join(keys)}")
                + (" | full data validation only" if fast else ""),
        "fast": fast, "seconds": round(time.perf_counter() - started, 1),
        "evidence": evidence or new_evidence(),
        "checks": checks, "columns": profile, "schema": schema,
        "dtypes": dtypes, "aggregations": aggs, "insights": insights, "full": full,
        "full_counts": full_counts, "include_matched": include_matched,
        "groups": groups, "distribution": distribution, "nulls": nulls,
        "dup_source": dup_source, "dup_target": dup_target,
        "null_tokens": sorted({str(x).strip() for x in null_tokens if str(x).strip()}),
        "mismatches_capped": n_cells > len(mismatches),
        "only_in_source": only_in_src, "only_in_target": only_in_tgt,
        "mismatches": mismatches, "total_mismatch_cells": n_cells,
        "matched": matched, "source_rows": len(s), "target_rows": len(t),
    }


def export_parts(result):
    """Result frames as named parts; frames over EXPORT_ROW_CAP split, never truncate."""
    sheets = {
        "Run Info": evidence_frame(result),
        "Checks": result["checks"], "Insights": result["insights"],
        "Columns": result["columns"], "Schema": result["schema"],
        "Data Types": result["dtypes"], "Aggregations": result["aggregations"],
        "Distribution": result["distribution"], "Group Counts": result["groups"],
        "Only in Source": result["only_in_source"], "Only in Target": result["only_in_target"],
        "Duplicates Source": result["dup_source"], "Duplicates Target": result["dup_target"],
        "Null Details": result["nulls"],
        "Mismatches": result["mismatches"], "Full Data": result["full"],
    }
    parts = {}
    for name, frame in sheets.items():
        if frame.empty and name != "Checks":
            continue
        n = max(1, -(-len(frame) // EXPORT_ROW_CAP))
        for i in range(n):
            parts[name if n == 1 else f"{name} {i + 1}"] = frame.iloc[i * EXPORT_ROW_CAP:(i + 1) * EXPORT_ROW_CAP]
    return parts


def _highlight_sheet(writer, sheet, base, frame):
    """Excel conditional-format rules (cheap on huge sheets): mismatches red, missing/extra yellow, duplicates orange."""
    from xlsxwriter.utility import xl_col_to_name
    book, ws = writer.book, writer.sheets[sheet]
    red = book.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006"})
    yellow = book.add_format({"bg_color": "#FFEB9C", "font_color": "#7F6000"})
    orange = book.add_format({"bg_color": "#F8CBAD", "font_color": "#843C0C"})
    cols, last = list(frame.columns), max(len(frame), 1)
    ws.freeze_panes(1, 0)
    ws.set_column(0, max(len(cols) - 1, 0), 18)
    if base == "Run Info":  # SQL text needs a wide, wrapped cell
        wrap = book.add_format({"text_wrap": True, "valign": "top"})
        ws.set_column(0, 0, 14)
        ws.set_column(1, 1, 26, wrap)
        ws.set_column(2, 2, 120, wrap)
        return
    if len(frame) == 0:
        return

    def rule(c1, c2, formula, fmt):
        ws.conditional_format(1, c1, last, c2, {"type": "formula", "criteria": formula, "format": fmt})

    if base == "Full Data" and "mismatched_columns" in cols:
        mc, st_ = xl_col_to_name(cols.index("mismatched_columns")), xl_col_to_name(cols.index("status"))
        for name in cols:
            if name.endswith("_source") and name[:-7] + "_target" in cols:
                i, base_col = cols.index(name), name[:-7].replace('"', '""')
                rule(i, i + 1, f'=ISNUMBER(SEARCH(", {base_col},",", "&${mc}2&","))', red)
                rule(i, i + 1, f'=OR(${st_}2="MISSING_IN_TARGET",${st_}2="EXTRA_IN_TARGET")', yellow)
        rule(cols.index("status"), cols.index("mismatched_columns"), f'=${st_}2="MISMATCH"', red)
        rule(cols.index("status"), cols.index("status"), f'=OR(${st_}2="MISSING_IN_TARGET",${st_}2="EXTRA_IN_TARGET")', yellow)
    elif base == "Mismatches" and "source" in cols:
        rule(cols.index("source"), cols.index("target"), "=TRUE", red)
        rule(cols.index("column"), cols.index("column"), "=TRUE", red)
    elif base.startswith("Duplicates") and "duplicate_count" in cols:
        rule(0, 1, "=TRUE", orange)
    elif base == "Checks":
        for word, fmt in (("FAIL", red), ("WARN", yellow)):
            rule(cols.index("status"), cols.index("status"), f'=${xl_col_to_name(cols.index("status"))}2="{word}"', fmt)
    elif base in ("Null Details", "Columns", "Data Types", "Aggregations") and "status" in cols:
        col = xl_col_to_name(cols.index("status"))
        rule(cols.index("status"), cols.index("status"), f'=${col}2="FAIL"', red)
        rule(cols.index("status"), cols.index("status"), f'=${col}2="WARN"', yellow)


def build_xlsx(result):
    try:  # xlsxwriter is several times faster than openpyxl and supports highlighting
        import xlsxwriter  # noqa: F401
        engine, options = "xlsxwriter", {"engine_kwargs": {"options": {"strings_to_urls": False}}}
    except ImportError:
        engine, options = "openpyxl", {}
    out = BytesIO()
    with pd.ExcelWriter(out, engine=engine, **options) as writer:
        for name, frame in export_parts(result).items():
            sheet = name[:31]
            frame.astype(object).where(frame.notna(), None).to_excel(writer, sheet_name=sheet, index=False)
            if engine == "xlsxwriter":
                _highlight_sheet(writer, sheet, re.sub(r" \d+$", "", name), frame)
    return out.getvalue()


def build_csv_zip(result):
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as zf:
        for name, frame in export_parts(result).items():
            zf.writestr(f"{name.lower().replace(' ', '_')}.csv",
                        frame.to_csv(index=False).encode("utf-8-sig"))
    return out.getvalue()


def build_json(result):
    summary = {k: result[k].astype(object).where(result[k].notna(), None).to_dict("records")
               for k in ("checks", "insights", "columns", "dtypes", "aggregations")}
    summary.update(passed=result["passed"], mode=result["mode"], seconds=result["seconds"],
                   full_counts=result["full_counts"], evidence=result.get("evidence"))
    return json.dumps(summary, indent=2, default=str).encode()


def build_exports(result):
    return build_xlsx(result), build_csv_zip(result), build_json(result)


# --------------------------------------------------------------------------
# Evidence: run information + self-contained HTML report that mirrors the UI
# --------------------------------------------------------------------------
APP_VERSION = "1.0"
HTML_ROWS = 1_000
_INFO_LABELS = {
    "input_type": "Input type", "name": "Name", "connection": "Connection", "database_type": "Database type",
    "host": "Host", "port": "Port", "database": "Database", "username": "Username",
    "file_size_bytes": "File size (bytes)", "sha256": "File SHA-256", "delimiter": "CSV delimiter",
    "max_rows": "Max rows (0 = all)", "rows": "Rows loaded", "columns": "Columns loaded",
    "loaded_at": "Loaded at (UTC)", "sql": "SQL", "sql_sha256": "SQL SHA-256",
}


def _no_secrets(info):
    return {k: v for k, v in (info or {}).items() if "pass" not in k.lower() and "secret" not in k.lower()}


def new_evidence(source=None, target=None, rules=None):
    """Who/when/what produced a result. Never contains passwords."""
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return {
        "run_id": uuid.uuid4().hex[:12].upper(),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "generated_local": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "run_by": user, "tool_version": APP_VERSION, "pandas": pd.__version__, "streamlit": st.__version__,
        "source": _no_secrets(source), "target": _no_secrets(target), "rules": rules or {},
    }


def evidence_frame(result):
    """Run information as section / item / value rows (source and target SQL included)."""
    ev = result.get("evidence") or {}
    rows = [
        ("Run", "Run ID", ev.get("run_id", "")), ("Run", "Generated (UTC)", ev.get("generated_utc", "")),
        ("Run", "Generated (local)", ev.get("generated_local", "")), ("Run", "Run by (OS user)", ev.get("run_by", "")),
        ("Run", "DataRecon version", ev.get("tool_version", "")),
        ("Run", "Library versions", f"pandas {ev.get('pandas', '')}, streamlit {ev.get('streamlit', '')}"),
        ("Run", "Verdict", "PASS" if result["passed"] else "FAIL"), ("Run", "Mode", result["mode"]),
        ("Run", "Compare duration (s)", result["seconds"]),
    ]
    for section in ("source", "target"):
        info = ev.get(section) or {}
        for key, label in _INFO_LABELS.items():
            if key in info and info[key] not in (None, ""):
                rows.append((section.title(), label, str(info[key])))
    for key, value in (ev.get("rules") or {}).items():
        rows.append(("Rules", key, ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)))
    return pd.DataFrame(rows, columns=["section", "item", "value"])


_CSS = """
body{font:14px/1.45 -apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:24px auto;max-width:1400px;padding:0 16px;color:#1f2430}
h1{margin:0 0 4px}h2{margin:28px 0 8px;border-bottom:2px solid #e3e6ee;padding-bottom:4px}
.muted{color:#6b7280;font-size:12px}.banner{padding:12px 16px;border-radius:8px;font-weight:600;margin:12px 0}
.pass{background:#d8f3dc;color:#14532d}.fail{background:#ffd6d6;color:#7f1d1d}
.tiles{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.tile{background:#f3f4f8;border-radius:8px;padding:8px 14px;min-width:150px}
.tile b{display:block;font-size:20px}
.scroll{overflow-x:auto;margin:6px 0}table{border-collapse:collapse;font-size:12.5px;min-width:50%}
th{background:#eef0f6;text-align:left;position:sticky;top:0}th,td{border:1px solid #dfe2ea;padding:4px 8px;vertical-align:top}
td.bad{background:#ffd6d6;color:#7f1d1d}td.warn{background:#fff3c4;color:#7a5b00}td.dup{background:#f8cbad;color:#843c0c}
td.ok{background:#d8f3dc;color:#14532d}.null{color:#9aa0ad;font-style:italic}
pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}footer{margin-top:32px;font-size:12px;color:#6b7280;word-break:break-all}
button{padding:6px 12px;border-radius:6px;border:1px solid #c7ccd8;background:#fff;cursor:pointer}
@media print{button{display:none}body{margin:0;max-width:none}.scroll{overflow:visible}}
"""
_STATUS_CLASS = {"PASS": "ok", "FAIL": "bad", "WARN": "warn", "MISMATCH": "bad",
                 "MISSING_IN_TARGET": "warn", "EXTRA_IN_TARGET": "warn"}


def _cell(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return '<span class="null">NULL</span>'
    return html.escape(str(value))


def _table(frame, cell_class=None, cap=HTML_ROWS):
    if frame is None or frame.empty:
        return '<p class="muted">None.</p>'
    view, cols = frame.head(cap), list(frame.columns)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = []
    for rec in view.itertuples(index=False, name=None):
        row = dict(zip(cols, rec))
        cells = []
        for c in cols:
            cls = (cell_class(row, c) if cell_class else "") or (
                _STATUS_CLASS.get(str(row[c]), "") if c == "status" or str(c).endswith("_status") else "")
            cells.append(f'<td class="{cls}">{_cell(row[c])}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = (f'<p class="muted">Showing first {cap:,} of {len(frame):,} rows; the Excel/CSV reports contain every row.</p>'
            if len(frame) > cap else "")
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{note}'


def build_html(result):
    """Self-contained evidence report with the same sections and highlighting as the Streamlit page."""
    ev = result.get("evidence") or {}
    esc = html.escape
    parts = []

    def section(title, body, note=""):
        parts.append(f"<h2>{esc(title)}</h2>" + (f'<p class="muted">{esc(note)}</p>' if note else "") + body)

    verdict = "PASS" if result["passed"] else "FAIL"
    parts.append(
        f"<h1>DataRecon - Evidence Report</h1>"
        f'<div class="muted">Run {esc(ev.get("run_id", ""))} | {esc(ev.get("generated_utc", ""))} | '
        f'{esc(ev.get("generated_local", ""))} | run by {esc(ev.get("run_by", ""))} | v{esc(ev.get("tool_version", ""))}'
        f' <button onclick="window.print()">Print / Save as PDF</button></div>'
        f'<div class="banner {"pass" if result["passed"] else "fail"}">{verdict} - {esc(result["mode"])}</div>')
    tiles = [(f"{esc(str((ev.get('source') or {}).get('name', 'Source')))} rows", result["source_rows"]),
             (f"{esc(str((ev.get('target') or {}).get('name', 'Target')))} rows", result["target_rows"]),
             ("Missing in target", len(result["only_in_source"])), ("Extra in target", len(result["only_in_target"])),
             ("Mismatched cells", result["total_mismatch_cells"])]
    parts.append('<div class="tiles">' + "".join(f'<div class="tile">{k}<b>{v:,}</b></div>' for k, v in tiles) + "</div>")

    sides = ""
    for name in ("source", "target"):
        info = ev.get(name) or {}
        body = (f"<pre>{esc(info['sql'])}</pre>" if info.get("sql")
                else f'<p class="muted">{esc(str(info.get("input_type", "File")))}: {esc(str(info.get("name", "")))}</p>')
        sides += f"<div><b>{name.title()}</b> - {esc(str(info.get('input_type', '')))} - {esc(str(info.get('name', '')))}{body}</div>"
    section("Run information", f'<div class="cols">{sides}</div>'
            + _table(evidence_frame(result).query("item != 'SQL'")), "Source and target queries exactly as executed.")

    section("Checks", _table(result["checks"]))
    if len(result["insights"]):
        section("Why do rows differ?", "<ul>" + "".join(
            f"<li><b>{esc(str(r.column))}</b> ({r.rows:,} rows): {esc(r.finding)}</li>"
            for r in result["insights"].itertuples()) + "</ul>")
    if not result["columns"].empty:
        section("Column profile", _table(result["columns"]))
    if not result["nulls"].empty:
        tokens = ", ".join(result["null_tokens"]) or "none"
        section("Null / NA details", _table(result["nulls"]),
                f"Real NULL, blank text and NULL-equivalent tokens ({tokens}) are treated as NULL when comparing.")
    if not result["fast"]:
        section("Data types", _table(result["dtypes"]))
        section("Aggregations on critical columns", _table(result["aggregations"]))
    diffs = result["schema"][result["schema"]["status"] != "On both sides"]
    if len(diffs):
        section("Schema differences", _table(diffs))
    if len(result["groups"]):
        section("Row counts by group", _table(result["groups"]))
    if len(result["distribution"]):
        section("Value distribution differences", _table(result["distribution"]))
    for label, key in (("Duplicate records in source", "dup_source"), ("Duplicate records in target", "dup_target")):
        if len(result[key]):
            section(label, _table(result[key], lambda r, c: "dup" if c in ("duplicate_count", "occurrence") else ""),
                    "Every row whose key appears more than once.")

    def full_class(row, c):
        if c == "status":
            return _STATUS_CLASS.get(row["status"], "")
        if c.endswith(("_source", "_target")):
            if row["status"] in ("MISSING_IN_TARGET", "EXTRA_IN_TARGET"):
                return "warn"
            bad = {x.strip() for x in str(row["mismatched_columns"]).split(",") if x.strip()}
            return "bad" if c.rsplit("_", 1)[0] in bad else ""
        return ""
    counts = result["full_counts"]
    section(f"Full data comparison ({len(result['full']):,} rows listed)",
            '<div class="tiles">' + "".join(f'<div class="tile">{k.replace("_", " ").title()}<b>{v:,}</b></div>'
                                           for k, v in counts.items()) + "</div>" + _table(result["full"], full_class),
            "Differing cells red, missing/extra rows yellow." + ("" if result["include_matched"] else " Matched rows are counted, not listed."))
    section("Value mismatches", _table(result["mismatches"], lambda r, c: "bad" if c in ("column", "source", "target", "issue") else ""),
            f"{result['total_mismatch_cells']:,} mismatched cells in total.")
    section("Rows only in source", _table(result["only_in_source"]))
    section("Rows only in target", _table(result["only_in_target"]))

    body = "\n".join(parts)
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    footer = (f'<footer>Report content SHA-256: {fingerprint}<br>Generated by DataRecon v{esc(ev.get("tool_version", ""))}. '
              f'Re-hash the body to detect changes; the Excel/CSV reports carry the full data.</footer>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DataRecon evidence {esc(ev.get("run_id", ""))}</title>'
            f"<style>{_CSS}</style></head><body>{body}{footer}</body></html>").encode("utf-8")


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
def pwd_key(name):
    return f"pwd::{name}"


def get_password(config, name):
    """Session password, else the encrypted one saved with the connection."""
    key = pwd_key(name)
    if not st.session_state.get(key):
        pw = decrypt_password(config["connections"].get(name, {}).get("password_enc"))
        if pw:
            st.session_state[key] = pw
    return st.session_state.get(key, "")


def connections_panel(config):
    with st.expander("Database connections (saved locally; saved passwords are encrypted)"):
        conns = config["connections"]
        pick = st.selectbox("Load connection", [NEW] + sorted(conns), key="cx_pick")
        if st.session_state.get("cx_loaded") != pick:
            saved = conns.get(pick, {})
            for field, default in dict(name="" if pick == NEW else pick,
                                       type="PostgreSQL", host="", port=5432,
                                       database="", username="").items():
                key_map = {"type": "database_type"}
                st.session_state[f"cx_{field}"] = saved.get(key_map.get(field, field), default)
            st.session_state["cx_password"] = get_password(config, pick) if pick != NEW else ""
            st.session_state["cx_remember"] = pick == NEW or "password_enc" in saved
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
        remember = st.checkbox("Remember password (encrypted on this machine)", key="cx_remember")
        b1, b2, b3 = st.columns(3)
        if b1.button("Save connection"):
            if not name.strip() or not database.strip():
                st.error("Name and database are required.")
            else:
                if remember and password:
                    token = encrypt_password(password)
                    if token:
                        conn["password_enc"] = token
                    else:
                        st.warning("Install 'cryptography' to save passwords; kept for this session only.")
                conns[name.strip()] = conn
                save_config(config)
                st.session_state[pwd_key(name.strip())] = password
                st.success(f"Saved '{name.strip()}'" + (" with encrypted password." if "password_enc" in conn else "."))
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
            frame, digest = read_file(up, sep or ","), hashlib.sha256(up.getvalue()).hexdigest()
            info = {"input_type": "File", "name": up.name, "file_size_bytes": up.size, "sha256": digest,
                    "delimiter": sep or ",", "rows": len(frame), "columns": len(frame.columns),
                    "loaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
            return frame, up.name, digest, info
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
        frame = run_query(conns[cname], get_password(config, cname),
                          sql, int(max_rows))
        conn = conns[cname]
        info = {"input_type": "Database query", "name": f"{cname} query", "connection": cname,
                "database_type": conn["database_type"], "host": conn.get("host", ""), "port": conn.get("port", ""),
                "database": conn["database"], "username": conn.get("username", ""),
                "sql": sql.strip(), "sql_sha256": hashlib.sha256(sql.strip().encode("utf-8")).hexdigest(),
                "max_rows": int(max_rows), "rows": len(frame), "columns": len(frame.columns),
                "loaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
        return frame, f"{cname} query", None, info
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

    st.caption(f"Compared in {result['seconds']}s. Reports are built when you click a download button.")
    ev = result.get("evidence") or {}
    with st.expander(f"Run information - run {ev.get('run_id', '')} (included in every report)", expanded=True):
        for side in ("source", "target"):
            info = ev.get(side) or {}
            st.markdown(f"**{side.title()}** - {info.get('input_type', '')} - {info.get('name', '')}")
            if info.get("sql"):
                st.code(info["sql"], language="sql")
        run_info = evidence_frame(result)
        show_df(st, run_info[run_info["item"] != "SQL"].astype("string"))
    if len(result["full"]) > 200_000:
        st.caption("Large result: the CSV zip is much faster to build than the Excel report.")
    d1, d2, d3, d4 = st.columns(4)
    rid = ev.get("run_id", "run")
    run_id = id(result)  # new result -> new buttons; old prepared files are dropped
    if st.session_state.get("_dl_run") != run_id:
        st.session_state["_ready_downloads"] = {}
        st.session_state["_dl_run"] = run_id
    download(d1, "Download Excel report", lambda: build_xlsx(result), f"datarecon_report_{rid}.xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "dl_xlsx")
    download(d2, "Download CSV reports (zip)", lambda: build_csv_zip(result), f"datarecon_reports_{rid}.zip",
             "application/zip", "dl_zip")
    download(d3, "Download JSON summary", lambda: build_json(result), f"datarecon_summary_{rid}.json",
             "application/json", "dl_json")
    download(d4, "Download evidence report (HTML)", lambda: build_html(result),
             f"datarecon_evidence_{rid}.html", "text/html", "dl_html")

    def paint(columns, color):
        return lambda row: [f"background-color: {color}" if c in columns else "" for c in row.index]

    def table(title, frame, note="", style=None):
        st.subheader(f"{title} ({len(frame):,})")
        if note:
            st.caption(note)
        if len(frame) > DISPLAY_ROWS:
            st.caption(f"Showing first {DISPLAY_ROWS:,} of {len(frame):,}; downloads contain every row.")
        view = frame.head(DISPLAY_ROWS).astype("string").fillna("<NULL>")
        try:  # highlighting needs jinja2; fall back to a plain grid
            shown = view.style.apply(style, axis=1) if style and len(view) else view
        except (ImportError, AttributeError):
            shown = view
        show_df(st, shown)

    table("Checks", result["checks"])
    if len(result["insights"]):
        st.subheader("Why do rows differ?")
        for f in result["insights"].itertuples():
            st.markdown(f"- **{f.column}** ({f.rows:,} rows): {f.finding}")
    if result["fast"]:
        st.info("Full data validation only: profiling, data types, aggregations and distributions were skipped.")
    if not result["columns"].empty:
        table("Column profile", result["columns"],
              "Null / distinct / numeric-sum totals and mismatches per column.")
    if not result["nulls"].empty:
        tokens = ", ".join(result["null_tokens"]) or "none"
        table("Null / NA details", result["nulls"],
              f"Real NULL, blank text and NULL-equivalent tokens ({tokens}) are all treated as NULL when comparing. "
              "NULL->value / value->NULL count matched rows where only one side is NULL.")
    if not result["fast"]:
        table("Data types", result["dtypes"],
              "Inferred from values (comparable across file and DB); WARN = compatible, e.g. integer vs decimal.")
        table("Aggregations on critical columns", result["aggregations"],
              "Count, distinct, sum, avg, min, max per column; tolerance applies to numeric metrics.")
    if (result["schema"]["status"] != "On both sides").any():
        table("Schema differences",
              result["schema"][result["schema"]["status"] != "On both sides"])
    if len(result["groups"]):
        table("Row counts by group", result["groups"])
    if len(result["distribution"]):
        table("Value distribution differences", result["distribution"],
              "Low-cardinality columns (<= 50 distinct): values whose counts differ.")
    full = result["full"]
    st.subheader(f"Full data comparison ({len(full):,} rows)")
    counts = pd.Series(result["full_counts"])
    cols = st.columns(4)
    for c, name in zip(cols, ("MATCHED", "MISMATCH", "MISSING_IN_TARGET", "EXTRA_IN_TARGET")):
        c.metric(name.replace("_", " ").title(), f"{int(counts.get(name, 0)):,}")
    if not result["include_matched"]:
        st.caption("Matched rows are not listed (counted only). Tick 'Include matched rows' in the rules to list them.")
    shown_status = sorted(full["status"].unique())
    chosen = st.multiselect("Show statuses", shown_status, default=shown_status, key="full_status")
    view = full[full["status"].isin(chosen)]
    if len(view) > DISPLAY_ROWS:
        st.caption(f"Showing first {DISPLAY_ROWS:,} of {len(view):,}; the Excel/CSV download has every row.")
    view = view.head(DISPLAY_ROWS).astype("string").fillna("<NULL>")

    def highlight(row):
        bad = {c.strip() for c in row["mismatched_columns"].split(",") if c.strip()}
        return ["background-color: #ffd6d6" if c.rsplit("_", 1)[0] in bad and c.endswith(("_source", "_target"))
                else "background-color: #fff3c4" if row["status"] in ("MISSING_IN_TARGET", "EXTRA_IN_TARGET")
                and c.endswith(("_source", "_target")) else "" for c in row.index]
    try:  # cell highlighting needs jinja2; fall back to a plain grid
        shown = view.style.apply(highlight, axis=1) if len(view.columns) < 60 else view
    except (ImportError, AttributeError):
        shown = view
    show_df(st, shown)
    for label, key in (("Duplicate records in source", "dup_source"), ("Duplicate records in target", "dup_target")):
        if len(result[key]):
            table(label, result[key], "Every row whose key appears more than once, with group size and occurrence #.",
                  paint({"duplicate_count", "occurrence"}, "#f8cbad"))
    table("Value mismatches", result["mismatches"],
          f"{result['total_mismatch_cells']:,} mismatched cells in total. 'issue' tells NULL vs value apart from value differences."
          + (" Detail capped at 100,000 rows." if result["mismatches_capped"] else ""),
          paint({"column", "source", "target", "issue"}, "#ffd6d6"))
    table("Rows only in source", result["only_in_source"])
    table("Rows only in target", result["only_in_target"])


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
                src, sname, shash, sinfo = load_src()
                tgt, tname, thash, tinfo = load_tgt()
            hashes = (shash, thash) if shash and thash else None
            st.session_state["data"] = (src, tgt, (sname, tname), hashes, (sinfo, tinfo))
        except Exception as err:
            st.session_state.pop("data", None)
            st.error(f"Could not load data: {err}")

    data = st.session_state.get("data")
    if not data:
        st.info("Choose a source and a target, then press Load data.")
        return
    src, tgt, names, hashes, infos = data
    p1, p2 = st.columns(2)
    for col, frame, name in ((p1, src, names[0]), (p2, tgt, names[1])):
        col.caption(f"{name}: {len(frame):,} rows x {len(frame.columns)} columns")
        show_df(col, frame.head(10).astype("string"))

    st.header("2 - Rules")
    norm = lambda df: [str(c).strip().lower() for c in df.columns]
    common = [c for c in norm(src) if c in set(norm(tgt))]
    every = sorted(set(norm(src)) | set(norm(tgt)))
    defaults = {"r_keys": [c for c in common if c in ("id", "pk")][:1], "r_ignore": [],
                "r_agg": [], "r_group": [], "r_trim": True, "r_empty": True, "r_case": False,
                "r_tol": 0.0, "r_fast": False, "r_matched": False, "r_nulltok": DEFAULT_NULL_TOKENS, "r_markers": DEFAULT_MARKERS, "r_cnt_abs": 0, "r_cnt_pct": 0.0}
    rules = config["rules"]
    pick = st.selectbox("Saved rule set", [""] + sorted(rules), format_func=lambda n: n or "-- none --")
    if st.session_state.get("r_loaded") != pick or "r_trim" not in st.session_state:
        for k, v in {**defaults, **rules.get(pick, {})}.items():
            if isinstance(v, list):  # drop columns this dataset doesn't have
                v = [c for c in v if c in every]
            st.session_state[k] = v
        st.session_state["r_loaded"] = pick

    m = st.columns(2)
    fast = m[0].checkbox("Full data validation only (fast: skips profiling, data types, aggregations, distributions)",
                         key="r_fast")
    inc_matched = m[1].checkbox("Include matched rows in the full-data result (slower, large exports)",
                                key="r_matched")
    keys = st.multiselect("Key column(s) - blank compares whole rows as a set", common, key="r_keys")
    ignore = st.multiselect("Ignore columns (audit timestamps, surrogate keys...)", every, key="r_ignore")
    agg_cols = st.multiselect("Critical columns for aggregations (blank = all numeric columns)",
                              common, key="r_agg")
    group_by = st.multiselect("Row counts by group (optional, e.g. region, load date)", common, key="r_group")
    o = st.columns(4)
    trim = o[0].checkbox("Trim whitespace", key="r_trim")
    empty_null = o[1].checkbox("Treat empty text as NULL", key="r_empty")
    nocase = o[2].checkbox("Ignore value case", key="r_case")
    tol = o[3].number_input("Numeric tolerance", 0.0, format="%g", step=0.01, key="r_tol")
    c = st.columns(3)
    markers = c[0].text_input("Missing-value markers (counted as incomplete)", key="r_markers")
    cnt_abs = c[1].number_input("Row-count tolerance (rows)", 0, key="r_cnt_abs")
    cnt_pct = c[2].number_input("Row-count tolerance (%)", 0.0, format="%g", key="r_cnt_pct")

    nulltok = st.text_input("Treat these values as NULL when comparing (comma-separated, case-insensitive; blank = off)",
                            key="r_nulltok")

    r1, r2 = st.columns([3, 1])
    save_as = r1.text_input("Save these rules as", label_visibility="collapsed", placeholder="Save rules as…")
    if r2.button("Save rules") and save_as.strip():
        rules[save_as.strip()] = {k: st.session_state[k] for k in defaults}
        save_config(config)
        st.toast(f"Saved rules '{save_as.strip()}'")

    if st.button("Run comparison", type="primary"):
        try:
            with st.spinner("Comparing..."):
                st.session_state["result"] = compare(
                    src, tgt, keys, ignore, trim, empty_null, nocase, tol,
                    agg_cols=agg_cols, markers=markers.split(","), count_tol_abs=cnt_abs,
                    count_tol_pct=cnt_pct, group_by=group_by, file_hashes=hashes,
                    fast=fast, include_matched=inc_matched,
                    null_tokens=nulltok.split(","),
                    evidence=new_evidence(infos[0], infos[1], {
                        "keys": keys or "(whole row)", "ignored columns": ignore or "(none)",
                        "aggregation columns": agg_cols or "(all numeric)", "group by": group_by or "(none)",
                        "trim whitespace": trim, "empty text is NULL": empty_null, "ignore value case": nocase,
                        "numeric tolerance": tol, "values treated as NULL": nulltok or "(off)",
                        "missing-value markers": markers, "row-count tolerance (rows)": cnt_abs,
                        "row-count tolerance (%)": cnt_pct, "full data validation only": fast,
                        "matched rows listed": inc_matched}))
        except Exception as err:
            st.session_state.pop("result", None)
            st.error(f"Comparison failed: {err}")

    if "result" in st.session_state:
        st.header("3 - Results")
        show_result(st.session_state["result"], names)


if __name__ == "__main__":
    main()
