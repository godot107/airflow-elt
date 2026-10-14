-- Daily demand and revenue by pickup zone. Tip rate uses card trips only: cash tips are not recorded.
select
    t.pickup_date,
    z.borough,
    z.zone_name,
    t.pickup_zone_id,
    count(*)                                                   as trips,
    sum(t.total_amount)                                        as revenue,
    avg(t.fare_amount)                                         as avg_fare,
    avg(t.trip_miles)                                          as avg_miles,
    sum(t.tip_amount) filter (where t.payment_type = 1)
      / nullif(sum(t.fare_amount) filter (where t.payment_type = 1), 0) as card_tip_rate
from {{ ref('fct_trips') }} t
join {{ ref('dim_zones') }} z on z.zone_id = t.pickup_zone_id
group by 1, 2, 3, 4
