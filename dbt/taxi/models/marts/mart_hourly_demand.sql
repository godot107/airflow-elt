-- Average trips per hour by day of week, the shape a dispatcher or a pricing team plans around.
with per_hour as (
    select pickup_date, pickup_dow, pickup_hour, count(*) as trips
    from {{ ref('fct_trips') }}
    group by 1, 2, 3
)
select
    pickup_dow,
    pickup_hour,
    avg(trips)          as avg_trips,
    count(*)            as n_days
from per_hour
group by 1, 2
