"""Unit tests for Aether weather service, intent detection, and ReDoS prevention."""

import io
import json
import re
import time
from unittest.mock import MagicMock, patch
import urllib.request
import urllib.error

import pytest

from src.agent.loop import TOOL_DOMAINS, DOMAIN_KEYWORDS, detect_intent_domains, get_tool_domain
from src.servers.weather_server import (
    fetch_weather_forecast,
    get_current_weather,
    get_default_weather_location,
    set_default_weather_location,
    DEFAULT_WEATHER_LOCATION,
    _WEATHER_CACHE,
)

SAMPLE_WTTR_JSON = {
    "current_condition": [
        {
            "temp_C": "14",
            "temp_F": "57",
            "FeelsLikeC": "13",
            "FeelsLikeF": "55",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "humidity": "62",
            "windspeedKmph": "19",
            "winddir16Point": "WSW",
            "uvIndex": "3",
        }
    ],
    "nearest_area": [
        {
            "areaName": [{"value": "Kingston"}],
            "region": [{"value": "Ontario"}],
            "country": [{"value": "Canada"}],
        }
    ],
    "weather": [
        {
            "date": "2026-09-12",
            "maxtempC": "18",
            "mintempC": "10",
            "hourly": [
                {"weatherDesc": [{"value": "Sunny"}]},
                {"weatherDesc": [{"value": "Partly cloudy"}]},
            ],
        },
        {
            "date": "2026-09-13",
            "maxtempC": "20",
            "mintempC": "12",
            "hourly": [
                {"weatherDesc": [{"value": "Clear"}]},
            ],
        },
    ],
}


def _mock_response(status=200, json_data=None):
    mock = MagicMock()
    mock.status = status
    payload = json.dumps(json_data or {}).encode("utf-8")
    mock.read.return_value = payload
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = None
    return mock


def test_get_current_weather_success():
    """Verify that get_current_weather parses structured weather accurately."""
    with patch("urllib.request.urlopen", return_value=_mock_response(200, SAMPLE_WTTR_JSON)):
        result = get_current_weather("Kingston, Ontario")

    assert "Weather Report for Kingston, Ontario, Canada:" in result
    assert "Condition: Partly cloudy" in result
    assert "Temperature: 14 C (57 F)" in result
    assert "Feels Like: 13 C (55 F)" in result
    assert "Humidity: 62%" in result
    assert "Wind: 19 km/h WSW" in result
    assert "UV Index: 3" in result
    assert "Upcoming Forecast:" in result
    assert "2026-09-12: Partly cloudy, High: 18 C, Low: 10 C" in result


def test_get_current_weather_auto_location():
    """Verify that 'auto' and 'here' trigger IP-based auto location."""
    captured_urls = []

    def mock_urlopen(req, timeout=None):
        captured_urls.append(req.full_url)
        return _mock_response(200, SAMPLE_WTTR_JSON)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        get_current_weather("auto")
        get_current_weather("here")

    assert len(captured_urls) == 2
    assert captured_urls[0] == "https://wttr.in/?format=j1"
    assert captured_urls[1] == "https://wttr.in/?format=j1"


def test_get_current_weather_http_error():
    """Verify handling of HTTP errors from weather provider."""
    with patch("urllib.request.urlopen", return_value=_mock_response(503, {})):
        result = get_current_weather("Tokyo")

    assert "Weather service error: received HTTP 503" in result


