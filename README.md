#Terraform Multicloud project
In this project we use terraform to automate aws and azure colud resources.

## DataRecon (data migration testing)
Lightweight single-file Streamlit app: `pip install -r requirements.txt && streamlit run datarecon.py`.
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
