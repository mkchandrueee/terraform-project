import pandas as pd
from datarecon import compare


def frames():
    src = pd.DataFrame({"ID": [1, 2, 3, 4], "Name": ["a", "b ", "c", "d"],
                        "Amt": ["10.50", "20", "30", None], "Dt": pd.to_datetime(["2024-01-01"] * 4)})
    tgt = pd.DataFrame({"id": ["4", "3", "2", "5"], "name": ["d", "X", "b", "e"],
                        "amt": [None, "30.0", "20.001", "1"], "dt": ["2024-01-01"] * 4})
    return src, tgt


def test_key_compare_ignores_order_and_finds_diffs():
    r = compare(*frames(), keys=["id"])
    assert len(r["only_in_source"]) == 1 and r["only_in_source"].id[0] == "1"
    assert len(r["only_in_target"]) == 1 and r["only_in_target"].id[0] == "5"
    m = r["mismatches"]
    assert set(zip(m.id, m.column)) == {("3", "name"), ("2", "amt")}
    assert not r["passed"]


def test_tolerance_and_ignore():
    r = compare(*frames(), keys=["id"], tol=0.01, ignore=["name"])
    assert r["total_mismatch_cells"] == 0


def test_identical_passes_and_row_mode():
    src, _ = frames()
    assert compare(src, src.sample(frac=1), keys=["id"])["passed"]
    assert compare(src, src.sample(frac=1))["passed"]
    dup = pd.concat([src, src.head(1)])
    r = compare(src, dup)
    assert len(r["only_in_target"]) == 1


def test_extra_validations():
    src, tgt = frames()
    r = compare(src, tgt, keys=["id"])
    checks = dict(zip(r["checks"].check, r["checks"].status))
    assert checks["Column count"] == "PASS"
    assert checks["Aggregation differences"] == "FAIL"
    dt = r["dtypes"].set_index("column")
    assert dt.loc["amt", "source_type"] == "decimal" and dt.loc["id", "status"] == "PASS"
    agg = r["aggregations"]
    assert {"sum", "avg", "min", "max", "count", "distinct"} <= set(agg.metric)
    assert compare(src, src, keys=["id"], agg_cols=["amt"])["passed"]
    dup = pd.concat([src, src.head(1)])
    c = dict(zip(*[compare(dup, src)["checks"][k] for k in ("check", "status")]))
    assert c["Duplicate full rows"] == "FAIL"


def test_enhancements():
    src = pd.DataFrame({"id": range(1, 11), "amt": [i * 1.0 for i in range(1, 11)],
                        "nm": ["Ab"] * 10, "grp": ["x"] * 5 + ["y"] * 5, "n": ["N/A"] + ["v"] * 9})
    tgt = src[src.id <= 7].copy()                      # ids 8-10 missing: contiguous block
    tgt["amt"] = tgt["amt"] * 100                      # exact 100x
    tgt["nm"] = tgt["nm"].str.lower()                  # case only
    r = compare(src, tgt, keys=["id"], group_by=["grp"], count_tol_pct=50,
                file_hashes=("a" * 64, "b" * 64))
    text = " | ".join(r["insights"].finding)
    assert "100x" in text and "letter case" in text and "contiguous key block" in text
    chk = dict(zip(r["checks"].check, r["checks"].status))
    assert chk["Row count"] == "PASS" and chk["File checksum (SHA-256) identical"] == "WARN"
    assert (r["groups"].difference.tolist().count(-3)) == 1
    r2 = compare(src, src, keys=["id"], markers=["n/a"])
    assert r2["passed"] and r2["columns"].set_index("column").loc["n", "source_markers"] == 1


def test_exports_split_not_truncate(monkeypatch):
    import datarecon
    monkeypatch.setattr(datarecon, "EXPORT_ROW_CAP", 5)
    src = pd.DataFrame({"id": range(12), "v": ["a"] * 12})
    r = compare(src, src.assign(v="b"), keys=["id"])
    import io, zipfile
    names = zipfile.ZipFile(io.BytesIO(datarecon.build_exports(r)[1])).namelist()
    assert {"mismatches_1.csv", "mismatches_2.csv", "mismatches_3.csv"} <= set(names)


