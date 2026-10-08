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
