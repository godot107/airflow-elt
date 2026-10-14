{# Small generic tests, written here so the project needs no dbt packages (no network at run time). #}
{% test value_between(model, column_name, min_value, max_value) %}
select * from {{ model }} where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}

{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) from {{ model }}
group by {{ columns | join(', ') }} having count(*) > 1
{% endtest %}

{# Trips and revenue in a mart must equal the fact table's: a join or filter that silently drops trips
   (e.g. a zone id missing from dim_zones) fails here. Defined as a generic test so it attaches to the mart
   and Cosmos runs it after the mart is built. #}
{% test reconciles_to(model, fact, count_col, sum_col, fact_sum_col) %}
with f as (select count(*) as n, sum({{ fact_sum_col }}) as s from {{ fact }}),
     m as (select sum({{ count_col }}) as n, sum({{ sum_col }}) as s from {{ model }})
select f.n as fact_rows, m.n as mart_rows, f.s as fact_sum, m.s as mart_sum
from f, m
where f.n <> m.n or abs(f.s - m.s) > 0.01
{% endtest %}