def test_full_data_result():
    src, tgt = frames()
    r = compare(src, tgt, keys=["id"])
    assert "4" not in set(r["full"].id) and r["full_counts"]["MATCHED"] == 1  # matched rows opt-in
    full = compare(src, tgt, keys=["id"], include_matched=True)["full"].set_index("id")
    assert full.status.to_dict() == {"1": "MISSING_IN_TARGET", "5": "EXTRA_IN_TARGET",
                                     "2": "MISMATCH", "3": "MISMATCH", "4": "MATCHED"}
    assert compare(src, tgt, keys=["id"], fast=True)["full_counts"] == r["full_counts"]
    assert full.loc["3", "mismatched_columns"] == "name"
    assert full.loc["3", "name_source"] == "c" and full.loc["3", "name_target"] == "X"


def test_matches_bruteforce_reference():
    """Optimised engine == naive pairing by (key, occurrence), incl. duplicate and text keys."""
    import numpy as np
    from collections import defaultdict
    rng = np.random.default_rng(7)
    for int_keys in (True, False):
        mk = (lambda n: [str(x) for x in rng.integers(0, 40, n)]) if int_keys else \
             (lambda n: [f"k{x}" for x in rng.integers(0, 40, n)])
        src = pd.DataFrame({"k": mk(60), "v": rng.integers(0, 3, 60).astype(str)})
        tgt = pd.DataFrame({"k": mk(55), "v": rng.integers(0, 3, 55).astype(str)})

        def pairs(df):
            seen, out = defaultdict(int), {}
            for k, v in zip(df.k, df.v):
                out[(k, seen[k])] = v
                seen[k] += 1
            return out
        a, b = pairs(src), pairs(tgt)
        exp = {"MISSING_IN_TARGET": len(a.keys() - b.keys()), "EXTRA_IN_TARGET": len(b.keys() - a.keys()),
               "MISMATCH": sum(a[x] != b[x] for x in a.keys() & b.keys()),
               "MATCHED": sum(a[x] == b[x] for x in a.keys() & b.keys())}
        for fast in (False, True):
            assert compare(src, tgt, keys=["k"], fast=fast)["full_counts"] == exp


def test_duplicates_listed():
    src = pd.DataFrame({"id": ["1", "2", "2", "3", "3", "3"], "v": list("abcdef")})
    tgt = pd.DataFrame({"id": ["1", "2", "3"], "v": list("abd")})
    r = compare(src, tgt, keys=["id"])
    d = r["dup_source"]
    assert list(d.id) == ["2", "2", "3", "3", "3"]
    assert list(d.duplicate_count) == [2, 2, 3, 3, 3] and list(d.occurrence) == [1, 2, 1, 2, 3]
    assert r["dup_target"].empty
    assert "Duplicates Source" in __import__("datarecon").export_parts(r)


def test_null_handling_and_details():
    src = pd.DataFrame({"id": ["1", "2", "3", "4"], "a": ["NULL", "x", None, "N/A"], "b": ["", "y", "z", "q"]})
    tgt = pd.DataFrame({"id": ["1", "2", "3", "4"], "a": [None, "x", "val", None], "b": [None, "y", None, "q"]})
    r = compare(src, tgt, keys=["id"], null_tokens=["null", "n/a"])
    assert r["total_mismatch_cells"] == 2          # row3 a (NULL->value) and row3 b (value->NULL)
    issues = dict(zip(r["mismatches"].column, r["mismatches"].issue))
    assert issues == {"a": "NULL -> value", "b": "value -> NULL"}
    n = r["nulls"].set_index("column")
    assert n.loc["a", "source_null_token"] == 2 and n.loc["a", "source_real_null"] == 1
    assert n.loc["b", "source_blank"] == 1 and n.loc["a", "source_NULL->target_value"] == 1
    # without tokens the literal strings differ from real NULLs
    assert compare(src, tgt, keys=["id"])["total_mismatch_cells"] > 2


