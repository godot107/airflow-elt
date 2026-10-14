"""The raw contract absorbs TLC's schema drift and refuses files missing what the pipeline needs."""
import pyarrow as pa
import pytest

from taxi import config, load


def tlc_batch(n=3, **overrides):
    cols = {
        "VendorID": pa.array([1] * n, pa.int32()),
        "tpep_pickup_datetime": pa.array([0] * n, pa.timestamp("us")),
        "tpep_dropoff_datetime": pa.array([60_000_000] * n, pa.timestamp("us")),
        "PULocationID": pa.array([132] * n, pa.int32()),
        "DOLocationID": pa.array([236] * n, pa.int32()),
        "fare_amount": pa.array([12.5] * n),
        "Airport_fee": pa.array([1.75] * n),
    }
    cols.update(overrides)
    return pa.table({k: v for k, v in cols.items() if v is not None})


def test_conform_maps_case_and_fills_missing_columns():
    t, extras = load.conform(tlc_batch(), "2024-01")
    assert t.column_names == [*config.COLUMNS, "source_month"]
    assert t["airport_fee"].to_pylist() == [1.75] * 3           # Airport_fee -> airport_fee
    assert t["tip_amount"].null_count == 3                        # absent in source -> NULL
    assert t["source_month"].to_pylist() == ["2024-01-01"] * 3
    assert extras == []


def test_conform_reports_new_source_columns_instead_of_loading_them():
    _, extras = load.conform(tlc_batch(cbd_congestion_fee=pa.array([0.75] * 3)), "2025-01")
    assert extras == ["cbd_congestion_fee"]


def test_conform_rejects_a_file_without_required_columns():
    with pytest.raises(ValueError, match="pulocationid"):
        load.conform(tlc_batch(PULocationID=None), "2024-01")
