{# Use the folder's schema as-is (staging, marts, reference) instead of dbt's default "<target>_<schema>".
   The `unit` target prefixes it (unit_staging, ...) so unit tests never touch the real tables. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set base = custom_schema_name if custom_schema_name is not none else target.schema -%}
    {{ "unit_" ~ base if target.name == "unit" else base }}
{%- endmacro %}
