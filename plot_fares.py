#!/usr/bin/env python3
"""
plot_fares.py

Reads data/fares.db (built by fare_tracker.py) and produces:
  1. charts/fare_trend_by_carrier.png
     One panel per carrier. Within each panel, one line per booking
     window (7/14/30/60 days out), showing the average fare across
     that carrier's route basket at each run date.
  2. charts/yield_index_by_carrier.png
     A single chart normalizing each carrier's overall average fare
     to 100 at the first observed run date, so carriers are visually
     comparable on the same axis regardless of absolute fare level.
  3. fares_export.csv
     A flat, pivot-ready export of every row in fare_samples, for
     anyone who'd rather work in Excel/a pivot table directly.

Usage:
    python plot_fares.py

No arguments needed -- reads data/fares.db, writes to charts/ and
fares_export.csv in the same directory as this script.
"""

import os
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # no display needed, just write files
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "fares.db")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "charts")
CSV_PATH = os.path.join(SCRIPT_DIR, "fares_export.csv")


def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        """
        SELECT run_timestamp_utc, carrier_code, carrier_name, origin, dest,
               route_label, booking_window_days, travel_date, price,
               price_level, raw_status
        FROM fare_samples
        WHERE raw_status = 'ok' AND price IS NOT NULL
        """,
        conn,
    )
    conn.close()
    df["run_timestamp_utc"] = pd.to_datetime(df["run_timestamp_utc"])
    df["run_date"] = df["run_timestamp_utc"].dt.date
    return df


def plot_trend_by_carrier(df: pd.DataFrame, out_path: str) -> None:
    carriers = sorted(df["carrier_code"].unique())
    n = len(carriers)
    fig, axes = plt.subplots(n, 1, figsize=(10, 3.2 * n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, carrier in zip(axes, carriers):
        sub = df[df["carrier_code"] == carrier]
        # Average across routes for each (run_date, booking_window)
        grouped = (
            sub.groupby(["run_date", "booking_window_days"])["price"]
            .mean()
            .reset_index()
        )
        for window in sorted(grouped["booking_window_days"].unique()):
            w = grouped[grouped["booking_window_days"] == window]
            ax.plot(w["run_date"], w["price"], marker="o", label=f"{window}d out")

        carrier_name = sub["carrier_name"].iloc[0]
        ax.set_title(f"{carrier_name} ({carrier})")
        ax.set_ylabel("Avg fare (USD)")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("Run date")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_yield_index(df: pd.DataFrame, out_path: str) -> None:
    # Overall average fare per carrier per run date, across all routes
    # and booking windows -- then normalize each carrier's series to
    # 100 at its first observation for cross-carrier comparability.
    grouped = df.groupby(["run_date", "carrier_code"])["price"].mean().reset_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    for carrier in sorted(grouped["carrier_code"].unique()):
        sub = grouped[grouped["carrier_code"] == carrier].sort_values("run_date")
        if sub.empty:
            continue
        base = sub["price"].iloc[0]
        index = (sub["price"] / base) * 100
        ax.plot(sub["run_date"], index, marker="o", label=carrier)

    ax.axhline(100, color="gray", linestyle="--", linewidth=1)
    ax.set_title("Fare yield index by carrier (first observation = 100)")
    ax.set_xlabel("Run date")
    ax.set_ylabel("Index (first run = 100)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH}. Run fare_tracker.py at least once first.")
        return

    df = load_data(DB_PATH)
    if df.empty:
        print("Database has no priced rows yet -- nothing to plot.")
        return

    n_run_dates = df["run_date"].nunique()
    print(f"Loaded {len(df)} priced rows across {n_run_dates} run date(s).")
    if n_run_dates < 2:
        print("Only one run date so far -- charts will show a single point per line.")
        print("Trends will become visible once more runs have accumulated.")

    os.makedirs(CHARTS_DIR, exist_ok=True)

    trend_path = os.path.join(CHARTS_DIR, "fare_trend_by_carrier.png")
    plot_trend_by_carrier(df, trend_path)
    print(f"Wrote {trend_path}")

    index_path = os.path.join(CHARTS_DIR, "yield_index_by_carrier.png")
    plot_yield_index(df, index_path)
    print(f"Wrote {index_path}")

    df.to_csv(CSV_PATH, index=False)
    print(f"Wrote {CSV_PATH}")


if __name__ == "__main__":
    main()
