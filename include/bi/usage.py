"""Copy Superset's usage log into the warehouse, so BI adoption is measured with the same pipeline as the data.

Superset writes every dashboard view, chart load and chart edit to its `logs` table. `sync()` reads the rows
newer than the warehouse's high-water mark, flattens them with the user, chart and dataset context needed
for adoption metrics (is the chart certified? is the user an admin?), and inserts them into
raw.bi_usage_events. Log ids are unique and append-only, so reruns insert nothing twice.
"""
SUPERSET_CONN_ID = "superset_db"

DDL = """
create schema if not exists raw;
create table if not exists raw.bi_usage_events (
    log_id            bigint primary key,
    event_at          timestamp not null,
    username          text,
    is_admin          boolean,
    action            text,
    event_name        text,
    dashboard_id      integer,
    dashboard_title   text,
    dashboard_certified boolean,
    slice_id          integer,
    slice_name        text,
    chart_certified   boolean,
    dataset_name      text,
    dataset_certified boolean,
    loaded_at         timestamptz not null default now()
);
"""

# Only the events adoption is measured on; Superset also logs every API call the UI makes.
EXTRACT_SQL = """
select
    l.id,
    l.dttm,
    u.username,
    exists (
        select 1 from ab_user_role ur join ab_role r on r.id = ur.role_id
        where ur.user_id = l.user_id and r.name = 'Admin'
    ) as is_admin,
    l.action,
    case when l.action = 'log' then l.json::json ->> 'event_name' end as event_name,
    l.dashboard_id,
    d.dashboard_title,
    d.certified_by is not null as dashboard_certified,
    l.slice_id,
    s.slice_name,
    s.certified_by is not null as chart_certified,
    t.table_name,
    coalesce(t.extra, '{}')::json -> 'certification' is not null as dataset_certified
from logs as l
left join ab_user as u on u.id = l.user_id
left join dashboards as d on d.id = l.dashboard_id
left join slices as s on s.id = l.slice_id
left join tables as t on t.id = s.datasource_id and s.datasource_type = 'table'
where l.id > %(since)s
  and (
      l.action = 'dashboard'
      or (l.action = 'log' and l.json::json ->> 'event_name' = 'load_chart')
      or l.action in ('ChartRestApi.post', 'ChartRestApi.put', 'DashboardRestApi.post', 'DashboardRestApi.put')
  )
order by l.id
"""

INSERT_SQL = """
insert into raw.bi_usage_events (
    log_id, event_at, username, is_admin, action, event_name, dashboard_id, dashboard_title,
    dashboard_certified, slice_id, slice_name, chart_certified, dataset_name, dataset_certified
) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (log_id) do nothing
"""


def sync(warehouse_conn, superset_conn) -> int:
    """Insert Superset log rows newer than the warehouse high-water mark. Returns rows inserted."""
    with warehouse_conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("select coalesce(max(log_id), 0) from raw.bi_usage_events")
        since = cur.fetchone()[0]
    with superset_conn.cursor() as cur:
        cur.execute(EXTRACT_SQL, {"since": since})
        rows = cur.fetchall()
    with warehouse_conn.cursor() as cur:
        for row in rows:
            cur.execute(INSERT_SQL, row)
    warehouse_conn.commit()
    return len(rows)
