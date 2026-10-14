-- One row per raw trip, renamed and typed, with a reason code for every row the marts will exclude.
-- Excluded rows stay visible here so mart_data_quality can count them.
with src as (
    select * from {{ source('raw', 'yellow_trips') }}
)

select
    source_month,
    loaded_at,
    vendorid as vendor_id,
    tpep_pickup_datetime as pickup_at,
    tpep_dropoff_datetime as dropoff_at,
    round(extract(epoch from tpep_dropoff_datetime - tpep_pickup_datetime) / 60.0, 2)::numeric(10, 2) as trip_minutes,
    passenger_count,
    trip_distance as trip_miles,
    ratecodeid as rate_code_id,
    pulocationid as pickup_zone_id,
    dolocationid as dropoff_zone_id,
    payment_type,
    fare_amount,
    tip_amount,
    tolls_amount,
    total_amount,
    cbd_congestion_fee,
    case
        when
            tpep_pickup_datetime < source_month
            or tpep_pickup_datetime >= source_month + interval '1 month' then 'pickup_outside_month'
        when tpep_dropoff_datetime < tpep_pickup_datetime then 'dropoff_before_pickup'
        when tpep_dropoff_datetime - tpep_pickup_datetime > interval '6 hours' then 'over_6_hours'
        when fare_amount < 0 or total_amount < 0 then 'negative_amount'
        when payment_type in (3, 4, 6) then 'no_charge_dispute_void'
        when trip_distance <= 0 or trip_distance > 200 then 'implausible_distance'
    end as exclusion_reason
from src
