import os
import atexit
from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from weather import (
    fetch_weather, get_weather, get_outlook_dates, get_hike_dates,
    days_until_departure, forecast_for_date, LOCATIONS,
)
from datetime import datetime, timezone

app = Flask(__name__)


def _start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=fetch_weather, trigger="interval", hours=12, id="weather_refresh")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())


@app.route("/")
def index():
    cache = get_weather()
    locations = cache.get("locations", {})
    fetched_at = cache.get("fetched_at", "")

    try:
        fetched_dt = datetime.fromisoformat(fetched_at)
        updated_str = fetched_dt.strftime("%a, %B %-d, %Y at %H:%M UTC")
    except Exception:
        updated_str = fetched_at

    outlook_dates = get_outlook_dates(cache)
    hike_dates = get_hike_dates()
    days_left = days_until_departure()

    outlook_rows = []
    for loc in LOCATIONS:
        loc_data = locations.get(loc["name"], {})
        days = []
        for d in outlook_dates:
            fc = forecast_for_date(loc_data, d)
            days.append(fc)
        outlook_rows.append({
            "name": loc["name"],
            "elev": loc["elev"],
            "day_label": loc["day_label"],
            "days": days,
            "source": loc_data.get("source", ""),
        })

    hike_days_data = []
    hike_locs = LOCATIONS[1:]
    for i, (loc, date_str) in enumerate(zip(hike_locs, hike_dates)):
        loc_data = locations.get(loc["name"], {})
        fc = forecast_for_date(loc_data, date_str)
        hike_days_data.append({
            "day_num": i + 1,
            "loc": loc,
            "date_str": date_str,
            "forecast": fc,
        })

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%a, %B %-d, %Y")

    outlook_date_labels = []
    for d in outlook_dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        outlook_date_labels.append(dt.strftime("%a %-m/%-d"))

    has_data = bool(locations)
    sources = cache.get("sources", [])

    return render_template(
        "index.html",
        updated_str=updated_str,
        today_str=today_str,
        days_left=days_left,
        outlook_rows=outlook_rows,
        outlook_date_labels=outlook_date_labels,
        hike_days_data=hike_days_data,
        hike_dates=hike_dates,
        has_data=has_data,
        sources=sources,
    )


@app.route("/refresh")
def refresh():
    fetch_weather()
    return "Weather cache refreshed", 200


if __name__ == "__main__":
    _start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
