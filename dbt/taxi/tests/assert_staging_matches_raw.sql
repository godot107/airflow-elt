-- Staging must not gain or lose rows: every raw row is either kept or carries an exclusion reason.
select r.source_month, r.n as raw_rows, s.n as staged_rows
from (select source_month, count(*) n from {{ source('raw', 'yellow_trips') }} group by 1) r
full join (select source_month, count(*) n from {{ ref('stg_yellow_trips') }} group by 1) s using (source_month)
where r.n is distinct from s.n
