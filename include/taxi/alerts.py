"""Alerting: one line to the log, and to a Slack-compatible incoming webhook when ALERT_WEBHOOK_URL is set
(in .env). Failures alert from on_failure_callback; the quality gate alerts on warn-level rules itself."""
import json
import logging
import os
import urllib.request

log = logging.getLogger("taxi.alerts")


def notify(text: str) -> bool:
    """Log, then POST {"text": ...} to the webhook if configured. Never raises: an alert that fails must
    not fail the task that sent it. Returns whether a webhook accepted it."""
    log.warning("ALERT %s", text)
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return False
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception as e:                                   # noqa: BLE001 - alerting is best effort
        log.error("alert webhook failed: %s", e)
        return False


def on_failure(context):
    ti = context["task_instance"]
    interval = context.get("data_interval_start")
    notify(f":red_circle: {ti.dag_id}.{ti.task_id} failed"
           f"{f' for {interval:%Y-%m}' if interval else ''} (try {ti.try_number}): {context.get('exception')}")
