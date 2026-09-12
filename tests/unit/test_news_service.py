"""Unit tests for Tech News Service and SQLite caching."""
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.servers.news_service import (
    fetch_and_cache_news,
    fetch_google_news,
    fetch_hacker_news,
    get_news,
    parse_rfc822_date,
)
from src.storage.db import DatabaseManager


SAMPLE_HN_RESPONSE = {
    "hits": [
        {
            "objectID": "41500001",
            "title": "Show HN: Fast local AI inference engine",
            "url": "https://github.com/example/engine",
            "points": 342,
            "num_comments": 85,
            "author": "devguru",
            "created_at": "2026-09-10T12:00:00Z",
        },
        {
            "objectID": "41500002",
            "story_title": "Ask HN: What are your favorite developer tools?",
            "url": None,
            "points": 120,
            "num_comments": 210,
            "author": "hacker1",
            "created_at": "2026-09-10T11:30:00Z",
        },
    ]
}

SAMPLE_GOOGLE_NEWS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News - Technology</title>
    <item>
      <title>Next-Gen Neural Chip Breakthrough - The Verge</title>
      <link>https://news.google.com/rss/articles/CBMi12345</link>
      <pubDate>Thu, 10 Sep 2026 10:15:00 GMT</pubDate>
      <source url="https://www.theverge.com">The Verge</source>
    </item>
    <item>
      <title>Open Source Foundation Releases Model - Ars Technica</title>
      <link>https://news.google.com/rss/articles/CBMi67890</link>
      <pubDate>Thu, 10 Sep 2026 09:00:00 GMT</pubDate>
      <source url="https://arstechnica.com">Ars Technica</source>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def temp_db(tmp_path: Path) -> DatabaseManager:
    """Create an isolated test SQLite database."""
    db_file = tmp_path / "test_news.db"
    return DatabaseManager(db_path=db_file)


def test_parse_rfc822_date() -> None:
    """Verify conversion of standard RSS pubDate strings to ISO 8601."""
    rfc_date = "Thu, 10 Sep 2026 10:15:00 GMT"
    iso_date = parse_rfc822_date(rfc_date)
    assert "2026-09-10" in iso_date

    # Fallback on empty or invalid
    fallback = parse_rfc822_date(None)
    assert fallback is not None


def test_fetch_hacker_news() -> None:
    """Verify parsing of Algolia Hacker News JSON payload."""
    mock_resp = io.BytesIO(json.dumps(SAMPLE_HN_RESPONSE).encode("utf-8"))

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        items = fetch_hacker_news(limit=10)

        assert len(items) == 2
        assert items[0]["id"] == "hn_41500001"
        assert items[0]["title"] == "Show HN: Fast local AI inference engine"
        assert items[0]["url"] == "https://github.com/example/engine"
        assert items[0]["score"] == 342
        assert items[0]["comments_count"] == 85
        assert items[0]["author"] == "devguru"

        # Verify fallback URL for Ask HN
        assert items[1]["id"] == "hn_41500002"
        assert items[1]["url"] == "https://news.ycombinator.com/item?id=41500002"


def test_fetch_google_news() -> None:
    """Verify parsing of Google News RSS XML payload."""
    mock_resp = io.BytesIO(SAMPLE_GOOGLE_NEWS_XML)

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        items = fetch_google_news(limit=10)

        assert len(items) == 2
        assert items[0]["source"] == "Google News"
        assert items[0]["author"] == "The Verge"
        assert "The Verge" not in items[0]["title"]  # Publisher cleaned from title
        assert items[0]["title"] == "Next-Gen Neural Chip Breakthrough"
        assert items[0]["url"] == "https://news.google.com/rss/articles/CBMi12345"

        assert items[1]["author"] == "Ars Technica"
        assert items[1]["title"] == "Open Source Foundation Releases Model"


