import requests
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

CACHE_FILE = Path("weather_cache.json")
CACHE_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()

YR_USER_AGENT = "SwissWeatherBulletin/1.0 github.com/boonespooner-bit/swissweather"

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

# Yr.no uses symbol_code strings — map to our icon IDs and conditions
YR_SYMBOL_MAP = {
    "clearsky": ("icon-sun", "Clear sky"),
    "fair": ("icon-partly", "Mostly clear"),
    "partlycloudy": ("icon-partly", "Partly cloudy"),
    "cloudy": ("icon-cloudy", "Overcast"),
    "fog": ("icon-cloudy", "Foggy"),
    "lightrain": ("icon-rain", "Light rain"),
    "rain": ("icon-rain", "Rain"),
    "heavyrain": ("icon-heavy-rain", "Heavy rain"),
    "lightrainshowers": ("icon-rain", "Light showers"),
    "rainshowers": ("icon-rain", "Showers"),
    "heavyrainshowers": ("icon-heavy-rain", "Heavy showers"),
    "lightsleet": ("icon-rain", "Light sleet"),
    "sleet": ("icon-rain", "Sleet"),
    "heavysleet": ("icon-heavy-rain", "Heavy sleet"),
    "lightsleetshowers": ("icon-rain", "Light sleet showers"),
    "sleetshowers": ("icon-rain", "Sleet showers"),
    "heavysleetshowers": ("icon-heavy-rain", "Heavy sleet showers"),
    "lightsnow": ("icon-snow", "Light snow"),
    "snow": ("icon-snow", "Snow"),
    "heavysnow": ("icon-snowstorm", "Heavy snow"),
    "lightsnowshowers": ("icon-snow", "Light snow showers"),
    "snowshowers": ("icon-snow", "Snow showers"),
    "heavysnowshowers": ("icon-snowstorm", "Heavy snow showers"),
    "lightrainandthunder": ("icon-thunder", "Rain & thunder"),
    "rainandthunder": ("icon-thunder", "Thunderstorm"),
    "heavyrainandthunder": ("icon-thunder", "Heavy thunderstorm"),
    "lightssleetandthunder": ("icon-thunder", "Sleet & thunder"),
    "sleetandthunder": ("icon-thunder", "Sleet & thunder"),
    "lightssnowandthunder": ("icon-thunder", "Snow & thunder"),
    "snowandthunder": ("icon-thunder", "Snow & thunder"),
    "rainshowersandthunder": ("icon-thunder", "Showers & thunder"),
    "heavyrainshowersandthunder": ("icon-thunder", "Heavy showers & thunder"),
    "snowshowersandthunder": ("icon-thunder", "Snow & thunder"),
}

YR_SNOW_SYMBOLS = {
    "lightsnow", "snow", "heavysnow",
    "lightsnowshowers", "snowshowers", "heavysnowshowers",
    "lightssnowandthunder", "snowandthunder", "snowshowersandthunder",
}


def _c_to_f(c):
    return round(c * 9 / 5 + 32)


def _snow_risk(elev, temp_max_c, precip_prob, is_snow):
    if elev >= 2500 and (temp_max_c <= 2 or is_snow):
        return "high"
    if elev >= 2000 and (temp_max_c <= 4 or is_snow):
        return "moderate" if not is_snow else "high"
    if precip_prob >= 50 and temp_max_c <= 5 and elev >= 1800:
        return "moderate"
    if elev >= 2500:
        return "moderate"
    return "low"


