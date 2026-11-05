-- Daily BI adoption, the KPIs an analytics Center of Excellence reports: who is viewing, who is building,
-- and how much of what people actually load is certified. Platform admins are excluded (their activity is
-- setup and maintenance, not adoption).
with events as (
    select * from {{ ref('stg_bi_usage') }}
    where not is_admin
)

select
    event_date,
    count(distinct username) filter (where event_type in ('dashboard_view', 'chart_load')) as active_viewers,
    count(distinct username) filter (where event_type in ('chart_built', 'dashboard_built')) as active_makers,
    count(*) filter (where event_type = 'dashboard_view') as dashboard_views,
    count(*) filter (where event_type = 'chart_load') as chart_loads,
    count(*) filter (where event_type = 'chart_load' and chart_certified) as certified_chart_loads,
    avg(chart_certified::int) filter (where event_type = 'chart_load') as certified_load_share,
    count(distinct slice_id) filter (where event_type = 'chart_load' and not chart_certified)
        as uncertified_charts_in_use,
    count(distinct slice_id) filter (
        where event_type = 'chart_load' and not chart_certified and dataset_certified
    ) as uncertified_charts_on_certified_data
from events
group by event_date
