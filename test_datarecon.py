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
