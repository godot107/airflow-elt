"""Screenshot the Superset dashboard for the README (headless Chromium, shared workspace venv).

    set -a; . ./.env; set +a; python bi/screenshots.py [--user ops_manager] [--out docs/img/superset_dashboard.png]
"""
import argparse
import os

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8088"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="admin")
    ap.add_argument("--dashboard", default="1")
    ap.add_argument("--out", default="docs/img/superset_dashboard.png")
    args = ap.parse_args()
    admin_pw = os.environ["SUPERSET_ADMIN_PASSWORD"]
    password = admin_pw if args.user == "admin" else f"{admin_pw}-{args.user}"

    with sync_playwright() as p:
        page = p.chromium.launch().new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{BASE}/login/")
        page.fill("input[name=username], #username", args.user)
        page.fill("input[name=password], #password", password)
        page.keyboard.press("Enter")
        page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)
        page.goto(f"{BASE}/superset/dashboard/{args.dashboard}/?standalone=1")
        page.wait_for_selector(".dashboard-component-chart-holder", timeout=60_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(4000)  # let ECharts finish animating
        errors = page.locator(".alert-danger, [data-test='error-message']").all_inner_texts()
        page.screenshot(path=args.out, full_page=True)
        print(f"saved {args.out}; chart errors: {errors or 'none'}")


if __name__ == "__main__":
    main()
