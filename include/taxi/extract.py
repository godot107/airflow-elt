"""Extract: is a month published yet, and download it once (atomic, skip if already complete)."""
import urllib.error
import urllib.request
from pathlib import Path

from taxi import config

UA = {"User-Agent": "airflow-elt-demo/0.1 (+https://github.com/godot107)"}


def url(month: str) -> str:
    return config.SOURCE_URL.format(month=month)


def remote_size(month: str) -> int | None:
    """Content-Length of the month's file, or None while TLC hasn't published it (they lag ~2 months)."""
    req = urllib.request.Request(url(month), method="HEAD", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers["Content-Length"])
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):            # CloudFront answers 403 for a key that doesn't exist yet
            return None
        raise


def download(month: str, dest_dir: Path = config.DATA_DIR) -> Path:
    """Idempotent: a complete file is reused; a partial one is replaced via a .part file and rename."""
    size = remote_size(month)
    if size is None:
        raise FileNotFoundError(f"{url(month)} is not published yet")
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"yellow_tripdata_{month}.parquet"
    if path.exists() and path.stat().st_size == size:
        return path
    part = path.with_suffix(".part")
    with urllib.request.urlopen(urllib.request.Request(url(month), headers=UA), timeout=60) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if part.stat().st_size != size:
        raise IOError(f"{path.name}: got {part.stat().st_size} bytes, expected {size}")
    part.rename(path)
    return path
