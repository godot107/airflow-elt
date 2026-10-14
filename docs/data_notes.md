# Data notes: NYC TLC yellow-taxi trips, 2024

Source: [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), one Parquet
file per month, ~50 MB / ~3M trips each, published about two months after the month ends.
[Data dictionary (PDF)](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf).

## What the raw files contain (measured by the quality gate, `audit.dq_results`)

| Month | Trips | Pickup inside the month | Dropoff after pickup | Negative fare | Passenger count missing | Distance > 200 mi |
|---|---|---|---|---|---|---|
| 2024-01 | 2,964,624 | 99.999% | 99.998% | 1.26% | 4.7% | 0.001% |
| 2024-02 | 3,007,526 | 100.000% | 100.000% | 1.35% | 6.2% | 0.001% |
| 2024-03 | 3,582,628 | 99.999% | 99.997% | 1.63% | 11.9% | 0.003% |

Observations that set the rule thresholds in `include/taxi/config.py`:

- **Negative fares are normal, not corruption.** About 1–2% of rows are reversals: 65% of them are
  payment type 3 (no charge) or 4 (dispute), where 29% and 46% of fares are negative. A "no negative fares" rule would fail every month; the gate warns above 3%.
- **Missing passenger counts are rising** (4.7% → 6.2% → 11.9% in one quarter). It is one
  population: in Q1 2024 a row lacks a passenger count **if and only if** `payment_type = 0` ("flex fare" in
  the current dictionary), and all of those rows also lack `RatecodeID`. So the rising share is flex-fare
  trips growing, not a degrading feed. It is a warn rule
  at 15%: real drift worth watching, not a reason to stop loading.
- **Stray timestamps exist** (January 2024 has pickups dated 2002 and 2024-02-01), but are rare: the gate
  only stops a month if fewer than 99% of pickups fall inside it, which would mean a wrong file.
- **Schema drift between years** (checked on 2023-01, 2024-01, 2025-01): `airport_fee` in 2023 becomes
  `Airport_fee` in 2024; `passenger_count` is a double in 2023 and an int64 in 2024; 2025 adds `cbd_congestion_fee`
  (Manhattan congestion pricing, started 2025-01-05). The loader maps names case-insensitively and logs new
  columns instead of failing or loading them unasked.

## What staging excludes (`mart_data_quality`)

`stg_yellow_trips.exclusion_reason` gives every dropped row one reason, checked in order:
pickup outside the month, dropoff before pickup, trip over 6 hours, negative fare or total,
no charge / dispute / void, distance ≤ 0 or > 200 miles. See the README for the measured shares.