def _build_forecast_entry(date, t_max, t_min, precip_prob, icon_id, condition, is_snow, elev, source):
    precip_label = f"{precip_prob}% {'SNOW' if is_snow else 'rain'}"
    return {
        "date": date,
        "temp_max_c": t_max,
        "temp_min_c": t_min,
        "temp_max_f": _c_to_f(t_max) if t_max is not None else None,
        "temp_min_f": _c_to_f(t_min) if t_min is not None else None,
        "precip_prob": precip_prob,
        "icon": icon_id,
        "condition": condition,
        "precip_label": precip_label,
        "is_snow": is_snow,
        "snow_risk": _snow_risk(elev, t_max if t_max else 20, precip_prob, is_snow),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Open-Meteo
# ---------------------------------------------------------------------------

def _fetch_with_retry(url, params, headers=None, max_retries=3):
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code == 429:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited, retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def _fetch_open_meteo(loc):
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

        forecasts.append(_build_forecast_entry(
            d, t_max, t_min, prob, icon_id, condition, is_snow, loc["elev"], "Open-Meteo",
        ))

    return forecasts


# ---------------------------------------------------------------------------
# Yr.no (MET Norway / Locationforecast 2.0)
# ---------------------------------------------------------------------------

def _fetch_yr(loc):
    data = _fetch_with_retry(
        "https://api.met.no/weatherapi/locationforecast/2.0/compact",
        params={
            "lat": round(loc["lat"], 4),
            "lon": round(loc["lon"], 4),
            "altitude": loc["elev"],
        },
        headers={"User-Agent": YR_USER_AGENT},
    )

    timeseries = data.get("properties", {}).get("timeseries", [])
    if not timeseries:
        return []

    daily = {}
    for entry in timeseries:
        ts = entry.get("time", "")
        date_str = ts[:10]
        inst = entry.get("data", {}).get("instant", {}).get("details", {})
        temp = inst.get("air_temperature")

        next6 = entry.get("data", {}).get("next_6_hours", {})
        next12 = entry.get("data", {}).get("next_12_hours", {})

        symbol_raw = ""
        precip_max = 0
        for period in (next6, next12):
            if period:
                sym = period.get("summary", {}).get("symbol_code", "")
                if sym and not symbol_raw:
                    symbol_raw = sym
                pmax = period.get("details", {}).get("precipitation_amount_max", 0)
                precip_max = max(precip_max, pmax or 0)

        if date_str not in daily:
            daily[date_str] = {
                "temps": [],
                "symbols": [],
                "precip_max": 0,
            }

        if temp is not None:
            daily[date_str]["temps"].append(temp)
        if symbol_raw:
            daily[date_str]["symbols"].append(symbol_raw)
        daily[date_str]["precip_max"] = max(daily[date_str]["precip_max"], precip_max)

    forecasts = []
    for date_str in sorted(daily.keys()):
        day = daily[date_str]
        temps = day["temps"]
        if not temps:
            continue

        t_max = max(temps)
        t_min = min(temps)

        # Pick the most representative symbol (daytime preferred)
        symbol = day["symbols"][0] if day["symbols"] else "cloudy"
        base_symbol = symbol.split("_")[0]

        icon_id, condition = YR_SYMBOL_MAP.get(base_symbol, ("icon-cloudy", "Variable"))
        is_snow = base_symbol in YR_SNOW_SYMBOLS

        # Yr doesn't give precipitation probability directly; estimate from precip amount
        precip_max = day["precip_max"]
        if precip_max >= 5:
            precip_prob = 80
        elif precip_max >= 2:
            precip_prob = 60
        elif precip_max >= 0.5:
            precip_prob = 40
        elif precip_max > 0:
            precip_prob = 20
        else:
            precip_prob = 5

        forecasts.append(_build_forecast_entry(
            date_str, t_max, t_min, precip_prob, icon_id, condition, is_snow, loc["elev"], "Yr.no",
        ))

    return forecasts


# ---------------------------------------------------------------------------
# Fetch orchestration: Open-Meteo primary, Yr.no fallback
# ---------------------------------------------------------------------------

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
    sources_used = set()

    for idx, loc in enumerate(LOCATIONS):
        if idx > 0:
            time.sleep(1.5)

        forecasts = None
        source = None

        # Try Open-Meteo first
        try:
            forecasts = _fetch_open_meteo(loc)
            source = "Open-Meteo"
            print(f"  {loc['name']}: OK from Open-Meteo ({len(forecasts)} days)")
        except Exception as e:
            print(f"  {loc['name']}: Open-Meteo failed ({e}), trying Yr.no...")

        # Fall back to Yr.no
        if not forecasts:
            time.sleep(1)
            try:
                forecasts = _fetch_yr(loc)
                source = "Yr.no"
                print(f"  {loc['name']}: OK from Yr.no ({len(forecasts)} days)")
            except Exception as e:
                print(f"  {loc['name']}: Yr.no also failed ({e})")
                continue

        if forecasts:
            sources_used.add(source)
            all_data[loc["name"]] = {
                "name": loc["name"],
                "elev": loc["elev"],
                "day_label": loc["day_label"],
                "forecasts": forecasts,
                "source": source,
            }

    cache = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": sorted(sources_used),
        "locations": all_data,
    }

    with CACHE_LOCK:
        CACHE_FILE.write_text(json.dumps(cache, indent=2))

    print(f"Weather cache updated at {cache['fetched_at']} — sources: {', '.join(sorted(sources_used)) or 'none'}")
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
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "locations": {}, "sources": []}


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
