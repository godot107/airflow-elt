-- Clean trips from gate-approved months only. Incremental by source month: each run rebuilds just the
-- months whose raw rows were (re)loaded since the last run, so a corrected or backfilled month replaces
-- itself without a full rebuild. A month whose latest load failed the gate is skipped and keeps its last
-- approved rows, even if another month's asset event triggers this run.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='source_month',
    on_schema_change='append_new_columns',
    indexes=[{'columns': ['source_month']}, {'columns': ['pickup_date']}],
) }}

with stg as (
    select * from {{ ref('stg_yellow_trips') }}
),

approved as (
    select source_month from {{ ref('approved_months') }}
),

raw_loads as (
    select
        source_month,
        loaded_at
    from {{ source('raw', 'yellow_trips') }}
)

select
    s.source_month,
    s.loaded_at,
    s.pickup_at,
    s.pickup_at::date as pickup_date,
    extract(isodow from s.pickup_at)::int as pickup_dow,
    extract(hour from s.pickup_at)::int as pickup_hour,
    s.dropoff_at,
    s.trip_minutes,
    s.trip_miles,
    s.passenger_count,
    s.pickup_zone_id,
    s.dropoff_zone_id,
    s.payment_type,
    s.fare_amount,
    s.tip_amount,
    s.total_amount,
    s.cbd_congestion_fee
from stg as s
where
    s.exclusion_reason is null
    and s.source_month in (select a.source_month from approved as a)
    {% if is_incremental() %}
        and s.source_month in (
            select distinct r.source_month from raw_loads as r
            -- this model can't take an alias here (dbt --empty adds one); it is the subquery's only table
            where r.loaded_at > (select coalesce(max(loaded_at), '1900-01-01') from {{ this }})  -- noqa: RF02
        )
    {% endif %}
