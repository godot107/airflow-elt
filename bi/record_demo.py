"""Record a short walkthrough of the certified dashboard and turn it into a GIF for the README/blog.

Logs in first (so the login page is not in the video), then records: the dashboard loading, the certified
badge tooltip, hovering the borough bars and a month, and sorting the scorecard. Headless Chromium records
no mouse pointer, so a small cursor is drawn in the page. Needs ffmpeg.

    set -a; . ./.env; set +a; python bi/record_demo.py --out docs/img/superset_walkthrough.gif
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8088"
VIEW = {"width": 1440, "height": 1240}
CURSOR_JS = """
(() => {
  const dot = document.createElement('div');
  dot.style.cssText = 'position:fixed;z-index:2147483647;width:18px;height:18px;border-radius:50%;' +
    'background:rgba(220,38,38,.85);border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.5);' +
    'pointer-events:none;transform:translate(-50%,-50%);left:-50px;top:-50px;transition:transform .08s';
  const add = () => document.body && !dot.isConnected && document.body.appendChild(dot);
  document.addEventListener('mousemove', e => {
    add(); dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px';
  }, true);
  document.addEventListener('mousedown', () => dot.style.transform = 'translate(-50%,-50%) scale(.7)', true);
  document.addEventListener('mouseup', () => dot.style.transform = 'translate(-50%,-50%)', true);
})();
"""


def glide(page, locator, pause_ms: int, dx: float = 0.5, dy: float = 0.5) -> None:
    box = locator.bounding_box()
    page.mouse.move(box["x"] + box["width"] * dx, box["y"] + box["height"] * dy, steps=25)
    page.wait_for_timeout(pause_ms)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/img/superset_walkthrough.gif")
    ap.add_argument("--width", type=int, default=1000)
    ap.add_argument("--fps", type=int, default=12)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        login = browser.new_context(viewport=VIEW)
        page = login.new_page()
        page.goto(f"{BASE}/login/")
        page.fill("#username", "admin")
        page.fill("#password", os.environ["SUPERSET_ADMIN_PASSWORD"])
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/login" not in u)
        state = login.storage_state()
        login.close()

        ctx = browser.new_context(viewport=VIEW, storage_state=state, record_video_dir=str(tmp),
                                  record_video_size=VIEW)
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        page.goto(f"{BASE}/superset/dashboard/1/?standalone=1")
        page.wait_for_selector(".dashboard-component-chart-holder")
        page.wait_for_load_state("networkidle")
        page.mouse.move(700, 450)
        page.wait_for_timeout(1500)

        charts = page.locator(".dashboard-component-chart-holder")
        glide(page, page.locator("[aria-label='certified']").first, 2200)        # certified badge tooltip
        revenue = charts.nth(5)
        glide(page, revenue, 1600, dx=0.55, dy=0.25)                              # Manhattan bar
        glide(page, revenue, 1600, dx=0.3, dy=0.33)                               # Queens bar
        glide(page, charts.nth(4), 1600, dx=0.95, dy=0.4)                         # Sep 2026 month bar
        header = page.locator("th", has_text="Card tip rate")
        glide(page, header, 400)
        header.click()                                                            # sort scorecard
        page.wait_for_timeout(1800)
        glide(page, page.locator("th", has_text="Revenue per trip"), 300)
        page.locator("th", has_text="Revenue per trip").click()
        page.wait_for_timeout(2000)
        video = page.video.path()
        ctx.close()
        browser.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Skip the blank first frames while the page paints, then a two-pass palette GIF.
    vf = f"fps={args.fps},scale={args.width}:-1:flags=lanczos"
    palette = tmp / "palette.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.8", "-i", video, "-vf",
                    f"{vf},palettegen=stats_mode=diff", str(palette)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.8", "-i", video, "-i", str(palette),
                    "-lavfi", f"{vf} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                    str(out)], check=True)
    shutil.rmtree(tmp)
    print(f"saved {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
