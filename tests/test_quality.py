from taxi import config, quality


def test_metrics_sql_has_one_column_per_rule_and_bound_parameters():
    sql = quality.metrics_sql()
    for name, *_ in config.RULES:
        assert f" as {name}" in sql
    assert ":start" not in sql and "%(start)s" in sql and "%(month)s" in sql


def test_evaluate_applies_direction_and_treats_missing_as_failed():
    rules = [("big", "x", ">=", 10, "error"), ("small", "y", "<=", 0.1, "warn"), ("gone", "z", ">=", 1, "error")]
    r = {x.rule: x for x in quality.evaluate({"big": 12, "small": 0.2, "gone": None}, rules)}
    assert r["big"].passed and not r["small"].passed and not r["gone"].passed


def test_thresholds_tolerate_a_normal_month():
    """Values in the range of a 2024 month (docs/data_notes.md) must pass every error rule."""
    normal = {"row_count": 2_964_624, "pickup_in_month": 0.99999, "zone_ids_valid": 1.0,
              "dropoff_after_pickup": 0.9999, "negative_fare_share": 0.0126, "passenger_null_share": 0.047,
              "distance_over_200mi": 0.0001}
    assert all(r.passed for r in quality.evaluate(normal))