def test_excel_highlight_rules():
    import io, openpyxl, datarecon
    src, tgt = frames()
    r = compare(src, tgt, keys=["id"])
    wb = openpyxl.load_workbook(io.BytesIO(datarecon.build_xlsx(r)))
    for sheet in ("Full Data", "Mismatches", "Checks"):
        assert len(wb[sheet].conditional_formatting) > 0, sheet
    formulas = [f for cf in wb["Full Data"].conditional_formatting for rule in cf.rules for f in rule.formula]
    assert any("SEARCH" in f and "mismatched" not in f for f in formulas)


def test_password_encryption_roundtrip(tmp_path, monkeypatch):
    import datarecon
    monkeypatch.setattr(datarecon, "KEY_FILE", tmp_path / "k.key")
    token = datarecon.encrypt_password("s3cret!")
    assert token and "s3cret" not in token
    assert datarecon.decrypt_password(token) == "s3cret!"
    assert oct((tmp_path / "k.key").stat().st_mode & 0o777) == "0o600"
    (tmp_path / "k.key").unlink()                      # key lost -> safely empty, no crash
    monkeypatch.setattr(datarecon, "KEY_FILE", tmp_path / "other.key")
    assert datarecon.decrypt_password(token) == ""


def _evidence():
    import datarecon
    src_info = {"input_type": "Database query", "name": "legacy query", "connection": "legacy", "database_type": "PostgreSQL",
                "host": "h1", "database": "old", "username": "etl", "sql": "SELECT * FROM old.customers ORDER BY id",
                "rows": 4, "columns": 4}
    tgt_info = {"input_type": "Database query", "name": "new query", "connection": "new", "database_type": "SQL Server",
                "host": "h2", "database": "new", "username": "etl2", "sql": "SELECT * FROM dbo.customers ORDER BY id"}
    return datarecon.new_evidence(src_info, tgt_info, {"keys": ["id"], "numeric tolerance": 0.0})


def test_sql_and_run_info_in_every_report():
    import io, json, zipfile, openpyxl, datarecon
    src, tgt = frames()
    r = compare(src, tgt, keys=["id"], evidence=_evidence())
    wb = openpyxl.load_workbook(io.BytesIO(datarecon.build_xlsx(r)))
    assert wb.sheetnames[0] == "Run Info"
    cells = " ".join(str(c.value) for row in wb["Run Info"].iter_rows() for c in row)
    assert "SELECT * FROM old.customers ORDER BY id" in cells and "SELECT * FROM dbo.customers ORDER BY id" in cells
    z = zipfile.ZipFile(io.BytesIO(datarecon.build_csv_zip(r)))
    assert "SELECT * FROM dbo.customers" in z.read("run_info.csv").decode("utf-8-sig")
    js = json.loads(datarecon.build_json(r))
    assert js["evidence"]["source"]["sql"].startswith("SELECT * FROM old") and js["evidence"]["target"]["host"] == "h2"


def test_html_evidence_report():
    import datarecon, hashlib, re
    src = pd.DataFrame({"id": ["1", "2", "2", "3"], "name": ["a", "<script>alert(1)</script>", "b", "c"]})
    tgt = pd.DataFrame({"id": ["1", "2", "3"], "name": ["a", "x", None]})
    r = compare(src, tgt, keys=["id"], evidence=_evidence())
    doc = datarecon.build_html(r).decode()
    assert "SELECT * FROM old.customers ORDER BY id" in doc and "SELECT * FROM dbo.customers ORDER BY id" in doc
    assert "<script>alert(1)" not in doc and "&lt;script&gt;" in doc            # values are escaped
    assert 'class="bad"' in doc and 'class="dup"' in doc and 'class="null"' in doc
    assert r["evidence"]["run_id"] in doc
    body = doc.split("<body>")[1].split("<footer>")[0]
    assert hashlib.sha256(body.encode()).hexdigest() in doc                      # content fingerprint


def _zip_text(blob):
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(blob))
    return " ".join(z.read(n).decode("utf-8-sig") for n in z.namelist())