def test_db_cache_and_query_news(temp_db: DatabaseManager) -> None:
    """Verify DatabaseManager news caching and filtering."""
    items = [
        {
            "id": "hn_101",
            "title": "Hacker News Story 1",
            "url": "https://news.ycombinator.com/item?id=101",
            "source": "Hacker News",
            "score": 500,
            "comments_count": 120,
            "author": "user1",
            "published_at": "2026-09-10T08:00:00Z",
        },
        {
            "id": "gn_201",
            "title": "Google News Story 2",
            "url": "https://news.google.com/articles/201",
            "source": "Google News",
            "score": 0,
            "comments_count": 0,
            "author": "TechCrunch",
            "published_at": "2026-09-10T07:30:00Z",
        },
    ]

    count = temp_db.cache_news_items(items)
    assert count == 2

    # Query all
    cached = temp_db.get_cached_news(limit=10)
    assert len(cached) == 2

    # Query filter by source
    hn_only = temp_db.get_cached_news(limit=10, source="Hacker News")
    assert len(hn_only) == 1
    assert hn_only[0]["id"] == "hn_101"

    gn_only = temp_db.get_cached_news(limit=10, source="Google News")
    assert len(gn_only) == 1
    assert gn_only[0]["id"] == "gn_201"


def test_db_prune_old_news(temp_db: DatabaseManager) -> None:
    """Verify prune_old_news cleans up stories older than max_age_hours."""
    old_time = (datetime.now().astimezone() - timedelta(hours=80)).isoformat()
    fresh_time = datetime.now().astimezone().isoformat()

    items = [
        {
            "id": "old_1",
            "title": "Ancient Story",
            "url": "https://example.com/old",
            "source": "Hacker News",
            "published_at": old_time,
        },
        {
            "id": "fresh_1",
            "title": "Fresh Story",
            "url": "https://example.com/fresh",
            "source": "Google News",
            "published_at": fresh_time,
        },
    ]

    temp_db.cache_news_items(items)

    with temp_db._get_connection() as conn:
        conn.execute("UPDATE cached_news SET fetched_at = ? WHERE id = 'old_1'", (old_time,))

    deleted = temp_db.prune_old_news(max_age_hours=72)
    assert deleted == 1

    remaining = temp_db.get_cached_news(limit=10)
    assert len(remaining) == 1
    assert remaining[0]["id"] == "fresh_1"


def test_get_news_cache_hit_avoids_network(temp_db: DatabaseManager) -> None:
    """Verify get_news returns from SQLite immediately when cache is fresh."""
    now_iso = datetime.now().astimezone().isoformat()
    temp_db.cache_news_items([
        {
            "id": "cached_story_1",
            "title": "Fast Cached Story",
            "url": "https://example.com/fast",
            "source": "Hacker News",
            "score": 100,
            "comments_count": 25,
            "published_at": now_iso,
        }
    ])

    with patch("src.servers.news_service.fetch_hacker_news") as mock_hn, \
         patch("src.servers.news_service.fetch_google_news") as mock_gn:
        results = get_news(db=temp_db, limit=10, force_refresh=False)
        assert len(results) == 1
        assert results[0]["id"] == "cached_story_1"
        mock_hn.assert_not_called()
        mock_gn.assert_not_called()


def test_get_news_force_refresh_triggers_fetch(temp_db: DatabaseManager) -> None:
    """Verify force_refresh=True invokes live network fetch and updates SQLite."""
    with patch("src.servers.news_service.fetch_hacker_news", return_value=[{
        "id": "hn_new",
        "title": "Newly Fetched HN Story",
        "url": "https://example.com/new",
        "source": "Hacker News",
        "score": 50,
        "comments_count": 10,
        "author": "author",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "summary": "Fast engine for local inference.",
        "category": "ai_ml",
    }]), patch("src.servers.news_service.fetch_google_news", return_value=[]), \
         patch("src.servers.news_service.fetch_google_ai_news", return_value=[]), \
         patch("src.servers.news_service.fetch_techcrunch_ai", return_value=[]):
        results = get_news(db=temp_db, limit=10, force_refresh=True)
        assert len(results) == 1
        assert results[0]["id"] == "hn_new"
        assert results[0]["summary"] == "Fast engine for local inference."
        assert results[0]["category"] == "ai_ml"

        # Verify persisted into DB
        cached = temp_db.get_cached_news(limit=10)
        assert len(cached) == 1
        assert cached[0]["id"] == "hn_new"


