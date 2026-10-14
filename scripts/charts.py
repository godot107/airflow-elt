"""Draw the README charts from the warehouse (run on the host after a backfill + transform).

    python scripts/charts.py          # needs the stack up; reads via `docker compose exec warehouse psql`
"""
import io
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
    gate = gate.drop_duplicates(["source_month", "rule"], keep="last").sort_values("source_month")  # latest check per month
    dq = sql("select * from marts.mart_data_quality order by source_month")
    months = [m[:7] for m in dq.source_month]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), gridspec_kw={"width_ratios": [1.25, 1, 1]})

    # 1. The gate: every rule, every month, as headroom to its threshold (green = pass).
    ax = axes[0]
    rules = ["row_count", "pickup_in_month", "zone_ids_valid", "dropoff_after_pickup",     # config.RULES order
             "negative_fare_share", "passenger_null_share", "distance_over_200mi"]
    grid = gate.pivot(index="rule", columns="source_month", values="passed").loc[rules].astype(bool)
    sev = gate.drop_duplicates("rule").set_index("rule").loc[rules]
    vals = gate.pivot(index="rule", columns="source_month", values="value").loc[rules]
    ax.imshow(np.where(grid.values, 1, 0), cmap="RdYlGn", vmin=-0.3, vmax=1.3, aspect="auto")
    for i, r in enumerate(rules):
        for j in range(grid.shape[1]):
            v = vals.iloc[i, j]
            ax.text(j, i, f"{v:,.0f}" if v > 10 else f"{v:.2%}", ha="center", va="center", fontsize=8)
    ax.set_yticks(range(len(rules)), [f"{r}  ({sev.loc[r, 'op']} {sev.loc[r, 'threshold']:{',.0f' if sev.loc[r, 'threshold'] > 10 else 'g'}}, {sev.loc[r, 'severity']})"
                                      for r in rules], fontsize=8)
    ax.set_xticks(range(grid.shape[1]), [m[:7] for m in grid.columns], fontsize=8)
    ax.set_title("1 · Load-time gate (audit.dq_results)\nall 7 rules pass; error rules would stop the run", fontsize=10)

    # 2. Warn-level drift: values against their thresholds.
    ax = axes[1]
    for rule, color in [("passenger_null_share", "tab:orange"), ("negative_fare_share", "tab:blue")]:
        s = gate[gate.rule == rule]
        ax.plot([m[:7] for m in s.source_month], s.value * 100, marker="o", color=color, label=rule)
        ax.axhline(s.threshold.iloc[0] * 100, color=color, ls="--", lw=1)
    ax.set_ylabel("% of the month's rows")
    ax.set_ylim(0, 16)
    ax.legend(fontsize=8, loc="upper left")
    ax.set_title("2 · Drift on warn rules (dashed = threshold)\nmissing passenger count 4.7% → 11.9%", fontsize=10)
    ax.grid(alpha=0.3)

    # 3. What staging excluded, by reason.
    ax = axes[2]
    bottom = np.zeros(len(dq))
    for r in REASONS:
        share = dq[r] / dq.raw_rows * 100
        ax.bar(months, share, bottom=bottom, label=r.replace("_", " "))
        bottom += share
    for x, b in zip(months, bottom):
        ax.text(x, b + 0.1, f"{b:.1f}%", ha="center", fontsize=8)
    ax.set_ylabel("% of raw rows excluded")
    ax.legend(fontsize=7, loc="lower right")
    ax.set_title("3 · Rows staging excludes, by reason\n(dbt tests then check nothing was lost)", fontsize=10)

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
    ax.set_title("mart_hourly_demand: NYC yellow-taxi pickups by hour of week (Q1 2024)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "hourly_demand.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    validation()
    demand()
    print("wrote", OUT / "validation.png", OUT / "hourly_demand.png")