def test_no_password_in_evidence():
    import datarecon
    ev = datarecon.new_evidence({"name": "s", "password_enc": "SECRET-TOKEN", "db_password": "SECRET-TOKEN"},
                                {"name": "t"}, {})
    r = compare(*frames(), keys=["id"], evidence=ev)
    for blob in (datarecon.evidence_frame(r).to_string(), datarecon.build_html(r).decode(),
                 datarecon.build_json(r).decode(), _zip_text(datarecon.build_csv_zip(r))):
        assert "SECRET-TOKEN" not in blob


def test_full_result_shows_occurrence_for_duplicate_keys_and_int_counts():
    src = pd.DataFrame({"id": ["1", "2", "2"], "v": ["a", "b", "b"]})
    tgt = pd.DataFrame({"id": ["1", "2"], "v": ["a", "b"]})
    r = compare(src, tgt, keys=["id"])
    row = r["full"].iloc[0]
    assert row["status"] == "MISSING_IN_TARGET" and row["id"] == "2" and row["occurrence"] == 2
    counts = r["aggregations"].query("metric == 'count'")
    assert all(isinstance(v, int) for v in counts["source"])


def test_lost_leading_zeros_are_mismatches_but_decimal_formatting_is_not():
    src = pd.DataFrame({"id": ["1", "2", "3", "4"], "zip": ["02134", "10001", "00501", "7"], "amt": ["10.50", "1", "2", "3"]})
    tgt = pd.DataFrame({"id": ["1", "2", "3", "4"], "zip": ["2134", "10001", "501", "7"], "amt": ["10.5", "1.0", "2", "3"]})
    r = compare(src, tgt, keys=["id"])
    assert sorted(zip(r["mismatches"].id, r["mismatches"].column)) == [("1", "zip"), ("3", "zip")]


def test_leading_zero_explanation_is_not_called_rounding():
    src = pd.DataFrame({"id": list("abcd"), "zip": ["02134", "00501", "07001", "10001"]})
    tgt = pd.DataFrame({"id": list("abcd"), "zip": ["2134", "501", "7001", "10001"]})
    text = " ".join(compare(src, tgt, keys=["id"])["insights"].finding)
    assert "Leading zeros lost" in text and "rounded" not in text


# ---------------------------------------------------------------- default connections (config file)
def _write_cfg(path, **extra):
    import json
    cfg = {"connections": {
        "Legacy (default)": {"database_type": "SQLite", "database": "/tmp/legacy.db"},
        "PG default": {"database_type": "PostgreSQL", "host": "h", "database": "d", "username": "u", "password_env": "EQ_TEST_PW"},
        "Broken": {"database_type": "Oracle", "database": "x"},
        "NoDb": {"database_type": "SQLite"}},
        "default_source_connection": "Legacy (default)", **extra}
    path.write_text(json.dumps(cfg))


def test_default_connections_load_merge_and_are_never_saved(tmp_path, monkeypatch):
    import json, datarecon
    cfg = tmp_path / "equaliser_config.json"
    _write_cfg(cfg)
    monkeypatch.setenv("EQUALISER_CONFIG", str(cfg))
    monkeypatch.setattr(datarecon, "PROFILE_FILE", tmp_path / "profile.json")
    (tmp_path / "profile.json").write_text(json.dumps({"connections": {"Mine": {"database_type": "SQLite", "database": "m.db"}}}))
    c = datarecon.load_config()
    assert {"Legacy (default)", "PG default", "Mine"} <= set(c["connections"])
    assert "Broken" not in c["connections"] and "NoDb" not in c["connections"]            # invalid entries skipped...
    assert len(c["_defaults_problems"]) == 2                                              # ...and reported
    assert c["_default_names"]["connections"] == {"Legacy (default)", "PG default"}
    assert c["_default_source"] == "Legacy (default)" and c["connections"]["PG default"]["port"] == 5432
    datarecon.save_config(c)                                                              # defaults must stay out of the user profile
    saved = json.loads((tmp_path / "profile.json").read_text())
    assert set(saved["connections"]) == {"Mine"} and not any(k.startswith("_") for k in saved)


