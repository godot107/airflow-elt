"""Render a terminal-style GIF of row-level security and the certification check, from REAL output.

Every command below is actually run against the live stack (psql inside the warehouse container, talking to
Cube's SQL API, and `make bi-check`); the GIF replays the captured text. Nothing is typed in by hand.

    set -a; . ./.env; set +a; python bi/terminal_gif.py --out docs/img/rls_and_check.gif   (needs Pillow)
"""
import argparse
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15)
BOLD = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 15)
COLS, ROWS, CW, LH, PAD = 104, 30, 9, 20, 16
BG, FG, DIM, GREEN, RED, CYAN, YELLOW = "#0f172a", "#e2e8f0", "#64748b", "#4ade80", "#f87171", "#67e8f9", "#fde047"


def psql(user: str, password: str, query: str) -> list[str]:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", f"PGPASSWORD={password}", "warehouse",
         "psql", "-h", "cube", "-p", "15432", "-U", user, "-d", "cube", "-c", query],
        check=True, capture_output=True, text=True).stdout
    return out.rstrip("\n").splitlines()


def bi_check() -> list[str]:
    out = subprocess.run(["make", "-s", "bi-check"], capture_output=True, text=True).stdout
    keep = [ln for ln in out.splitlines() if re.match(r"^(ok  |FAIL|     timing|PASS|FAILED)", ln)]
    return [ln if len(ln) <= COLS else ln[: COLS - 1] + "…" for ln in keep]


def scenes() -> list[tuple[str, list[str]]]:
    admin = (os.environ["CUBE_SQL_ADMIN_USER"], os.environ["CUBE_SQL_ADMIN_PASSWORD"])
    analyst = (os.environ["CUBE_SQL_ANALYST_USER"], os.environ["CUBE_SQL_ANALYST_PASSWORD"])
    by_borough = ("select pickup_zones_borough as borough, measure(trips) as trips "
                  "from taxi_operations group by 1 order by 2 desc limit 4;")
    total = "select measure(trips) as trips from taxi_operations;"
    return [
        ("# Same question, two logins. Row-level security lives in the semantic layer (Cube).", []),
        (f"psql -U {admin[0]} -c \"{by_borough}\"", psql(*admin, by_borough)),
        (f"psql -U {analyst[0]} -c \"{by_borough}\"", psql(*analyst, by_borough)),
        ("# Even a grand total is filtered for the analyst:", []),
        (f"psql -U {analyst[0]} -c \"{total}\"", psql(*analyst, total)),
        ("# And the whole BI layer is certified on demand:", []),
        ("make bi-check", bi_check()),
    ]


def wrap(text: str, first: int) -> list[str]:
    lines, width = [], first
    while len(text) > width:
        lines.append(text[:width])
        text, width = "  " + text[width:], COLS
    return [*lines, text]


def render(screen: list[tuple[str, str]]) -> Image.Image:
    img = Image.new("RGB", (COLS * CW + 2 * PAD, ROWS * LH + 2 * PAD + 26), BG)
    d = ImageDraw.Draw(img)
    for i, c in enumerate(("#f87171", "#fbbf24", "#4ade80")):
        d.ellipse((PAD + i * 20, 9, PAD + i * 20 + 11, 20), fill=c)
    d.text((PAD + 74, 6), "airflow-elt: semantic layer + BI add-on (live output)", font=FONT, fill=DIM)
    for row, (kind, text) in enumerate(screen[-ROWS:]):
        y = PAD + 26 + row * LH
        if kind == "cmd":
            d.text((PAD, y), "$ ", font=BOLD, fill=GREEN)
            d.text((PAD + 2 * CW, y), text, font=FONT, fill=FG)
        elif kind == "cmd+":
            d.text((PAD, y), text, font=FONT, fill=FG)
        elif kind == "comment":
            d.text((PAD, y), text, font=FONT, fill=YELLOW)
        else:
            color = GREEN if text.startswith(("ok", "PASS")) else RED if text.startswith("FAIL") else \
                CYAN if "timing" in text or "Queens" in text else FG
            d.text((PAD, y), text, font=FONT, fill=color)
    return img


def build(out: str) -> None:
    frames, durations, screen = [], [], []

    def snap(ms: int) -> None:
        frames.append(render(screen))
        durations.append(ms)

    for cmd, output in scenes():
        if cmd.startswith("#"):
            screen.append(("comment", cmd))
            snap(900)
            continue
        parts = wrap(cmd, COLS - 2)
        for j, part in enumerate(parts):  # type the command, a few characters per frame
            kind = "cmd" if j == 0 else "cmd+"
            screen.append((kind, ""))
            for k in range(0, len(part) + 1, 6):
                screen[-1] = (kind, part[:k])
                snap(30)
            screen[-1] = (kind, part)
        snap(350)
        for line in output:
            screen.append(("out", line))
            snap(70)
        screen.append(("out", ""))
        snap(1600)
    durations[-1] = 5000
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True)
    print(f"saved {out}: {len(frames)} frames, {os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/img/rls_and_check.gif")
    build(ap.parse_args().out)
