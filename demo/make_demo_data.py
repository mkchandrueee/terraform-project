"""Build the DataRecon client-demo kit (deterministic, ~seconds).

    python demo/make_demo_data.py            # 50,000-customer migration + demo profile
    python demo/make_demo_data.py --big      # also a 900,000-row pair for the performance moment

Creates, under demo/data/:
  legacy.db   table customers                 (the "source" system)
  new.db      table customers                 (the migrated target - with planted defects)
              table customers_clean           (a faithful, reshuffled copy -> PASS scenario)
  customers_legacy.csv / customers_new.csv    (same data as files, for File-to-File / File-to-SQL)
and demo/.demo_profile.json with saved connections, queries and rule sets, so the demo never
touches your real ~/.datarecon_profiles.json.

PLANTED DEFECTS (target vs source) - one per column so each finding is clean:
  customer_id 49961-50000 missing (40 rows)  -> partial-load key block
  5 extra customers (90001-90005)            -> extra rows
  12 customers loaded twice                  -> duplicate records
  credit_limit  x100 on 75 rows              -> "exactly 100x" (units/scale)
  name          UPPERCASED on 200 rows       -> "differ only by letter case"
  phone         cut to 10 chars on 80 rows   -> truncation
  city          NULL in target on 60 rows    -> NULL -> value
  city          source 'N/A' / target NULL (30 rows) -> equal (NULL-token handling)
  zip_code      leading zero lost on 30 rows -> mismatch (02134 vs 2134)
  balance       rounded to 0 decimals, 90    -> "rounded to 0 decimal places"
  signup_ts     +5h30 on 100 rows            -> timezone shift
  segment       GOLD -> PREMIUM on 40 rows   -> value-distribution difference (code remap)
  email         trailing spaces on 150 rows  -> ignored by 'Trim whitespace' (noise, not a defect)
  etl_loaded_at differs on every row         -> use 'Ignore columns'
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
PROFILE = HERE / ".demo_profile.json"
N = 50_000
FIRST = ["Aarav", "Diya", "Rohan", "Meera", "Kabir", "Isha", "Arjun", "Sana", "Vikram", "Anaya", "Nikhil", "Priya"]
LAST = ["Sharma", "Iyer", "Khan", "Patel", "Reddy", "Nair", "Gupta", "Mehta", "Das", "Joshi", "Rao", "Singh"]
CITIES = ["Pune", "Mumbai", "Chennai", "Delhi", "Bengaluru", "Hyderabad", "Kolkata", "Ahmedabad"]
SEGMENTS = ["GOLD", "SILVER", "BRONZE"]


def build_legacy(n=N, seed=42):
    rng = np.random.default_rng(seed)
    ids = np.arange(1, n + 1)
    first, last = rng.choice(FIRST, n), rng.choice(LAST, n)
    zips = rng.integers(0, 99999, n)
    zip_text = np.array([f"{z:05d}" for z in zips])
    zip_text[rng.choice(n, 2000, replace=False)] = np.array([f"0{z:04d}" for z in rng.integers(0, 9999, 2000)])
    base = pd.Timestamp("2020-01-01")
    df = pd.DataFrame({
        "customer_id": ids,
        "name": [f"{a} {b}" for a, b in zip(first, last)],
        "email": [f"{a}.{b}{i}@example.com".lower() for a, b, i in zip(first, last, ids)],
        "phone": [f"+91-98{rng.integers(10000000, 99999999)}" for _ in range(n)],
        "city": rng.choice(CITIES, n),
        "zip_code": zip_text,
        "segment": rng.choice(SEGMENTS, n, p=[0.2, 0.5, 0.3]),
        "credit_limit": rng.integers(1, 200, n) * 1000,
        "balance": np.round(rng.uniform(0.5, 90000, n), 2),
        "signup_ts": (base + pd.to_timedelta(rng.integers(0, 1500 * 24 * 3600, n), unit="s")).strftime("%Y-%m-%d %H:%M:%S"),
        "etl_loaded_at": "2024-03-01 02:00:00",
    })
    # legacy system stored 'N/A' for unknown city on 30 rows (a different NULL spelling than the target)
    df.loc[rng.choice(n, 30, replace=False), "city"] = "N/A"
    return df


def build_target(src, seed=7):
    rng = np.random.default_rng(seed)
    t = src.copy()
    order = rng.permutation(np.flatnonzero(t["customer_id"].to_numpy() < 49_961))
    used = set()

    def pick(k, where=None):
        """k rows not used by another defect (so every finding stays clean), optionally matching `where(row_index)`."""
        chosen = []
        for i in order:
            if i not in used and (where is None or where(i)):
                chosen.append(i)
                used.add(i)
                if len(chosen) == k:
                    break
        return chosen

    t.loc[pick(75), "credit_limit"] *= 100
    rows = pick(200)
    t.loc[rows, "name"] = t.loc[rows, "name"].str.upper()
    rows = pick(80)
    t.loc[rows, "phone"] = t.loc[rows, "phone"].str[:10]
    t.loc[pick(60, lambda i: src.at[i, "city"] != "N/A"), "city"] = None
    t.loc[src.index[src["city"] == "N/A"], "city"] = None            # legacy 'N/A' -> NULL in target (equivalent)
    rows = pick(30, lambda i: t.at[i, "zip_code"].startswith("0"))
    t.loc[rows, "zip_code"] = t.loc[rows, "zip_code"].str.lstrip("0")
    rows = pick(90, lambda i: round(src.at[i, "balance"] % 1, 2) not in (0.0, 1.0))
    t.loc[rows, "balance"] = np.round(src.loc[rows, "balance"])
    rows = pick(100)
    t.loc[rows, "signup_ts"] = (pd.to_datetime(t.loc[rows, "signup_ts"]) + pd.Timedelta(hours=5, minutes=30)).dt.strftime("%Y-%m-%d %H:%M:%S")
    t.loc[pick(40, lambda i: t.at[i, "segment"] == "GOLD"), "segment"] = "PREMIUM"
    rows = pick(150)
    t.loc[rows, "email"] = t.loc[rows, "email"] + "  "                # whitespace noise (ignored by Trim)
    t["etl_loaded_at"] = "2024-09-15 23:30:00"                        # audit column differs on every row

    t = t[~t["customer_id"].between(49_961, 50_000)]                 # partial load: last 40 never arrived
    extra = t.sample(5, random_state=3).copy()
    extra["customer_id"] = np.arange(90_001, 90_006)
    dups = t.sample(12, random_state=5)                              # 12 customers loaded twice
    t = pd.concat([t, extra, dups], ignore_index=True)
    return t.sample(frac=1, random_state=11).reset_index(drop=True)  # reshuffled: order must not matter


def build_clean(src, seed=9):
    c = src.copy()
    c["etl_loaded_at"] = "2024-09-15 23:30:00"
    c["email"] = c["email"].where(~(c["customer_id"] % 97 == 0), c["email"] + " ")   # trailing-space noise only
    return c.sample(frac=1, random_state=seed).reset_index(drop=True)


def write_sqlite(path, tables):
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    for name, frame in tables.items():
        frame.to_sql(name, con, index=False)
    con.close()


def write_profile():
    conn = lambda p: {"database_type": "SQLite", "host": "", "port": 0, "database": str(p), "username": ""}
    q = lambda db: f"SELECT customer_id, name, email, phone, city, zip_code, segment, credit_limit, balance, signup_ts, etl_loaded_at\nFROM {db}\nORDER BY customer_id"
    rules = {"r_keys": ["customer_id"], "r_ignore": ["etl_loaded_at"], "r_agg": ["credit_limit", "balance"],
             "r_group": ["segment"], "r_trim": True, "r_empty": True, "r_case": False, "r_tol": 0.0,
             "r_fast": False, "r_matched": False, "r_nulltok": "NULL, None, NaN, N/A, #N/A",
             "r_markers": "N/A, NA, NULL, None, -, -999, 1900-01-01", "r_cnt_abs": 0, "r_cnt_pct": 0.0}
    profile = {
        "connections": {"Legacy system (demo)": conn(DATA / "legacy.db"), "New platform (demo)": conn(DATA / "new.db")},
        "queries": {"1 Legacy customers": q("customers"), "2 New customers (migrated)": q("customers"),
                    "3 New customers (clean copy)": q("customers_clean")},
        "rules": {"Customer migration": rules, "Customer migration - full data only (fast)": {**rules, "r_fast": True}},
    }
    PROFILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


def write_big(n=900_000, seed=1):
    rng = np.random.default_rng(seed)
    src = pd.DataFrame({"txn_id": np.arange(n), "account": rng.integers(10**6, 10**7, n).astype(str),
                        "amount": np.round(rng.uniform(1, 5000, n), 2), "channel": rng.choice(["ATM", "WEB", "POS", "UPI"], n),
                        "booked_on": (pd.Timestamp("2023-01-01") + pd.to_timedelta(rng.integers(0, 700, n), unit="D")).strftime("%Y-%m-%d")})
    tgt = src.sample(frac=1, random_state=2).copy()
    bad = rng.choice(len(tgt), 2000, replace=False)
    tgt.iloc[bad, tgt.columns.get_loc("amount")] += 1.0
    tgt = tgt.iloc[:-250]                                            # 250 rows never arrived
    src.to_csv(DATA / "big_legacy.csv", index=False)
    tgt.to_csv(DATA / "big_new.csv", index=False)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    legacy = build_legacy()
    target = build_target(legacy)
    clean = build_clean(legacy)
    write_sqlite(DATA / "legacy.db", {"customers": legacy})
    write_sqlite(DATA / "new.db", {"customers": target, "customers_clean": clean})
    legacy.to_csv(DATA / "customers_legacy.csv", index=False)
    target.to_csv(DATA / "customers_new.csv", index=False)
    write_profile()
    if "--big" in sys.argv:
        write_big()
    print(f"legacy {len(legacy):,} rows | new {len(target):,} rows | clean copy {len(clean):,} rows")
    print(f"demo data: {DATA}\ndemo profile: {PROFILE}")


if __name__ == "__main__":
    main()
