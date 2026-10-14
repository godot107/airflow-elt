import pyarrow as pa
import pyarrow.compute as pc
import pytest

from taxi import faults, load
from tests.test_contract import tlc_batch


def test_shift_pickups_moves_half_the_trips_a_year_back_and_keeps_durations():
    t = faults.corrupt(tlc_batch(n=10), "shift_pickups")
    years = pc.year(t["tpep_pickup_datetime"]).to_pylist()
    assert years.count(1969) == 5 and years.count(1970) == 5
    minutes = pc.divide(pc.subtract(t["tpep_dropoff_datetime"], t["tpep_pickup_datetime"]).cast(pa.int64()),
                        60_000_000).to_pylist()
    assert set(minutes) == {1}


def test_bad_zones_sets_one_in_twenty_out_of_range():
    t = faults.corrupt(tlc_batch(n=40), "bad_zones")
    assert t["PULocationID"].to_pylist().count(999) == 2


def test_missing_column_breaks_the_contract():
    t = faults.corrupt(tlc_batch(), "missing_column")
    with pytest.raises(load.ContractError):
        load.conform(t, "2024-04")


def test_unknown_fault_is_rejected():
    with pytest.raises(ValueError, match="unknown fault"):
        faults.corrupt(tlc_batch(), "cosmic_rays")
