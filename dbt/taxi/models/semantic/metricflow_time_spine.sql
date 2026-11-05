-- One row per day: MetricFlow joins to this for cumulative metrics and for filling days with no trips.

select d::date as date_day
from generate_series('2023-01-01'::date, '2027-12-31'::date, interval '1 day') as d