def test_get_news_handles_naive_timestamp(temp_db: DatabaseManager) -> None:
    """Verify get_news gracefully handles offset-naive timestamp in fetched_at without crashing."""
    naive_recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    temp_db.cache_news_items([
        {
            "id": "cached_story_naive",
            "title": "Naive Timestamp Story",
            "url": "https://example.com/naive",
            "source": "Hacker News",
            "published_at": naive_recent,
        }
    ])
    with temp_db._get_connection() as conn:
        conn.execute("UPDATE cached_news SET fetched_at = ? WHERE id = 'cached_story_naive'", (naive_recent,))

    with patch("src.servers.news_service.fetch_hacker_news") as mock_hn:
        results = get_news(db=temp_db, limit=10, force_refresh=False)
        assert len(results) == 1
        assert results[0]["id"] == "cached_story_naive"
        mock_hn.assert_not_called()


def test_fetch_hacker_news_rejects_unsafe_schemes() -> None:
    """Verify stories with javascript: or invalid schemes fall back to the HN discussion URL."""
    payload = {
        "hits": [
            {
                "objectID": "9999",
                "title": "XSS Attempt Story",
                "url": "javascript:alert(1)",
                "points": 10,
                "created_at": "2026-09-10T12:00:00Z",
            }
        ]
    }
    mock_resp = io.BytesIO(json.dumps(payload).encode("utf-8"))
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        items = fetch_hacker_news(limit=5)
        assert len(items) == 1
        assert items[0]["url"] == "https://news.ycombinator.com/item?id=9999"


def test_fetch_and_cache_news_dedupes_symbol_titles(temp_db: DatabaseManager) -> None:
    """Verify titles with only symbols/emojis don't erroneously collide due to empty norm_title."""
    items_hn = [
        {"id": "hn_1", "title": "⚡⚡⚡", "url": "https://example.com/1", "source": "Hacker News"},
        {"id": "hn_2", "title": "🚀🚀🚀", "url": "https://example.com/2", "source": "Hacker News"},
    ]
    with patch("src.servers.news_service.fetch_hacker_news", return_value=items_hn), \
         patch("src.servers.news_service.fetch_google_news", return_value=[]), \
         patch("src.servers.news_service.fetch_google_ai_news", return_value=[]), \
         patch("src.servers.news_service.fetch_techcrunch_ai", return_value=[]):
        cached = fetch_and_cache_news(db=temp_db, limit_per_source=10)
        assert len(cached) == 2
        titles = {c["title"] for c in cached}
        assert "⚡⚡⚡" in titles
        assert "🚀🚀🚀" in titles


def test_ai_student_digest_deterministic_fallback(temp_db: DatabaseManager) -> None:
    """Verify generate_ai_student_digest provides a complete fallback when Ollama is offline."""
    from src.servers.news_service import generate_ai_student_digest, get_ai_student_digest

    items = [
        {
            "id": "1",
            "title": "Open-Weights Reasoning LLM Released for Autonomous Coding",
            "url": "https://example.com/reasoning-model",
            "source": "TechCrunch AI",
            "category": "ai_ml",
            "summary": "New open weights model matches closed frontier systems in code generation.",
        },
        {
            "id": "2",
            "title": "vLLM 0.7 Introduces Speculative Decoding Pipeline",
            "url": "https://example.com/vllm",
            "source": "Hacker News",
            "category": "dev_tools",
            "summary": "Massive throughput upgrade for running local open-source LLMs.",
        },
    ]

    # Deterministic extraction without Ollama
    digest = generate_ai_student_digest(items, ollama_client=None)
    assert digest["headline"]
    assert digest["executive_takeaway"]
    assert len(digest["models_and_research"]) > 0
    assert len(digest["developer_tools"]) > 0
    assert digest["student_project_takeaway"]["title"]
    assert digest["student_project_takeaway"]["tech_stack"]

    # Caching verification in db
    cached_digest = get_ai_student_digest(db=temp_db, ollama_client=None, force_refresh=True)
    assert cached_digest["headline"]
    # Subsequent call hits cache without regeneration
    hit = get_ai_student_digest(db=temp_db, ollama_client=None, force_refresh=False)
    assert hit["headline"] == cached_digest["headline"]

