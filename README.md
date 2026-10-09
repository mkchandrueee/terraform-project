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
