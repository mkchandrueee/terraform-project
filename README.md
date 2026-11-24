#Terraform Multicloud project
In this project we use terraform to automate aws and azure colud resources.

## Equaliser (data migration testing)
Lightweight single-file Streamlit app: `pip install -r requirements.txt && streamlit run datarecon.py   # file name unchanged for compatibility`.
Source and target can each be a file (CSV/XLSX/Parquet) or a SQL query; rows are matched by key (order-independent).

Validations: column/row counts (with abs/% tolerance and group-by breakdown), missing/extra rows, cell mismatches,
duplicate keys and full rows, data types, nulls + blank/sentinel completeness score, aggregations on critical columns,
value-distribution diffs, and file checksums. A "Why do rows differ?" section explains uniform causes exactly
(whitespace, case, truncation, NULL columns, sign flip, constant ratio/offset, rounding, time shift, partial-load key blocks).
Rule sets, connections and queries are saved locally; reports export to Excel, CSV zip and JSON, split into numbered parts
rather than truncated. Tests: `pytest test_datarecon.py`.

**Large data (e.g. 9 lakh rows):** tick *Full data validation only* to skip profiling/type/aggregation/distribution work
(~2x faster); matched rows are counted but not listed unless *Include matched rows* is ticked; reports are built only when
you click a download. Prefer CSV/Parquet over XLSX for big files (Excel parsing is slow).

**Duplicates, nulls, highlighting, saved passwords**
- Duplicate records (same key more than once) are listed per side with group size and occurrence #, in the UI and as
  *Duplicates Source/Target* report sheets.
- Mismatches are highlighted red in the UI and in the Excel report (conditional formatting: differing cells red,
  missing/extra rows yellow, duplicates orange, FAIL/WARN statuses coloured). CSV exports carry the `status` /
  `mismatched_columns` / `issue` columns instead of colour.
- NULL handling: real NULLs, blank text and NULL-equivalent tokens (default `NULL, None, NaN, N/A, #N/A`; editable,
  `NA` is deliberately not default as it can be a real value) all compare equal as NULL. *Null / NA details* shows, per
  column and side, real-NULL / blank / token counts and NULL->value / value->NULL cell mismatches; each mismatch row is
  tagged `NULL -> value`, `value -> NULL` or `value differs`.
- Passwords: tick *Remember password* when saving a connection. They are stored Fernet-encrypted in
  `~/.datarecon_profiles.json` with the key in `~/.datarecon.key` (both owner-only, 0600). This protects against casual
  reading/sharing of the profile file, not against someone who can read both files; use read-only DB accounts.

**Evidence**
- Every result carries run information: run ID, UTC/local time, OS user, tool/library versions, verdict, the rules used,
  and for each side the input (file name + SHA-256, or connection/host/database/user), the **exact SQL executed** (+ its
  SHA-256), rows/columns loaded. No passwords are ever included.
- It appears in the app ("Run information"), as the first *Run Info* sheet of the Excel report, `run_info.csv` in the CSV
  zip, and under `evidence` in the JSON summary.
- *Download evidence report (HTML)* produces a single self-contained page mirroring the app's results (same sections and
  highlighting, source/target SQL, a content SHA-256 in the footer). Open it in a browser and use *Print / Save as PDF*
  for a PDF copy. Tables are capped at 1,000 rows there; Excel/CSV hold every row.

## Default connections, batch runs, combined Excel, capacity

**Default connections for every session.** Put shared connections in `equaliser_config.json` next to `datarecon.py`
(or set `EQUALISER_CONFIG` to another path, or use `~/.equaliser_config.json`). Copy `equaliser_config.example.json` to
start. They load for every user/session, are re-read on each page refresh (no restart), show as "(default)", and are
read-only in the app; they are never written into a user's own profile. Optional `default_source_connection` /
`default_target_connection` preselect the dropdowns. The file can also hold default `queries`, `rules` and `batches`.
Passwords, in order of preference: `"password_env": "ENV_VAR_NAME"` (recommended, nothing secret in the file),
`"password_enc"` (Fernet token; same key file as saved passwords), or `"password"` (plain text, avoid). Keep the real
`equaliser_config.json` out of git (it is git-ignored).

**Multiple queries in one run.** Switch *Mode* to *Multiple queries (one run)*. Each row of the test table is a test:
`test, source_connection, source_sql, target_connection, target_sql, keys, ignore`. Type them in, upload a CSV/Excel
list (template download provided), or load a saved list. One set of rules applies to all tests (optionally a saved rule
set); a failing test is recorded as ERROR and never stops the run. Data for each test is released before the next, so
a large table can be checked as several key-range queries.

**One combined Excel.** The batch workbook has *Batch Summary*, *Batch Run Info* (every test's source and target SQL,
connections and rules), *All Checks*, *All Mismatches* (one `key` column per row), *All Duplicates*, *All Missing/Extra
Rows*, and a *Full Data* detail sheet for each test that has differences. Frames over 100,000 rows split into numbered
sheets, never truncated. A batch HTML evidence report (summary + collapsible per-test reports, SHA-256 in the footer)
and a JSON summary are also available.

**Capacity per session.** Both sides are held in memory, so the limit is RAM, not a row cap. Measured on a 16 GB machine
with 10 text columns per side, keyed compare (peak process memory, includes the loaded data):

| rows per side | pandas 3: full / peak | pandas 2.3: full / peak | fast mode (pandas 3) |
|---|---|---|---|
| 500,000 | 3.7 s / 0.7 GB | 14.6 s / 0.9 GB | 1.1 s |
| 1,000,000 | 7.9 s / 1.2 GB | 34.9 s / 1.7 GB | 2.3 s |
| 2,000,000 | 18.3 s / 2.2 GB | 80.3 s / 3.1 GB | n/a |
| 4,000,000 | 37.3 s / 4.1 GB | not measured | 9.6 s / 3.7 GB |

Rule of thumb: about 0.1 GB (pandas 3) to 0.16 GB (pandas 2) of RAM per million cells of one side, per open browser
session. Streamlit's 200 MB upload limit is raised to 2 GB in `.streamlit/config.toml` (start Streamlit from the
project folder). Database queries are not subject to the upload limit; use *Max rows* to cap a query. Upgrading to
pandas 3 (needs a recent Streamlit) is about 4x faster than pandas 2.
