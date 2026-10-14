-- What the pipeline kept and why it dropped the rest, per month. Pairs with audit.dq_results (load-time gate).
select
    source_month,
    count(*) as raw_rows,
    count(*) filter (where exclusion_reason is null) as kept_rows,
    avg((exclusion_reason is not null)::int) as excluded_share,
    count(*) filter (where exclusion_reason = 'pickup_outside_month') as pickup_outside_month,
    count(*) filter (where exclusion_reason = 'dropoff_before_pickup') as dropoff_before_pickup,
    count(*) filter (where exclusion_reason = 'over_6_hours') as over_6_hours,
    count(*) filter (where exclusion_reason = 'negative_amount') as negative_amount,
    count(*) filter (where exclusion_reason = 'no_charge_dispute_void') as no_charge_dispute_void,
    count(*) filter (where exclusion_reason = 'implausible_distance') as implausible_distance
from {{ ref('stg_yellow_trips') }}
group by source_month
