-- Months whose latest raw load passed every error-level rule of the quality gate. "Latest" is checked
-- against the raw data itself: a month reloaded after its last check is not approved until the gate
-- has seen the new rows.
with last_check as (
    select
        source_month,
        run_id,
        checked_at,
        max(checked_at) over (partition by source_month) as latest_checked_at,
        severity,
        passed
    from {{ source('audit', 'dq_results') }}
),

latest_load as (
    select
        source_month,
        max(loaded_at) as loaded_at
    from {{ source('raw', 'yellow_trips') }}
    group by source_month
)

select
    c.source_month,
    max(c.checked_at) as approved_at
from last_check as c
inner join latest_load as l on c.source_month = l.source_month
where c.checked_at = c.latest_checked_at
group by c.source_month
having
    bool_and(c.passed or c.severity <> 'error')
    and max(c.checked_at) >= max(l.loaded_at)
