"""
### taxi_housekeeping — keep the disk bounded

Weekly. `taxi_ingest` deletes each download once its month passes the gate; this catches what is left by
failed or abandoned runs, and prunes task logs. Long backfills therefore don't fill the disk.
"""
import time
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import dag, task

from taxi import config
from taxi.alerts import on_failure


def prune(root: Path, pattern: str, older_than_days: int, now: float | None = None) -> list[str]:
    """Delete files under `root` matching `pattern` whose mtime is older than the cutoff; then remove
    directories left empty. Returns the deleted paths."""
    cutoff = (now or time.time()) - older_than_days * 86400
    deleted = []
    if not root.exists():
        return deleted
    for f in root.rglob(pattern):
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            deleted.append(str(f))
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return deleted


@dag(
    dag_id="taxi_housekeeping",
    schedule="@weekly",
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5), "on_failure_callback": on_failure},
    tags=["taxi", "maintenance"],
    doc_md=__doc__,
)
def taxi_housekeeping():
    @task
    def prune_downloads() -> int:
        deleted = prune(config.DATA_DIR, "*.parquet*", config.KEEP_DOWNLOADS_DAYS)
        print(f"deleted {len(deleted)} stale downloads", *deleted, sep="\n  ")
        return len(deleted)

    @task
    def prune_logs() -> int:
        deleted = prune(config.LOG_DIR, "*.log", config.KEEP_LOG_DAYS)
        print(f"deleted {len(deleted)} task logs older than {config.KEEP_LOG_DAYS} days")
        return len(deleted)

    prune_downloads()
    prune_logs()


taxi_housekeeping()
