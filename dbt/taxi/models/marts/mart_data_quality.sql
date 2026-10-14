-- What the pipeline kept and why it dropped the rest, per month. Pairs with audit.dq_results (load-time gate).
select
    source_month,
    count(*)                                              as raw_rows,
    count(*) filter (where exclusion_reason is null)      as kept_rows,
    avg((exclusion_reason is not null)::int)              as excluded_share,
    {% for r in ['pickup_outside_month', 'dropoff_before_pickup', 'over_6_hours', 'negative_amount',
                 'no_charge_dispute_void', 'implausible_distance'] %}
    count(*) filter (where exclusion_reason = '{{ r }}')  as {{ r }}{{ "," if not loop.last }}
    {% endfor %}
from {{ ref('stg_yellow_trips') }}
group by 1
