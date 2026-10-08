#Terraform Multicloud project
In this project we use terraform to automate aws and azure colud resources.

## DataRecon (data migration testing)
Single-file Streamlit app: `pip install -r requirements.txt && streamlit run datarecon.py`.
Source and target can each be a file (CSV/XLSX/Parquet) or a SQL query. Rows are matched by key
(order-independent), reporting missing/extra rows, cell mismatches, duplicate keys and
per-column null/distinct/sum profiles. Tests: `pytest test_datarecon.py`.
