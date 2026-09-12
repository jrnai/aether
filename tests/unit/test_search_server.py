"""Unit tests for FastMCP DuckDuckGo search server, SSRF defenses, and untrusted quarantine."""
import re
from unittest.mock import MagicMock, patch

import pytest
from src.agent.guardrails import SafetyGuard
from src.servers.search_server import (
    _clean_html_text,
    _is_safe_url,
    _wrap_untrusted,
    fetch_web_page,
    mcp,
    search_web,
)

SAMPLE_DDG_HTML = """
<!DOCTYPE html>
<html>
<head><title>DuckDuckGo</title></head>
<body>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Fwhatsnew%2F3.13.html&rut=abc">
        What's New In Python 3.13 &mdash; Python Documentation
      </a>
    </h2>
    <a class="result__snippet" href="#">
      Comprehensive overview of Python 3.13 performance improvements and JIT.
    </a>
  </div>
</div>
<div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
    <h2 class="result__title">
      <a class="result__a" href="https://realpython.com/python313-features/">
        Real Python: Python 3.13 Features
      </a>
    </h2>
    <a class="result__snippet" href="#">
      A detailed guide to the new experimental free-threaded mode and standard library updates.
    </a>
  </div>
</div>
</body>
</html>
"""

SAMPLE_ARTICLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Python 3.13 Release Notes</title>
  <style>body { background: red; }</style>
  <script>console.log("malicious indirect prompt injection payload");</script>
</head>
<body>
  <header><nav>Home &gt; News</nav></header>
  <h1>Python 3.13 Overview</h1>
  <p>Python 3.13 introduces experimental JIT compilation and improved error tracebacks.</p>
  <p>Free-threading support (PEP 703) is also included as an optional build mode.</p>
  <footer>Copyright 2026 Python Software Foundation</footer>
</body>
</html>
"""


def test_search_web_empty_query() -> None:
    res = search_web("   ")
    assert "Error: Search query cannot be empty." in res


def test_search_web_success() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_DDG_HTML

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = search_web("python 3.13 features", max_results=5)

    assert "<untrusted_content source=\"web_search\"" in output
    assert "</untrusted_content>" in output
    assert "https://docs.python.org/3/whatsnew/3.13.html" in output
    assert "What's New In Python 3.13 — Python Documentation" in output
    assert "Comprehensive overview of Python 3.13" in output
    assert "https://realpython.com/python313-features/" in output


def test_search_web_max_results_limit() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_DDG_HTML

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = search_web("python", max_results=1)

    assert "1. [What's New In Python 3.13" in output
    assert "2. [Real Python" not in output


def test_search_web_no_results() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><div>No results found.</div></body></html>"

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = search_web("nonexistent term query")

    assert "No web search results found" in output


def test_search_web_http_error() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_resp
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = search_web("python query")

    assert "DuckDuckGo search error" in output or "HTTP 503" in output


def test_is_safe_url_ssrf() -> None:
    safe, _ = _is_safe_url("https://example.com/articles/1")
    assert safe is True

    safe, err = _is_safe_url("http://localhost:8000")
    assert safe is False
    assert "localhost" in err

    safe, err = _is_safe_url("http://127.0.0.1:8080")
    assert safe is False
    assert "127.0.0.1" in err

    safe, err = _is_safe_url("http://169.254.169.254/metadata")
    assert safe is False
    assert "169.254.169.254" in err

    safe, err = _is_safe_url("http://192.168.1.1/admin")
    assert safe is False
    assert "private IP" in err

    safe, err = _is_safe_url("file:///etc/passwd")
    assert safe is False
    assert "Unsupported URL scheme" in err


def test_clean_html_text() -> None:
    text = _clean_html_text(SAMPLE_ARTICLE_HTML)
    assert "console.log" not in text
    assert "background: red" not in text
    assert "Python 3.13 Overview" in text
    assert "Python 3.13 introduces experimental JIT" in text
    assert "Free-threading support" in text


def test_fetch_web_page_success() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.text = SAMPLE_ARTICLE_HTML

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = fetch_web_page("https://example.com/python-3-13")

    assert "<untrusted_content source=\"web_page\" url=\"https://example.com/python-3-13\">" in output
    assert "</untrusted_content>" in output
    assert "Title: Python 3.13 Release Notes" in output
    assert "Python 3.13 Overview" in output
    assert "console.log" not in output


def test_fetch_web_page_ssrf_blocked() -> None:
    output = fetch_web_page("http://127.0.0.1:5000/keys")
    assert "Error: Access to private/local destination '127.0.0.1' is blocked" in output


def test_fetch_web_page_truncation() -> None:
    long_html = "<html><head><title>Long</title></head><body>" + "<p>word </p>" * 3000 + "</body></html>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html"}
    mock_resp.text = long_html

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        output = fetch_web_page("https://example.com/long-page", max_chars=1000)

    assert "Truncated" in output


def test_guardrails_default_safe() -> None:
    guard = SafetyGuard()
    assert guard.is_safe("search_web") is True
    assert guard.is_safe("fetch_web_page") is True
    assert guard.requires_approval("search_web") is False
    assert guard.requires_approval("fetch_web_page") is False


def test_fastmcp_tools_registration() -> None:
    # Verify tools are registered on the FastMCP instance
    import asyncio
    tool_search = asyncio.run(mcp.get_tool("search_web"))
    tool_fetch = asyncio.run(mcp.get_tool("fetch_web_page"))
    assert tool_search is not None
    assert tool_search.name == "search_web"
    assert tool_fetch is not None
    assert tool_fetch.name == "fetch_web_page"

