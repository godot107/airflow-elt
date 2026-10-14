{# Use the folder's schema as-is (staging, marts, reference) instead of dbt's default "<target>_<schema>". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