def test_default_connection_password_sources(tmp_path, monkeypatch):
    import datarecon
    monkeypatch.setattr(datarecon, "KEY_FILE", tmp_path / "k.key")
    monkeypatch.setenv("EQ_TEST_PW", "from-env")
    assert datarecon.resolve_conn_password({"password_env": "EQ_TEST_PW", "password": "plain"}) == "from-env"   # env wins
    token = datarecon.encrypt_password("from-token")
    assert datarecon.resolve_conn_password({"password_env": "NOT_SET_ANYWHERE", "password_enc": token}) == "from-token"
    assert datarecon.resolve_conn_password({"password": "plain"}) == "plain"
    assert datarecon.resolve_conn_password({}) == ""


def test_missing_config_is_not_an_error(tmp_path, monkeypatch):
    import datarecon
    monkeypatch.delenv("EQUALISER_CONFIG", raising=False)
    monkeypatch.setattr(datarecon, "PROFILE_FILE", tmp_path / "none.json")
    monkeypatch.setenv("EQUALISER_CONFIG", str(tmp_path / "absent.json"))
    c = datarecon.load_config()
    assert c["connections"] == {} and "not found" in c["_defaults_problems"][0]


# ---------------------------------------------------------------- batch: many queries in one run
def _batch_dbs(tmp_path):
    import sqlite3
    src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
    a = pd.DataFrame({"id": [1, 2, 3, 4], "name": ["a", "b", "c", "d"], "amt": [10.0, 20.0, 30.0, 40.0]})
    for path, frame in ((src, a), (tgt, a.assign(name=["a", "B", "c", "d"]))):
        con = sqlite3.connect(path); frame.to_sql("t", con, index=False); a.assign(amt=1.0).to_sql("u", con, index=False); con.close()
    conns = {"S": {"database_type": "SQLite", "database": str(src)}, "T": {"database_type": "SQLite", "database": str(tgt)}}
    return conns


def _tests():
    row = lambda name, ssql, tsql, keys="id", ignore="": {"test": name, "source_connection": "S", "source_sql": ssql,
                                                          "target_connection": "T", "target_sql": tsql, "keys": keys, "ignore": ignore}
    return [row("same table", "SELECT * FROM u ORDER BY id", "SELECT * FROM u ORDER BY id"),
            row("name differs", "SELECT * FROM t", "SELECT * FROM t"),
            row("bad sql", "SELECT * FROM missing_table", "SELECT * FROM t"),
            row("ignored column", "SELECT * FROM t", "SELECT * FROM t", ignore="name")]


def test_parse_tests_reports_every_problem():
    import datarecon
    bad = pd.DataFrame([{"test": "a", "source_connection": "S", "source_sql": "", "target_connection": "T", "target_sql": "x"},
                        {"test": "a", "source_connection": "S", "source_sql": "q", "target_connection": "", "target_sql": "x"}])
    try:
        datarecon.parse_tests(bad)
        raise AssertionError("expected ValueError")
    except ValueError as err:
        text = str(err)
    assert "Row 1: 'source_sql' is empty" in text and "Row 2: 'target_connection' is empty" in text and "duplicate test name 'a'" in text
    try:
        datarecon.parse_tests(pd.DataFrame({"test": ["x"]}))
        raise AssertionError("expected ValueError")
    except ValueError as err:
        assert "Missing column(s)" in str(err)


def test_run_batch_isolates_errors_and_reports_each_test(tmp_path):
    import datarecon
    conns, progress = _batch_dbs(tmp_path), []
    tests = datarecon.parse_tests(pd.DataFrame(_tests()))
    batch = datarecon.run_batch(tests, conns, lambda name: "", progress=lambda d, t, n: progress.append((d, t)))
    status = {r["test"]: r["status"] for r in batch["records"]}
    assert status == {"same table": "PASS", "name differs": "FAIL", "bad sql": "ERROR", "ignored column": "PASS"}   # error did not stop the run
    assert "missing_table" in [r for r in batch["records"] if r["test"] == "bad sql"][0]["error"]
    assert progress[0] == (0, 4) and progress[-1] == (4, 4)
    s = datarecon.batch_summary(batch).set_index("test")
    assert s.loc["name differs", "mismatched_cells"] == 1 and s.loc["same table", "mismatched_cells"] == 0
    assert "OperationalError" in s.loc["bad sql", "error"]


