"""Single source of truth: source URLs, the raw-table contract and data-quality thresholds."""
from pathlib import Path

SOURCE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"   # month = YYYY-MM
DATA_DIR = Path("/opt/airflow/data/raw")
WAREHOUSE_CONN_ID = "warehouse"
RAW_TABLE = "raw.yellow_trips"
AUDIT_TABLE = "audit.dq_results"

# The raw contract. TLC files drift between years (Airport_fee vs airport_fee, cbd_congestion_fee added in
# 2025), so the loader maps names case-insensitively, fills missing contract columns with NULL and logs any
# extras instead of failing or silently widening the table.
COLUMNS = {
    "vendorid": "integer",
    "tpep_pickup_datetime": "timestamp",
    "tpep_dropoff_datetime": "timestamp",
    "passenger_count": "integer",
    "trip_distance": "double precision",
    "ratecodeid": "integer",
    "store_and_fwd_flag": "text",
    "pulocationid": "integer",
    "dolocationid": "integer",
    "payment_type": "integer",
    "fare_amount": "numeric(10,2)",
    "extra": "numeric(10,2)",
    "mta_tax": "numeric(10,2)",
    "tip_amount": "numeric(10,2)",
    "tolls_amount": "numeric(10,2)",
    "improvement_surcharge": "numeric(10,2)",
    "total_amount": "numeric(10,2)",
    "congestion_surcharge": "numeric(10,2)",
    "airport_fee": "numeric(10,2)",
}
REQUIRED = ["tpep_pickup_datetime", "tpep_dropoff_datetime", "pulocationid", "dolocationid", "fare_amount"]

# Data-quality rules, evaluated on each loaded month. "error" stops the pipeline before dbt sees the data;
# "warn" is recorded in the audit table and the log. Thresholds come from 2024 baselines (docs/data_notes.md):
# real files carry ~1% refunds and ~5% missing passenger counts, so a rule of "zero bad rows" would always fail.
RULES = [
    # name,                 metric (SQL over the month's raw rows),                                op,  threshold, severity
    ("row_count",           "count(*)",                                                             ">=", 1_000_000, "error"),
    ("pickup_in_month",     "avg((tpep_pickup_datetime >= :start and tpep_pickup_datetime < :end)::int)", ">=", 0.99, "error"),
    ("zone_ids_valid",      "avg((pulocationid between 1 and 265 and dolocationid between 1 and 265)::int)", ">=", 0.999, "error"),
    ("dropoff_after_pickup", "avg((tpep_dropoff_datetime >= tpep_pickup_datetime)::int)",           ">=", 0.995, "error"),
    ("negative_fare_share", "avg((fare_amount < 0)::int)",                                          "<=", 0.03, "warn"),
    ("passenger_null_share", "avg((passenger_count is null)::int)",                                 "<=", 0.15, "warn"),
    ("distance_over_200mi", "avg((trip_distance > 200)::int)",                                      "<=", 0.0005, "warn"),
]
