#!/usr/bin/env python3
"""
fare_tracker.py

Samples one-way fares for a fixed route basket per carrier at several
booking windows (7/14/30/60 days out), using SerpApi's Google Flights
endpoint, and appends results to a local SQLite database.

This is a DIRECTIONAL YIELD PROXY, not a substitute for reported PRASM/TRASM.
It only sees retail/advance-purchase leisure fares at query time -- it does
not capture corporate contract fares, last-minute business fares, cargo,
or ancillary revenue, all of which are part of actual RASM.

Usage:
    python fare_tracker.py

Environment variables:
    SERPAPI_KEY   Required. Your SerpApi API key.

Config:
    routes_config.json   Editable basket of routes per carrier.

Output:
    data/fares.db   SQLite database, table `fare_samples`, append-only.
"""

import os
import sys
import json
import time
import sqlite3
import logging
from datetime import date, timedelta

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("fare_tracker")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "routes_config.json")
DB_PATH = os.path.join(SCRIPT_DIR, "data", "fares.db")
SERPAPI_ENDPOINT = "https://serpapi.com/search"

# Be gentle with the API -- avoid hammering it in a tight loop.
REQUEST_DELAY_SECONDS = 1.5
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def init_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fare_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_timestamp_utc TEXT NOT NULL,
            carrier_code TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            origin TEXT NOT NULL,
            dest TEXT NOT NULL,
            route_label TEXT,
            booking_window_days INTEGER NOT NULL,
            travel_date TEXT NOT NULL,
            price REAL,
            currency TEXT,
            price_level TEXT,
            typical_price_low REAL,
            typical_price_high REAL,
            raw_status TEXT
        )
        """
    )
    conn.commit()
    return conn


def query_fare(api_key: str, origin: str, dest: str, travel_date: str,
                carrier_code: str) -> dict:
    """
    Query SerpApi Google Flights for the cheapest one-way fare on a given
    route/date, restricted to a single carrier. Returns a dict with price
    info, or a dict with raw_status set to an error description on failure.
    """
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": dest,
        "outbound_date": travel_date,
        "type": "2",  # one-way
        "include_airlines": carrier_code,
        "sort_by": "2",  # sort by price
        "currency": "USD",
        "api_key": api_key,
    }

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()

            all_flights = (payload.get("best_flights") or []) + \
                          (payload.get("other_flights") or [])

            if not all_flights:
                return {
                    "price": None,
                    "currency": "USD",
                    "price_level": None,
                    "typical_price_low": None,
                    "typical_price_high": None,
                    "raw_status": "no_flights_found",
                }

            cheapest = min(
                (f for f in all_flights if f.get("price") is not None),
                key=lambda f: f["price"],
                default=None,
            )
            if cheapest is None:
                return {
                    "price": None,
                    "currency": "USD",
                    "price_level": None,
                    "typical_price_low": None,
                    "typical_price_high": None,
                    "raw_status": "no_priced_flights",
                }

            insights = payload.get("price_insights") or {}
            typical_range = insights.get("typical_price_range") or [None, None]

            return {
                "price": cheapest.get("price"),
                "currency": "USD",
                "price_level": insights.get("price_level"),
                "typical_price_low": typical_range[0],
                "typical_price_high": typical_range[1],
                "raw_status": "ok",
            }

        except requests.exceptions.RequestException as e:
            last_error = str(e)
            log.warning(
                "Request failed (attempt %d/%d) for %s-%s %s [%s]: %s",
                attempt, MAX_RETRIES, origin, dest, travel_date, carrier_code, e,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)

    return {
        "price": None,
        "currency": "USD",
        "price_level": None,
        "typical_price_low": None,
        "typical_price_high": None,
        "raw_status": f"error: {last_error}",
    }


def run(api_key: str, config: dict, conn: sqlite3.Connection) -> None:
    run_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today = date.today()
    booking_windows = config["booking_windows_days"]

    total = 0
    ok = 0

    for carrier_code, carrier_info in config["carriers"].items():
        carrier_name = carrier_info["name"]
        for route in carrier_info["routes"]:
            origin = route["origin"]
            dest = route["dest"]
            label = route.get("label", "")

            for window_days in booking_windows:
                travel_date = (today + timedelta(days=window_days)).isoformat()

                log.info(
                    "Querying %s %s-%s (+%dd, %s)",
                    carrier_code, origin, dest, window_days, travel_date,
                )

                result = query_fare(api_key, origin, dest, travel_date, carrier_code)
                total += 1
                if result["raw_status"] == "ok":
                    ok += 1

                conn.execute(
                    """
                    INSERT INTO fare_samples (
                        run_timestamp_utc, carrier_code, carrier_name,
                        origin, dest, route_label, booking_window_days,
                        travel_date, price, currency, price_level,
                        typical_price_low, typical_price_high, raw_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_timestamp, carrier_code, carrier_name,
                        origin, dest, label, window_days,
                        travel_date, result["price"], result["currency"],
                        result["price_level"], result["typical_price_low"],
                        result["typical_price_high"], result["raw_status"],
                    ),
                )
                conn.commit()

                time.sleep(REQUEST_DELAY_SECONDS)

    log.info("Run complete: %d/%d queries returned priced results.", ok, total)


def main():
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        log.error("SERPAPI_KEY environment variable is not set. Aborting.")
        sys.exit(1)

    config = load_config(CONFIG_PATH)
    conn = init_db(DB_PATH)
    try:
        run(api_key, config, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