def test_combined_workbook_has_every_test_and_every_sql(tmp_path):
    import io, openpyxl, datarecon
    batch = datarecon.run_batch(datarecon.parse_tests(pd.DataFrame(_tests())), _batch_dbs(tmp_path), lambda n: "")
    wb = openpyxl.load_workbook(io.BytesIO(datarecon.build_batch_xlsx(batch)))
    assert wb.sheetnames[:2] == ["Batch Summary", "Batch Run Info"]
    assert {"All Checks", "All Mismatches", "T02 Full Data"} <= set(wb.sheetnames)
    assert "T01 Full Data" not in wb.sheetnames and "T04 Full Data" not in wb.sheetnames   # passing tests have no differing rows to list
    assert "T03 Full Data" not in wb.sheetnames                                      # the errored test has no result to detail
    summary = {r[1]: r[-1] for r in wb["Batch Summary"].iter_rows(min_row=2, values_only=True)}
    assert summary["name differs"] == "T02 Full Data" and not summary["same table"]  # summary names only sheets that exist
    info = " ".join(str(c.value) for row in wb["Batch Run Info"].iter_rows() for c in row)
    for sql in ("SELECT * FROM u ORDER BY id", "SELECT * FROM missing_table"):      # both SQLs, including the failed test's
        assert sql in info
    assert "same table" in info and "bad sql" in info and "Batch ID" in info
    mism = list(wb["All Mismatches"].iter_rows(values_only=True))
    assert mism[0][:3] == ("test", "key", "column") and mism[1][0] == "name differs" and mism[1][1] == "id=2"
    assert len(wb["Batch Summary"].conditional_formatting) > 0 and len(wb["All Mismatches"].conditional_formatting) > 0
    lean = openpyxl.load_workbook(io.BytesIO(datarecon.build_batch_xlsx(batch, detail_sheets=False)))
    assert not any(n.endswith("Full Data") for n in lean.sheetnames)


def test_batch_html_and_json(tmp_path):
    import json, hashlib, datarecon
    batch = datarecon.run_batch(datarecon.parse_tests(pd.DataFrame(_tests())), _batch_dbs(tmp_path), lambda n: "")
    doc = datarecon.build_batch_html(batch).decode()
    assert "Batch Evidence Report" in doc and "ATTENTION" in doc and doc.count("<details>") == 4
    assert "SELECT * FROM missing_table" in doc and "OperationalError" in doc
    body = doc.split("<body>")[1].split("<footer>")[0]
    assert hashlib.sha256(body.encode()).hexdigest() in doc
    js = json.loads(datarecon.build_batch_json(batch))
    assert [t["status"] for t in js["tests"]] == ["PASS", "FAIL", "ERROR", "PASS"] and js["summary"][1]["mismatched_cells"] == 1


def test_large_stacked_sheets_split_never_truncate(monkeypatch, tmp_path):
    import datarecon
    monkeypatch.setattr(datarecon, "EXPORT_ROW_CAP", 3)
    batch = datarecon.run_batch(datarecon.parse_tests(pd.DataFrame(_tests()[:1])), _batch_dbs(tmp_path), lambda n: "")
    parts = datarecon._batch_parts(batch)
    checks = [n for n in parts if n.startswith("All Checks")]
    assert len(checks) > 1 and sum(len(parts[n][1]) for n in checks) == len(batch["records"][0]["result"]["checks"])


def test_plaintext_password_in_config_is_flagged(tmp_path, monkeypatch):
    import json, datarecon
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"connections": {"X": {"database_type": "SQLite", "database": "x.db", "password": "hunter2"}}}))
    monkeypatch.setenv("EQUALISER_CONFIG", str(cfg))
    defaults, path, problems = datarecon.load_default_config()
    assert "X" in defaults["connections"] and any("plain-text password" in p for p in problems)
    assert "hunter2" not in " ".join(problems)                  # the warning never echoes the secret
