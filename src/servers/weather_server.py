"""Weather service and tool for Project Aether.

Provides fast, accurate, real-time weather and hourly/daily forecasts for any city or location worldwide.
Adheres to Project Aether Core Philosophy:
- Zero API keys or user credentials required (free, privacy-preserving).
- Uses Python standard library (urllib.request) with timeout protection.
- Strictly ZERO emojis in output text (clean, technical, structured markdown and JSON).
"""

import json
import logging
import ssl
import time
from typing import Any
import urllib.parse
import urllib.request

logger = logging.getLogger("aether.weather")

_WEATHER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS: float = 600.0  # 10 minutes cache TTL

DEFAULT_WEATHER_LOCATION: str = "Kingston Downtown, Ontario"


def _urlopen_with_ssl_fallback(req: urllib.request.Request, timeout: float = 6.0):
    """Safely open public weather endpoints with fallback if local system clock drifts."""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:
        # ponytail: deliberate SSL fallback for read-only public weather data when local clock drifts
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or isinstance(e, ssl.SSLCertVerificationError):
            logger.debug("SSL verify failed (%s), retrying with unverified context", e)
            try:
                unverified_ctx = ssl.create_default_context()
                unverified_ctx.check_hostname = False
                unverified_ctx.verify_mode = ssl.CERT_NONE
                return urllib.request.urlopen(req, timeout=timeout, context=unverified_ctx)
            except TypeError:
                return urllib.request.urlopen(req, timeout=timeout)
        raise


def get_default_weather_location() -> str:
    """Get the currently configured weather location from persistent storage or default."""
    try:
        from src.storage.db import DatabaseManager
        db = DatabaseManager()
        loc = db.get_state("weather_location")
        if loc and loc.strip():
            return loc.strip()
    except Exception as e:
        logger.debug("Failed to read weather_location from db: %s", e)
    return DEFAULT_WEATHER_LOCATION


def set_default_weather_location(location: str) -> str:
    """Save a new persistent weather location for the dashboard and assistant.

    Args:
        location: Target city or location name (e.g. 'Tokyo', 'Toronto, Ontario').

    Returns:
        The newly saved location string.
    """
    clean = (location or DEFAULT_WEATHER_LOCATION).strip()
    if not clean or clean.lower() in ("auto", "here", "current", "my location", "local", "me"):
        clean = DEFAULT_WEATHER_LOCATION

    try:
        from src.storage.db import DatabaseManager
        db = DatabaseManager()
        db.set_state("weather_location", clean)
        logger.info("Saved persistent weather location: '%s'", clean)
    except Exception as e:
        logger.warning("Failed to save weather_location to db: %s", e)

    _WEATHER_CACHE.pop(clean.lower(), None)
    return clean


