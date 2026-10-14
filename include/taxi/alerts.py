"""Failure alerting. Logs a one-line summary; swap the body for Slack/email (a notifier) in a real deployment."""
import logging

log = logging.getLogger("taxi.alerts")


def on_failure(context):
    ti = context["task_instance"]
    log.error("ALERT %s.%s failed for %s (try %s): %s", ti.dag_id, ti.task_id,
              context.get("data_interval_start"), ti.try_number, context.get("exception"))
