import requests
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

CACHE_FILE = Path("weather_cache.json")
CACHE_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()

LOCATIONS = [
    {"name": "Wengen", "lat": 46.6067, "lon": 7.9222, "elev": 1275, "day_label": "Base"},
    {"name": "Lobhornhütte", "lat": 46.6150, "lon": 7.8400, "elev": 1955, "day_label": "Day 1"},
    {"name": "Rotstockhütte", "lat": 46.5767, "lon": 7.8267, "elev": 2039, "day_label": "Day 2"},
    {"name": "Gspaltenhornhütte", "lat": 46.5500, "lon": 7.7167, "elev": 2455, "day_label": "Day 3"},
    {"name": "Blüemlisalphütte", "lat": 46.4967, "lon": 7.6833, "elev": 2840, "day_label": "Day 4"},
    {"name": "Kandersteg", "lat": 46.4950, "lon": 7.6744, "elev": 1176, "day_label": "Day 5"},
]

HIKE_START = datetime(2026, 6, 17)
HIKE_END = datetime(2026, 6, 21)

ICON_MAP = {
    0: ("icon-sun", "Clear sky"),
    1: ("icon-partly", "Mainly clear"),
    2: ("icon-partly", "Partly cloudy"),
    3: ("icon-cloudy", "Overcast"),
    45: ("icon-cloudy", "Foggy"),
    48: ("icon-cloudy", "Rime fog"),
    51: ("icon-rain", "Light drizzle"),
    53: ("icon-rain", "Moderate drizzle"),
    55: ("icon-rain", "Dense drizzle"),
    56: ("icon-rain", "Freezing drizzle"),
    57: ("icon-heavy-rain", "Heavy freezing drizzle"),
    61: ("icon-rain", "Slight rain"),
    63: ("icon-rain", "Moderate rain"),
    65: ("icon-heavy-rain", "Heavy rain"),
    66: ("icon-rain", "Freezing rain"),
    67: ("icon-heavy-rain", "Heavy freezing rain"),
    71: ("icon-snow", "Slight snow"),
    73: ("icon-snow", "Moderate snow"),
    75: ("icon-snowstorm", "Heavy snow"),
    77: ("icon-snow", "Snow grains"),
    80: ("icon-rain", "Slight showers"),
    81: ("icon-rain", "Moderate showers"),
    82: ("icon-heavy-rain", "Violent showers"),
    85: ("icon-snow", "Slight snow showers"),
    86: ("icon-snowstorm", "Heavy snow showers"),
    95: ("icon-thunder", "Thunderstorm"),
    96: ("icon-thunder", "Thunderstorm w/ hail"),
    99: ("icon-thunder", "Severe thunderstorm"),
}


def _c_to_f(c):
    return round(c * 9 / 5 + 32)


def _snow_risk(elev, temp_max_c, precip_prob, weather_code):
    is_snow_code = weather_code in (71, 73, 75, 77, 85, 86)
    if elev >= 2500 and (temp_max_c <= 2 or is_snow_code):
        return "high"
    if elev >= 2000 and (temp_max_c <= 4 or is_snow_code):
        return "moderate" if not is_snow_code else "high"
    if precip_prob >= 50 and temp_max_c <= 5 and elev >= 1800:
        return "moderate"
    if elev >= 2500:
        return "moderate"
    return "low"


def _fetch_with_retry(url, params, max_retries=4):
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited, retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def fetch_weather():
    if not _FETCH_LOCK.acquire(blocking=False):
        print("Another fetch already in progress, skipping")
        return load_cache() or {"fetched_at": datetime.now(timezone.utc).isoformat(), "locations": {}}

    try:
        return _do_fetch()
    finally:
        _FETCH_LOCK.release()


def _do_fetch():
    all_data = {}

    for idx, loc in enumerate(LOCATIONS):
        if idx > 0:
            time.sleep(1.5)
        try:
            data = _fetch_with_retry(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "elevation": loc["elev"],
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
                    "timezone": "Europe/Zurich",
                    "forecast_days": 16,
                },
            )
        except Exception as e:
            print(f"Error fetching weather for {loc['name']}: {e}")
            continue

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])
        precip_probs = daily.get("precipitation_probability_max", [])
        weather_codes = daily.get("weathercode", [])

        forecasts = []
        for i, d in enumerate(dates):
            t_max = temps_max[i] if i < len(temps_max) else None
            t_min = temps_min[i] if i < len(temps_min) else None
            prob = precip_probs[i] if i < len(precip_probs) else 0
            wcode = weather_codes[i] if i < len(weather_codes) else 0

            icon_id, condition = ICON_MAP.get(wcode, ("icon-cloudy", "Unknown"))

            is_snow = wcode in (71, 73, 75, 77, 85, 86)
            precip_label = f"{prob}% {'SNOW' if is_snow else 'rain'}"

            forecasts.append({
                "date": d,
                "temp_max_c": t_max,
                "temp_min_c": t_min,
                "temp_max_f": _c_to_f(t_max) if t_max is not None else None,
                "temp_min_f": _c_to_f(t_min) if t_min is not None else None,
                "precip_prob": prob,
                "weather_code": wcode,
                "icon": icon_id,
                "condition": condition,
                "precip_label": precip_label,
                "is_snow": is_snow,
                "snow_risk": _snow_risk(loc["elev"], t_max if t_max else 20, prob, wcode),
            })

        all_data[loc["name"]] = {
            "name": loc["name"],
            "elev": loc["elev"],
            "day_label": loc["day_label"],
            "forecasts": forecasts,
        }

    cache = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "locations": all_data,
    }

    with CACHE_LOCK:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))

    print(f"Weather cache updated at {cache['fetched_at']}")
    return cache


def load_cache():
    with CACHE_LOCK:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    return None


def get_weather():
    cache = load_cache()
    if cache:
        fetched = datetime.fromisoformat(cache["fetched_at"])
        age = datetime.now(timezone.utc) - fetched
        if age >= timedelta(hours=12):
            trigger_background_fetch()
        return cache

    trigger_background_fetch()
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "locations": {}}


def trigger_background_fetch():
    t = threading.Thread(target=fetch_weather, daemon=True)
    t.start()


def get_outlook_dates(cache):
    today = datetime.now(timezone.utc).date()
    return [(today + timedelta(days=i)).isoformat() for i in range(5)]


def get_hike_dates():
    return [(HIKE_START + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]


def days_until_departure():
    today = datetime.now(timezone.utc).date()
    delta = HIKE_START.date() - today
    return max(0, delta.days)


def forecast_for_date(location_data, date_str):
    for f in location_data.get("forecasts", []):
        if f["date"] == date_str:
            return f
    return None
