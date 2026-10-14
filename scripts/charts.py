"""Draw the README charts from the warehouse (run on the host after a backfill + transform).

    python scripts/charts.py          # needs the stack up; reads via `docker compose exec warehouse psql`
"""
import io
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "img"
REASONS = ["implausible_distance", "no_charge_dispute_void", "negative_amount", "over_6_hours",
           "dropoff_before_pickup", "pickup_outside_month"]


def sql(query: str) -> pd.DataFrame:
    out = subprocess.run(["docker", "compose", "exec", "-T", "warehouse", "psql", "-U", "warehouse", "warehouse",
                          "--csv", "-c", query], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return pd.read_csv(io.StringIO(out))


def validation():
    gate = sql("select source_month, rule, value, op, threshold, severity, passed from audit.dq_results "
               "where source_month >= '2000-01-01' order by checked_at")
    gate["passed"] = gate.passed.map({"t": True, "f": False, True: True, False: False})   # psql --csv writes t/f
    # latest check per month, months in order
    gate = gate.drop_duplicates(["source_month", "rule"], keep="last").sort_values("source_month")
    dq = sql("select * from marts.mart_data_quality order by source_month")
    months = [m[:7] for m in dq.source_month]

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.6), gridspec_kw={"width_ratios": [1.35, 1, 1]})

    # 1. The gate: every rule, every month. Green pass, amber failed warn rule, red failed error rule.
    ax = axes[0]
    rules = ["row_count", "pickup_in_month", "zone_ids_valid", "dropoff_after_pickup",     # config.RULES order
             "negative_fare_share", "passenger_null_share", "distance_over_200mi"]
    passed = gate.pivot(index="rule", columns="source_month", values="passed").loc[rules].astype(bool)
    sev = gate.drop_duplicates("rule").set_index("rule").loc[rules]
    vals = gate.pivot(index="rule", columns="source_month", values="value").loc[rules]
    is_error = (sev.severity.to_numpy(dtype=str) == "error")[:, None]
    status = np.where(passed.values, 2, np.where(is_error, 0, 1))
    ax.imshow(status, cmap=ListedColormap(["#e06666", "#f6b26b", "#93c47d"]), vmin=0, vmax=2, aspect="auto")
    for i in range(len(rules)):
        for j in range(passed.shape[1]):
            v = vals.iloc[i, j]
            ax.text(j, i, f"{v / 1e6:.2f}M" if v > 10 else f"{v:.1%}", ha="center", va="center", fontsize=8)

    def label(r):
        t = sev.loc[r, "threshold"]
        shown = f"{t / 1e6:g}M" if t > 10 else f"{t:g}"
        return f"{r}  ({sev.loc[r, 'op']} {shown}, {sev.loc[r, 'severity']})"

    ax.set_yticks(range(len(rules)), [label(r) for r in rules], fontsize=8)
    ax.set_xticks(range(passed.shape[1]), [m[:7] for m in passed.columns], fontsize=8, rotation=45, ha="right")
    n_warn = int((~passed.values & (status == 1)).sum())
    n_err = int((status == 0).sum())
    ax.set_title("1 · Quality gate, latest check per month (audit.dq_results)\n"
                 f"{n_err} failed error rules, {n_warn} failed warn rules (amber)", fontsize=10)

    # 2. Warn-level drift: values against their thresholds.
    ax = axes[1]
    for rule, color in [("passenger_null_share", "tab:orange"), ("negative_fare_share", "tab:blue")]:
        s_ = gate[gate.rule == rule]
        ax.plot([m[:7] for m in s_.source_month], s_.value * 100, marker="o", color=color, label=rule)
        ax.axhline(s_.threshold.iloc[0] * 100, color=color, ls="--", lw=1)
    ax.set_ylabel("% of the month's rows")
    ax.set_ylim(0, max(18, gate[gate.rule == "passenger_null_share"].value.max() * 110))
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.legend(fontsize=8, loc="upper left")
    ax.set_title("2 · Warn rules over time (dashed = threshold)", fontsize=10)
    ax.grid(alpha=0.3)

    # 3. What staging excluded, by reason.
    ax = axes[2]
    bottom = np.zeros(len(dq))
    for r in REASONS:
        share = dq[r] / dq.raw_rows * 100
        ax.bar(months, share, bottom=bottom, label=r.replace("_", " "))
        bottom += share
    for x, b in zip(months, bottom, strict=True):
        ax.text(x, b + 0.1, f"{b:.1f}%", ha="center", fontsize=8)
    ax.set_ylabel("% of raw rows excluded")
    ax.set_ylim(0, bottom.max() * 1.45)
    ax.tick_params(axis="x", labelrotation=45, labelsize=8)
    ax.legend(fontsize=7, loc="upper left", ncol=2)
    ax.set_title("3 · Rows staging excludes, by reason", fontsize=10)

    fig.tight_layout()
    fig.savefig(OUT / "validation.png", dpi=130)
    plt.close(fig)


def demand():
    d = sql("select pickup_dow, pickup_hour, avg_trips from marts.mart_hourly_demand")
    grid = d.pivot(index="pickup_dow", columns="pickup_hour", values="avg_trips")
    fig, ax = plt.subplots(figsize=(11, 3.2))
    im = ax.imshow(grid.values, aspect="auto", cmap="viridis")
    ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(0, 24, 2), [f"{h:02d}:00" for h in range(0, 24, 2)], fontsize=8)
    fig.colorbar(im, ax=ax, label="avg trips per hour")
    ax.set_title("mart_hourly_demand: NYC yellow-taxi pickups by hour of week (all loaded months)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "hourly_demand.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    validation()
    demand()
    print("wrote", OUT / "validation.png", OUT / "hourly_demand.png")
