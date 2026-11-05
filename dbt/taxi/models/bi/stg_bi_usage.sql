-- One row per adoption-relevant BI event, classified. Source: Superset's log, copied by the bi_usage DAG.
{{ config(materialized='view', schema='staging') }}

with events as (
    select * from {{ source('raw', 'bi_usage_events') }}
)

select
    e.log_id,
    e.event_at,
    e.event_at::date as event_date,
    e.username,
    e.is_admin,
    case
        when e.action = 'dashboard' then 'dashboard_view'
        when e.action = 'log' and e.event_name = 'load_chart' then 'chart_load'
        when e.action in ('ChartRestApi.post', 'ChartRestApi.put') then 'chart_built'
        when e.action in ('DashboardRestApi.post', 'DashboardRestApi.put') then 'dashboard_built'
    end as event_type,
    e.dashboard_id,
    e.dashboard_title,
    coalesce(e.dashboard_certified, false) as dashboard_certified,
    e.slice_id,
    e.slice_name,
    coalesce(e.chart_certified, false) as chart_certified,
    e.dataset_name,
    coalesce(e.dataset_certified, false) as dataset_certified
from events as e
