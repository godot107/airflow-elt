"""Assets shared between DAGs: the producer lists them as outlets, the consumer schedules on them."""
from airflow.sdk import Asset

RAW_TRIPS = Asset(name="raw_yellow_trips", uri="postgres://warehouse:5432/warehouse/raw/yellow_trips")
