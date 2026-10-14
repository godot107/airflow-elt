import os
import sys
import time

sys.path.insert(0, "/opt/airflow/dags")
from taxi_housekeeping import prune  # noqa: E402


def test_prune_deletes_only_old_matching_files_and_empty_dirs(tmp_path):
    old, new, other = tmp_path / "a" / "old.parquet", tmp_path / "new.parquet", tmp_path / "keep.txt"
    old.parent.mkdir()
    for f in (old, new, other):
        f.write_text("x")
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    os.utime(other, (ten_days_ago, ten_days_ago))
    deleted = prune(tmp_path, "*.parquet*", older_than_days=7)
    assert deleted == [str(old)]
    assert new.exists() and other.exists() and not old.parent.exists()


def test_prune_missing_root_is_a_no_op(tmp_path):
    assert prune(tmp_path / "absent", "*", 1) == []