def fetch_weather_forecast(
    location: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Fetch structured current weather and hourly/daily forecast data for a specified location.

    Zero API keys required. Uses open public weather data endpoints with 10-minute caching.

    Args:
        location: City or location name. Defaults to configured location or Kingston Downtown.
        force_refresh: If True, bypass in-memory cache and fetch live data.

    Returns:
        Structured dict with current conditions, day0 high/low, and 8-period hourly breakdown.
    """
    if not location or not location.strip():
        clean_loc = get_default_weather_location()
    else:
        clean_loc = location.strip()
    cache_key = clean_loc.lower()

    now_ts = time.time()
    if not force_refresh and cache_key in _WEATHER_CACHE:
        cached_ts, cached_data = _WEATHER_CACHE[cache_key]
        if (now_ts - cached_ts) < _CACHE_TTL_SECONDS:
            return cached_data

    if clean_loc.lower() in ("auto", "here", "current", "my location", "local", "me"):
        query = ""
    else:
        query = clean_loc

    encoded_query = urllib.parse.quote(query)
    url = f"https://wttr.in/{encoded_query}?format=j1"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AetherWeather/1.0",
        "Accept": "application/json",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with _urlopen_with_ssl_fallback(req, timeout=6.0) as resp:
            if resp.status != 200:
                return {
                    "status": "error",
                    "message": f"Weather service error: received HTTP {resp.status}",
                    "location": clean_loc,
                }
            raw_bytes = resp.read()
            data = json.loads(raw_bytes.decode("utf-8", errors="replace"))

        current = data.get("current_condition", [{}])[0]
        nearest_area = data.get("nearest_area", [{}])[0]

        city = nearest_area.get("areaName", [{}])[0].get("value", clean_loc or "Current Location")
        region = nearest_area.get("region", [{}])[0].get("value", "")
        country = nearest_area.get("country", [{}])[0].get("value", "")

        loc_parts = [p for p in (city, region, country) if p]
        loc_display = ", ".join(loc_parts) if loc_parts else (clean_loc or "Current Location")

        temp_c = current.get("temp_C", "N/A")
        temp_f = current.get("temp_F", "N/A")
        feels_c = current.get("FeelsLikeC", "N/A")
        feels_f = current.get("FeelsLikeF", "N/A")
        desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown").strip()
        humidity = current.get("humidity", "0")
        wind_km = current.get("windspeedKmph", "0")
        wind_dir = current.get("winddir16Point", "")
        uv = current.get("uvIndex", "0")

        weather_days = data.get("weather", [])
        day0 = weather_days[0] if weather_days else {}
        date_str = day0.get("date", "")
        max_c = day0.get("maxtempC", "N/A")
        min_c = day0.get("mintempC", "N/A")
        max_f = day0.get("maxtempF", "N/A")
        min_f = day0.get("mintempF", "N/A")

        astronomy = day0.get("astronomy", [{}])[0] if day0.get("astronomy") else {}
        sunrise = astronomy.get("sunrise", "")
        sunset = astronomy.get("sunset", "")

        hourly_list: list[dict[str, Any]] = []
        for h in day0.get("hourly", []):
            try:
                raw_t = int(h.get("time", "0"))
            except (ValueError, TypeError):
                raw_t = 0
            hour_num = raw_t // 100
            time_str = f"{hour_num:02d}:00"
            display_12h = f"{(hour_num % 12) or 12} {'AM' if hour_num < 12 else 'PM'}"

            try:
                rain_pct = int(h.get("chanceofrain", 0))
            except (ValueError, TypeError):
                rain_pct = 0

            h_desc = h.get("weatherDesc", [{}])[0].get("value", "Unknown").strip()

            hourly_list.append({
                "time": time_str,
                "time_label": display_12h,
                "temp_c": h.get("tempC", "N/A"),
                "temp_f": h.get("tempF", "N/A"),
                "feels_c": h.get("FeelsLikeC", "N/A"),
                "feels_f": h.get("FeelsLikeF", "N/A"),
                "wind_kmph": h.get("windspeedKmph", "0"),
                "wind_dir": h.get("winddir16Point", ""),
                "rain_chance": rain_pct,
                "condition": h_desc,
            })

        forecast_days = []
        for d in weather_days:
            day_desc = ""
            hourly = d.get("hourly", [])
            if hourly:
                mid = hourly[len(hourly) // 2]
                day_desc = mid.get("weatherDesc", [{}])[0].get("value", "")
            forecast_days.append({
                "date": d.get("date", ""),
                "condition": day_desc,
                "max_c": d.get("maxtempC", ""),
                "min_c": d.get("mintempC", ""),
                "max_f": d.get("maxtempF", ""),
                "min_f": d.get("mintempF", ""),
            })

        result = {
            "status": "success",
            "location": loc_display,
            "query": clean_loc,
            "configured_location": get_default_weather_location(),
            "current": {
                "temp_c": temp_c,
                "temp_f": temp_f,
                "feels_c": feels_c,
                "feels_f": feels_f,
                "condition": desc,
                "humidity": humidity,
                "wind_kmph": wind_km,
                "wind_dir": wind_dir,
                "uv": uv,
            },
            "today": {
                "date": date_str,
                "max_c": max_c,
                "min_c": min_c,
                "max_f": max_f,
                "min_f": min_f,
                "sunrise": sunrise,
                "sunset": sunset,
                "hourly": hourly_list,
            },
            "forecast_days": forecast_days,
        }

        _WEATHER_CACHE[cache_key] = (now_ts, result)
        return result

    except Exception as e:
        logger.warning("Weather query failed for '%s': %s", clean_loc, e)
        return {
            "status": "error",
            "message": str(e),
            "location": clean_loc,
        }


def get_current_weather(location: str = "auto") -> str:
    """Fetch current weather and 3-day forecast for a specified city or location.

    Zero API keys required. Uses open public weather data endpoints.

    Args:
        location: City or location name (e.g. "Kingston, Ontario", "New York", "London", "Tokyo").
                  Defaults to "auto" to detect location automatically.

    Returns:
        Structured text summary with conditions, temperature, humidity, wind, and 3-day forecast.
    """
    clean_loc = (location or "auto").strip()
    res = fetch_weather_forecast(clean_loc)

    if res.get("status") == "error":
        return f"Unable to retrieve real-time weather for '{clean_loc}': {res.get('message', 'Unknown error')}"

    loc_display = res.get("location", clean_loc)
    cur = res.get("current", {})
    desc = cur.get("condition", "Unknown")
    temp_c = cur.get("temp_c", "N/A")
    temp_f = cur.get("temp_f", "N/A")
    feels_c = cur.get("feels_c", "N/A")
    feels_f = cur.get("feels_f", "N/A")
    humidity = cur.get("humidity", "N/A")
    wind_km = cur.get("wind_kmph", "N/A")
    wind_dir = cur.get("wind_dir", "")
    uv = cur.get("uv", "N/A")

    lines = [
        f"Weather Report for {loc_display}:",
        f"- Condition: {desc}",
        f"- Temperature: {temp_c} C ({temp_f} F)",
        f"- Feels Like: {feels_c} C ({feels_f} F)",
        f"- Humidity: {humidity}%",
        f"- Wind: {wind_km} km/h {wind_dir}".strip(),
        f"- UV Index: {uv}",
    ]

    weather_days = res.get("forecast_days", [])
    if weather_days:
        lines.append("\nUpcoming Forecast:")
        for day in weather_days[:3]:
            date = day.get("date", "")
            max_c = day.get("max_c", "")
            min_c = day.get("min_c", "")
            desc = day.get("condition", "")
            desc_prefix = f"{desc}, " if desc else ""
            lines.append(f"- {date}: {desc_prefix}High: {max_c} C, Low: {min_c} C")

    return "\n".join(lines)


def search_weather_locations(query: str, count: int = 6) -> list[dict[str, Any]]:
    """Search for matching cities and geographic locations using Open-Meteo Geocoding.

    Zero API keys required. Free, open, and fast.

    Args:
        query: Partial or full location name (e.g. 'King', 'Tokyo', 'Toronto').
        count: Maximum number of suggestions to return (default 6).

    Returns:
        List of structured location dictionaries with name, region, country, and formatted label.
    """
    clean_query = (query or "").strip()
    if len(clean_query) < 2:
        return []

    encoded = urllib.parse.quote(clean_query)
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count={count}&language=en&format=json"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AetherWeather/1.0",
            "Accept": "application/json",
        },
    )

    try:
        with _urlopen_with_ssl_fallback(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_results = data.get("results", [])
            output = []
            for item in raw_results:
                name = item.get("name", "")
                admin1 = item.get("admin1", "")
                country = item.get("country", "")
                country_code = item.get("country_code", "")

                parts = [name]
                if admin1 and admin1 != name:
                    parts.append(admin1)
                if country:
                    parts.append(country)

                formatted = ", ".join(parts)
                output.append({
                    "name": name,
                    "region": admin1,
                    "country": country,
                    "country_code": country_code,
                    "formatted": formatted,
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                })
            return output
    except Exception as e:
        logger.debug("Failed to query Open-Meteo Geocoding for '%s': %s", clean_query, e)
        return []
