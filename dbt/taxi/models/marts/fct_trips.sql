-- Clean trips only. Incremental by source month: each run rebuilds just the months whose raw rows were
-- (re)loaded since the last run, so a corrected or backfilled month replaces itself without a full rebuild.
{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='source_month',
    indexes=[{'columns': ['source_month']}, {'columns': ['pickup_date']}],
) }}

select
    source_month,
    loaded_at,
    pickup_at,
    pickup_at::date                     as pickup_date,
    extract(isodow from pickup_at)::int as pickup_dow,
    extract(hour from pickup_at)::int   as pickup_hour,
    dropoff_at,
    trip_minutes,
    trip_miles,
    passenger_count,
    pickup_zone_id,
    dropoff_zone_id,
    payment_type,
    fare_amount,
    tip_amount,
    total_amount
from {{ ref('stg_yellow_trips') }}
where exclusion_reason is null
{% if is_incremental() %}
  and source_month in (
      select distinct source_month from {{ source('raw', 'yellow_trips') }}
      where loaded_at > (select coalesce(max(loaded_at), '1900-01-01') from {{ this }})
  )
{% endif %}
