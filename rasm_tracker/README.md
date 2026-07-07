# Fare Yield Proxy Tracker

Samples one-way fares for a fixed route basket across DL / UA / AA / WN at
several booking windows (7 / 14 / 30 / 60 days out), on a schedule, and
stores the time series in SQLite.

## What this is -- and isn't

This is a **directional leading indicator for yield trend**, not a
substitute for reported PRASM/TRASM. It only sees the retail/advance-purchase
leisure fare curve at query time. It does NOT capture:
- Corporate contract fares
- Close-in / last-minute business fares
- Cargo revenue
- Ancillary revenue (bags, seats, loyalty co-brand)
- Award/upgrade redemptions

Rising fares at a given booking window vs. prior periods = pricing power
improving = directional PRASM tailwind. That's the read -- not a number to
plug into a model as if it were the reported metric. The institutional
version of this (ARC ticketing data) uses actual realized bookings across
the industry and removes this retail-fare noise problem; it's a paid feed,
not something scrapeable, but worth knowing it exists.

## Setup

1. **Get a SerpApi key**: sign up at https://serpapi.com (free tier: 250
   searches/month; this basket uses ~80 queries per run -- 4 carriers x
   ~4-5 routes x 4 windows -- so the free tier covers roughly 3 runs/month,
   the $25/month tier for 1,000 searches covers a run every 3 days
   comfortably).

2. **Create a GitHub repo** and push this folder to it.

3. **Add your API key as a repo secret**:
   Repo -> Settings -> Secrets and variables -> Actions -> New repository
   secret -> name it `SERPAPI_KEY`, paste your key.

4. **That's it.** The workflow in `.github/workflows/track_fares.yml` runs
   automatically every 3 days and commits the updated `data/fares.db` back
   to the repo. You can also trigger it manually from the Actions tab
   ("Run workflow") to test immediately without waiting 3 days.

## Running locally instead (no GitHub needed)

```bash
pip install -r requirements.txt
export SERPAPI_KEY="your_key_here"
python fare_tracker.py
```

Then schedule it yourself with cron, e.g. to run every 3 days at 9am:
```
0 9 */3 * * cd /path/to/rasm_tracker && SERPAPI_KEY="your_key" python fare_tracker.py
```

## Editing the route basket

Edit `routes_config.json` -- add/remove routes or carriers, or change the
booking windows sampled. No code changes needed.

**Note on Southwest (WN)**: Southwest has historically restricted
distribution through GDS/OTA channels including Google Flights. Run the
tracker once and check `raw_status` in the database for WN rows -- if
you're consistently seeing `no_flights_found`, Google Flights isn't a
viable source for WN and you'd need a different approach for that carrier.

## Getting the data back out

Once the database has a few runs in it, download `data/fares.db` from your
repo (or from GitHub Actions run artifacts) and send it back to me --
I can build you a chart/dashboard of fare trends by carrier, route, and
booking window, and overlay it against reported PRASM once each quarter's
earnings print lands.

## Database schema

Table `fare_samples`:

| column | meaning |
|---|---|
| run_timestamp_utc | when this sample was taken |
| carrier_code | 2-letter IATA code |
| carrier_name | full carrier name |
| origin / dest | route |
| route_label | tag from config (e.g. "hub-transcon") |
| booking_window_days | how far out from run date the travel date is |
| travel_date | the date being priced |
| price | cheapest one-way fare found, USD |
| currency | always USD in this config |
| price_level | Google's own price_level tag (low/typical/high) if available |
| typical_price_low / typical_price_high | Google's typical range for the route |
| raw_status | "ok", "no_flights_found", or an error message |