def test_get_current_weather_network_exception():
    """Verify graceful handling when network times out or raises an exception."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection timed out")):
        result = get_current_weather("Tokyo")

    assert "Unable to retrieve real-time weather for 'Tokyo'" in result
    assert "Connection timed out" in result


def test_get_current_weather_zero_emojis():
    """Verify strictly zero emojis in output per Aether design rules."""
    with patch("urllib.request.urlopen", return_value=_mock_response(200, SAMPLE_WTTR_JSON)):
        result = get_current_weather("Kingston")

    # Range of emoji characters
    for char in result:
        code = ord(char)
        assert not (
            0x1F600 <= code <= 0x1F64F
            or 0x1F300 <= code <= 0x1F5FF
            or 0x1F680 <= code <= 0x1F6FF
            or 0x2600 <= code <= 0x26FF
            or 0x2700 <= code <= 0x27BF
            or 0x1F900 <= code <= 0x1F9FF
        ), f"Unexpected emoji detected: {char} (U+{code:04X})"


def test_weather_tool_domain_and_intent():
    """Verify that weather tools are mapped to 'web' domain and weather queries trigger 'web' intent."""
    assert "get_weather" in TOOL_DOMAINS["web"]
    assert "get_current_weather" in TOOL_DOMAINS["web"]
    assert get_tool_domain("get_weather") == "web"
    assert get_tool_domain("get_current_weather") == "web"

    # Intent detection
    assert "web" in detect_intent_domains("what is the weather in kingston?")
    assert "web" in detect_intent_domains("check the temperature outside")
    assert "web" in detect_intent_domains("is it going to rain tomorrow?")
    assert "web" in detect_intent_domains("whats the 3 day forecast?")


def test_markdown_url_regex_linear_time_redos_immune():
    """Verify that the markdown URL linking regex processes trailing-dot URLs in microsecond linear time without ReDoS."""
    safe_pattern = re.compile(
        r"(^|[\s(]|&lt;)((?:https?|file)://[^\s()<>\"]+[^\s()<>\'.,:;?!\]\)])(?=[\s)]|&gt;|$)"
    )

    # Incomplete streaming URLs that triggered catastrophic backtracking in the old nested regex
    malicious_inputs = [
        "Check here: https://www.theweathernetwork." + "." * 40,
        "Weather at https://weather.gc.ca/en/location/index.html?coords=44.23,-76.48" + "/" * 30,
        "Source: https://en.wikipedia.org/wiki/Weather_forecast" + "!" * 35,
    ]

    for text in malicious_inputs:
        start = time.perf_counter()
        matches = list(safe_pattern.finditer(text))
        elapsed = time.perf_counter() - start
        assert elapsed < 0.005, f"Regex took {elapsed:.4f}s, potential ReDoS detected!"


def test_fetch_weather_forecast_structure():
    """Verify that fetch_weather_forecast returns structured current conditions and hourly breakdown."""
    _WEATHER_CACHE.clear()
    with patch("urllib.request.urlopen", return_value=_mock_response(200, SAMPLE_WTTR_JSON)):
        data = fetch_weather_forecast("Kingston Downtown, Ontario")

    assert data["status"] == "success"
    assert "Kingston" in data["location"]
    assert data["current"]["temp_c"] == "14"
    assert data["current"]["condition"] == "Partly cloudy"
    assert data["current"]["humidity"] == "62"
    assert data["current"]["wind_kmph"] == "19"
    assert data["current"]["wind_dir"] == "WSW"

    today = data["today"]
    assert today["date"] == "2026-09-12"
    assert today["max_c"] == "18"
    assert today["min_c"] == "10"
    assert len(today["hourly"]) == 2

    h0 = today["hourly"][0]
    assert "time" in h0
    assert "time_label" in h0
    assert "temp_c" in h0
    assert "wind_kmph" in h0
    assert "rain_chance" in h0
    assert "condition" in h0


def test_fetch_weather_forecast_caching():
    """Verify that fetch_weather_forecast caches results and force_refresh bypasses cache."""
    _WEATHER_CACHE.clear()
    call_count = 0

    def mock_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        return _mock_response(200, SAMPLE_WTTR_JSON)

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # First call: hits network
        res1 = fetch_weather_forecast("Kingston Downtown, Ontario")
        assert call_count == 1

        # Second call: served from cache
        res2 = fetch_weather_forecast("Kingston Downtown, Ontario")
        assert call_count == 1
        assert res1 == res2

        # Third call with force_refresh=True: hits network
        res3 = fetch_weather_forecast("Kingston Downtown, Ontario", force_refresh=True)
        assert call_count == 2


def test_weather_location_get_and_set():
    """Verify persistent setting and retrieval of default weather location."""
    initial = get_default_weather_location()
    assert isinstance(initial, str) and len(initial) > 0

    # Set new location
    new_loc = set_default_weather_location("Tokyo, Japan")
    assert new_loc == "Tokyo, Japan"
    assert get_default_weather_location() == "Tokyo, Japan"

    # Reset back to initial location
    set_default_weather_location(initial)
    assert get_default_weather_location() == initial


def test_set_weather_location_tool_in_loop():
    """Verify that set_weather_location tool is registered in TOOL_DOMAINS and loop."""
    assert "set_weather_location" in TOOL_DOMAINS["web"]
    assert get_tool_domain("set_weather_location") == "web"


def test_search_weather_locations():
    """Verify that search_weather_locations parses geocoding results accurately."""
    from src.servers.weather_server import search_weather_locations

    # Short query returns empty immediately
    assert search_weather_locations("") == []
    assert search_weather_locations("a") == []

    mock_geo_json = {
        "results": [
            {
                "name": "Kingston",
                "admin1": "Ontario",
                "country": "Canada",
                "country_code": "CA",
                "latitude": 44.23,
                "longitude": -76.48,
            },
            {
                "name": "Kingston",
                "admin1": "Kingston",
                "country": "Jamaica",
                "country_code": "JM",
                "latitude": 17.99,
                "longitude": -76.79,
            },
        ]
    }

    with patch("urllib.request.urlopen", return_value=_mock_response(200, mock_geo_json)):
        results = search_weather_locations("Kingston")

    assert len(results) == 2
    assert results[0]["formatted"] == "Kingston, Ontario, Canada"
    assert results[0]["name"] == "Kingston"
    assert results[0]["region"] == "Ontario"
    assert results[1]["formatted"] == "Kingston, Jamaica"


